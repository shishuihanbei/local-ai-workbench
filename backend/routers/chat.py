"""对话：会话/消息管理、SSE 流式生成、语音朗读。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from ..errors import QUOTA_EXCEEDED, APIError
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import logbus, pipeline
from ..config import load_config
from ..db import audit, execute, fetch_all, fetch_one, parse_meta
from ..security import current_user, user_from_any_token
from ..services import (access, admission, agent, attachments, cluster, collab, docgen, kb,
                        library, llama, memory, model_fit, model_usage, moderation,
                        prompts, quota, routing, skills, tts, websearch)

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 24000


def _node_headers(candidate: dict) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if candidate.get("key"):
        headers["Authorization"] = f"Bearer {candidate['key']}"
    return headers


class ConversationBody(BaseModel):
    title: str | None = None
    system_prompt: str | None = None


class ChatBody(BaseModel):
    conversation_id: int | None = None
    message: str
    model: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    use_kb: bool | None = None
    library_docs: list[int] = Field(default_factory=list)
    regenerate: bool = False
    attachments: list[int] = Field(default_factory=list)
    vision: bool = False          # 当前模型是视觉模型，图片以 image_url 直接送入
    skill: str | None = None
    web: bool = False
    agent_id: int | None = None
    agent_mode: bool | None = None
    output_format: str | None = None


class TTSBody(BaseModel):
    text: str
    voice: str | None = None


# ------------------------------------------------------------------ 会话
@router.get("/chat/skills")
async def list_skills(user: dict = Depends(current_user)):
    return {"items": skills.list_public()}


@router.get("/chat/conversations")
async def list_conversations(user: dict = Depends(current_user), q: str = ""):
    if q:
        rows = await fetch_all(
            "SELECT id,title,model,pinned,created_at,updated_at FROM conversations "
            "WHERE user_id=? AND title LIKE ? ORDER BY pinned DESC, updated_at DESC LIMIT 200",
            (user["id"], f"%{q}%"))
    else:
        rows = await fetch_all(
            "SELECT id,title,model,pinned,created_at,updated_at FROM conversations "
            "WHERE user_id=? ORDER BY pinned DESC, updated_at DESC LIMIT 200", (user["id"],))
    return {"items": rows}


@router.post("/chat/conversations")
async def create_conversation(body: ConversationBody, user: dict = Depends(current_user)):
    now = time.time()
    cid = await execute(
        "INSERT INTO conversations(user_id,title,model,system_prompt,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (user["id"], (body.title or "新对话")[:120], "", body.system_prompt, now, now))
    return {"id": cid}


@router.post("/chat/conversations/clear-all")
async def clear_all_conversations(user: dict = Depends(current_user)):
    await execute("DELETE FROM messages WHERE conversation_id IN "
                  "(SELECT id FROM conversations WHERE user_id=?)", (user["id"],))
    await execute("DELETE FROM conversations WHERE user_id=?", (user["id"],))
    return {"ok": True}


@router.patch("/chat/conversations/{cid}")
async def patch_conversation(cid: int, body: ConversationBody, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, user["id"]))
    if not row:
        raise HTTPException(404, "会话不存在")
    if body.title is not None:
        await execute("UPDATE conversations SET title=? WHERE id=?", (body.title[:120], cid))
    if body.system_prompt is not None:
        await execute("UPDATE conversations SET system_prompt=? WHERE id=?", (body.system_prompt, cid))
    return {"ok": True}


@router.delete("/chat/conversations/{cid}")
async def delete_conversation(cid: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT id FROM conversations WHERE id=? AND user_id=?", (cid, user["id"]))
    if not row:
        raise HTTPException(404, "会话不存在")
    await execute("DELETE FROM conversations WHERE id=?", (cid,))
    return {"ok": True}


@router.get("/chat/conversations/{cid}/messages")
async def messages(cid: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, user["id"]))
    if not row:
        raise HTTPException(404, "会话不存在")
    rows = await fetch_all(
        "SELECT id,role,content,reasoning,tokens,meta,created_at FROM messages "
        "WHERE conversation_id=? ORDER BY id", (cid,))
    for r in rows:
        r["meta"] = parse_meta(r.get("meta"))
        meta = r["meta"] if isinstance(r["meta"], dict) else {}
        files = meta.get("files")
        if isinstance(files, list) and files:
            try:
                await docgen.enrich_file_list(files, user["id"])
            except Exception:
                pass
    return {"conversation": row, "items": rows}


@router.post("/chat/conversations/{cid}/clear")
async def clear_messages(cid: int, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT id FROM conversations WHERE id=? AND user_id=?", (cid, user["id"]))
    if not row:
        raise HTTPException(404, "会话不存在")
    await execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ 生成
def _tokens(text: str) -> int:
    return max(1, len(text) // 2)


def _content_with_images(text: str, images: list[dict]) -> str | list[dict]:
    """OpenAI 兼容的视觉消息：文字块 + image_url 块。"""
    if not images:
        return text
    parts: list[dict] = [{"type": "text", "text": text or "请查看这张图片。"}]
    parts.extend(images)
    return parts


def _content_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


async def _build_context(user: dict, body: ChatBody, cfg: dict,
                         att_rows: list[dict] | None = None,
                         skill: dict | None = None) -> tuple[list[dict], int, dict]:
    system_prompt = body.system_prompt or prompts.get(
        "core.system", cfg.get("system_prompt") or "")
    use_kb = cfg.get("kb_enabled", False) if body.use_kb is None else body.use_kb
    meta: dict[str, Any] = {}
    msgs: list[dict] = []
    if skill is None:
        skill = skills.get(body.skill)
    if att_rows is None:
        att_rows = await attachments.load_many(user["id"], body.attachments) if not body.regenerate else []
    if body.vision:
        current_images, current_image_ids = await attachments.vision_payload(att_rows)
    else:
        current_images, current_image_ids = [], []
    att_text = attachments.context_block(att_rows, skip_image_ids=set(current_image_ids))
    link_unreadable = False
    link_title = ""
    if att_rows:
        link_source = "\n".join(str(r.get("text_content") or "") for r in att_rows)
        if "http://" in link_source or "https://" in link_source:
            try:
                link_block = await websearch.read_links(link_source)
                if link_block:
                    att_text = (att_text + "\n\n" + link_block).strip()
                    link_unreadable = "未取到正文" in link_block
                    m = re.search(r"网页标题：([^\n]+)", link_block)
                    link_title = (m.group(1).strip() if m else "")[:120]
            except Exception:
                pass
    if current_images:
        system_prompt += ("\n\n【图片输入】用户本轮带了 "
                          f"{len(current_images)} 张图片/截图，已直接作为视觉输入发送给你。"
                          "先看图片内容再回答；需要读文字时以图片为准，OCR 文本只作辅助。"
                          "看不清、被裁掉或无法判断的地方要直接说明，不要凭猜测补全。")
        meta["vision_images"] = len(current_images)
    if att_rows:
        meta["attachments"] = [attachments.public(r) for r in att_rows]
    if skill:
        system_prompt = (system_prompt + "\n\n" + skill["prompt"]).strip()
        meta["skill"] = {"id": skill["id"], "name": skill["name"]}
    if use_kb:
        try:
            flags = await fetch_one(
                "SELECT kb_personal_enabled,kb_use_public,kb_use_personal "
                "FROM users WHERE id=?", (user["id"],)) or {}
            include_global = bool(cfg.get("kb_enabled")) and int(flags.get("kb_use_public") or 0) == 1
            include_personal = (int(flags.get("kb_personal_enabled") or 0) == 1
                                and int(flags.get("kb_use_personal") or 0) == 1)
            hits = await kb.search(body.message, int(cfg.get("kb_top_k") or 3),
                                   user_id=user["id"],
                                   include_global=include_global,
                                   include_personal=include_personal)
            if hits:
                ctx = "\n\n".join(f"【{h['title']}】{h['snippet']}" for h in hits)
                system_prompt += ("\n\n" + prompts.get(
                    "function.kb_hint", "以下是本机知识库中的相关资料，回答时优先参考：")
                    + "\n" + ctx[:3000])
                meta["kb"] = [h["title"] for h in hits]
        except Exception:
            pass
    if body.library_docs:
        try:
            picked = await library.selected_documents(user["id"], body.library_docs, cfg)
            if picked:
                max_chars = int(cfg.get("library_max_chars") or 12000)
                parts: list[str] = []
                used = 0
                for doc in picked:
                    text = str(doc.get("content") or "").strip()
                    if not text or used >= max_chars:
                        continue
                    remain = max_chars - used
                    piece = text[:remain]
                    parts.append(f"【资料库：{doc['title']}】\n{piece}")
                    used += len(piece)
                if parts:
                    system_prompt += ("\n\n" + prompts.get(
                        "function.library_hint",
                        "以下是用户从资料库中选择、可重复使用的资料，回答时优先参考；"
                        "资料之间相互独立：")
                        + "\n" + "\n\n".join(parts))
                    meta["library"] = {
                        "items": [{"id": d["id"], "title": d["title"], "scope": d["scope"]}
                                  for d in picked],
                        "chars": used,
                    }
                    await kb.mark_used([d["id"] for d in picked])
        except Exception:
            pass
    try:
        mem = await memory.context(user["id"], body.message)
        if mem.get("prompt"):
            system_prompt += "\n\n" + mem["prompt"]
        if mem.get("enabled"):
            meta["memory"] = {
                "enabled": True,
                "count": len(mem.get("items") or []),
                "ids": [x["id"] for x in (mem.get("items") or [])],
            }
    except Exception:
        pass
    fmt = docgen.resolve_format(body.output_format, body.message)
    if fmt:
        system_prompt = (system_prompt + "\n\n" + docgen.prompt_hint(fmt)).strip()
        meta["output_format"] = fmt
        meta["file_mode"] = True
    if body.web:
        if not websearch.is_enabled():
            plan = {"query": "", "intent": "general", "skip": "管理后台已关闭联网检索"}
        else:
            plan = websearch.plan_query(
                body.message,
                has_attachments=bool(att_rows),
                has_library=bool(body.library_docs),
            )
        if (plan.get("skip") and websearch.is_enabled() and link_unreadable and link_title):
            plan = {"query": websearch.query_from_doc_title(link_title),
                    "intent": "general", "skip": ""}
        if plan.get("skip"):
            skip = plan["skip"]
            meta["web"] = {"query": "", "sources": [], "error": "", "skipped": skip}
            if plan.get("intent") == "doc":
                text = prompts.get(
                    "function.web_skip_doc",
                    "本次联网已跳过（{reason}）。请只依据附件或资料库回答；"
                    "没有可读内容时直接说明，不要引用外部网页或编造来源。")
            else:
                text = prompts.get(
                    "function.web_skip_general",
                    "本次联网已跳过（{reason}）。按普通对话直接回答，"
                    "不要假装已经联网，也不要编造来源。")
            system_prompt += "\n\n" + text.replace("{reason}", skip)
        else:
            try:
                web = await websearch.research(
                    plan["query"], prefer_news=(plan.get("intent") == "news"))
            except Exception as e:
                web = {"query": plan["query"], "sources": [], "prompt": "",
                       "error": str(e)[:120] or "联网检索失败"}
            sources = [{"title": s["title"], "url": s["url"]}
                       for s in (web.get("sources") or [])]
            meta["web"] = {"query": web.get("query") or plan["query"], "sources": sources,
                           "error": web.get("error") or "", "skipped": "",
                           "intent": plan.get("intent") or "general"}
            if web.get("prompt"):
                system_prompt += "\n\n" + web["prompt"]
                if plan.get("intent") == "news":
                    system_prompt += "\n\n" + prompts.get(
                        "function.web_news_guard",
                        "【新闻事实约束】只能逐条列出本次检索资料“今日新闻条目”中的新闻，"
                        "清单有几条就输出几条，不合并、不拆分、不新增；"
                        "逐条保留原文的人物、机构和编号；不得用模型自身记忆补充资料外的年份、"
                        "人物、飞船编号或背景，也不要添加解释、评论或影响。")
            elif web.get("error"):
                system_prompt += ("\n\n本次联网检索没有成功（" + web["error"] +
                                  "）。请明确告诉用户未能获取实时资料，不要假装已经联网或编造来源。")
    if link_unreadable:
        if (meta.get("web") or {}).get("sources"):
            meta["web_fallback"] = True
            system_prompt += "\n\n" + prompts.get(
                "function.link_fallback",
                "【附件链接说明】原附件链接的正文无法读取（需要登录或只显示在线文档界面）。"
                "下面联网检索到的是按链接标题找到的公开同主题资料，只能作为参考，"
                "不能声称是原文档；回答正文直接给公开资料概要，开头说明由系统补充，不要重复。")
        else:
            system_prompt += "\n\n" + prompts.get(
                "function.link_unreadable",
                "【附件阅读状态】附件正文只是一个网页链接，链接页面没有返回正文"
                "（需要登录或只显示在线文档界面）。不要声称已经阅读，也不要编造总结或给通用建议；"
                "直接说明无法读取这个链接的正文，并请用户粘贴正文或导出 PDF/Word 后再上传。")
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    cid = body.conversation_id
    if cid:
        history = await fetch_all(
            "SELECT role,content,meta FROM messages WHERE conversation_id=? AND role IN ('user','assistant') "
            "ORDER BY id DESC LIMIT 20", (cid,))
        history.reverse()
        total = 0
        keep: list[dict] = []
        hist_images_left = max(0, attachments.VISION_MAX_IMAGES - len(current_images))
        hist_image_msgs = 0
        for h in reversed(history):
            content = str(h["content"] or "")
            hist_meta = parse_meta(h.get("meta"))
            ids = [a.get("id") for a in hist_meta.get("attachments", []) if isinstance(a, dict)]
            hist_images: list[dict] = []
            hist_ids: list[int] = []
            if body.vision and h["role"] == "user" and ids:
                rows = await attachments.load_many(user["id"], ids)
                if hist_images_left > 0 and hist_image_msgs < 2:
                    hist_images, hist_ids = await attachments.vision_payload(rows, hist_images_left)
                # 只跳过已成功转成视觉输入的图；预算外或坏图继续带 OCR。
                block = attachments.context_block(rows, skip_image_ids=set(hist_ids))
                if block:
                    content += "\n\n" + block
                if hist_images:
                    hist_images_left -= len(hist_images)
                    hist_image_msgs += 1
            elif h["role"] == "user" and ids:
                rows = await attachments.load_many(user["id"], ids)
                block = attachments.context_block(rows)
                if block:
                    content += "\n\n" + block
            total += len(content)
            if total > MAX_CONTEXT_CHARS:
                break
            keep.append({"role": h["role"], "content": _content_with_images(content, hist_images)})
        keep.reverse()
        msgs.extend(keep)
    if not body.regenerate:
        user_content = body.message
        if att_text:
            user_content = f"{user_content}\n\n{att_text}"
        msgs.append({"role": "user", "content": _content_with_images(user_content, current_images)})
    return msgs, (body.max_tokens or 2048), meta


@router.post("/chat/stream")
async def chat_stream(body: ChatBody, request: Request, user: dict = Depends(current_user)):
    if not (body.message or "").strip():
        raise HTTPException(400, "消息不能为空")
    if len(body.attachments) > 5:
        raise HTTPException(400, "一条消息最多带 5 个附件")
    ok, reason = await quota.check(user)
    if not ok:
        raise APIError(429, reason, QUOTA_EXCEEDED)
    cfg = load_config()
    body.model = (body.model or "").strip() or None
    agent: dict[str, Any] | None = None
    if body.agent_id:
        agent = await collab.agent_for_chat(int(body.agent_id), user)
        if not agent:
            raise HTTPException(404, "智能体不存在或无权使用")
        if agent.get("model"):
            body.model = str(agent["model"]).strip() or body.model
        if agent.get("system_prompt"):
            base = (body.system_prompt or cfg.get("system_prompt") or "").strip()
            body.system_prompt = (agent["system_prompt"].strip()
                                  + (("\n\n" + base) if base else ""))
    if body.model and not await access.can_use(user, body.model):
        raise HTTPException(403, "该模型未对当前用户开放")
    if not body.model:
        # 受限用户未指定模型时，自动落到名单里的第一个模型；管理员仍走默认路由
        first = await access.first_model(user)
        if first == "":
            raise HTTPException(403, "管理员尚未给该用户分配可用模型")
        if first:
            body.model = first
    fmt_pre = docgen.resolve_format(body.output_format, body.message)
    # 视觉模型在会话里时不要再按“任务复杂”切到纯文本大模型，否则图片会被丢掉。
    if body.vision:
        model_switch = None
    else:
        model_switch = await model_fit.maybe_escalate(body, cfg, fmt_pre or "")
        if model_switch and await access.can_use(user, model_switch["to"]):
            body.model = model_switch["to"]
        else:
            model_switch = None
    guard = await moderation.guard_input(
        body.message, user=user, model=body.model or "", conversation_id=body.conversation_id)
    if guard["blocked"]:
        raise HTTPException(
            400, "输入内容包含敏感词：" + "、".join(guard["matches"][:6]))
    body.message = guard["text"]
    decision = await routing.resolve(body, cfg)
    if decision.get("disabled"):
        raise HTTPException(503, decision.get("reason") or "本地部署已关闭")
    use_agent = bool(cfg.get("agent_mode_enabled", True)) and (
        body.agent_mode if body.agent_mode is not None else True)
    if decision.get("pool_id"):
        use_agent = False
    ctx = pipeline.new_ctx(user, body, cfg)
    await pipeline.run("before_render", ctx)
    now = time.time()

    if body.conversation_id:
        conv = await fetch_one("SELECT * FROM conversations WHERE id=? AND user_id=?",
                               (body.conversation_id, user["id"]))
        if not conv:
            raise HTTPException(404, "会话不存在")
        cid = conv["id"]
    else:
        cid = await execute(
            "INSERT INTO conversations(user_id,title,model,system_prompt,agent_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (user["id"], body.message.strip().replace("\n", " ")[:30] or "新对话",
             body.model or "", body.system_prompt, agent["id"] if agent else None, now, now))

    att_rows: list[dict[str, Any]] = []
    if body.regenerate:
        last = await fetch_one(
            "SELECT id,role FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1", (cid,))
        if last and last["role"] == "assistant":
            await execute("DELETE FROM messages WHERE id=?", (last["id"],))
    else:
        att_rows = await attachments.load_many(user["id"], body.attachments)
        if body.attachments and not att_rows:
            raise HTTPException(400, "附件不存在或已删除")
        skill = skills.get(body.skill)
        if body.skill and not skill:
            raise HTTPException(400, "技能不存在")
        user_meta = {}
        if att_rows:
            user_meta["attachments"] = [attachments.public(r) for r in att_rows]
        if skill:
            user_meta["skill"] = {"id": skill["id"], "name": skill["name"]}
        if body.web:
            user_meta["web"] = True
        if agent:
            user_meta["agent"] = {"id": agent["id"], "name": agent["name"], "avatar": agent["avatar"]}
        fmt = docgen.resolve_format(body.output_format, body.message)
        if fmt:
            user_meta["output_format"] = fmt
        await execute(
            "INSERT INTO messages(conversation_id,role,content,tokens,meta,created_at) VALUES(?,?,?,?,?,?)",
            (cid, "user", body.message, _tokens(body.message),
             json.dumps(user_meta, ensure_ascii=False) if user_meta else None, now))
    await execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, cid))

    msgs, max_tokens, extra = await _build_context(
        user, body, cfg, att_rows if not body.regenerate else None,
        skill if not body.regenerate else skills.get(body.skill))
    agent_ctx: dict[str, Any] = {
        "user": user, "cfg": cfg, "body": body,
        "attachments": att_rows, "extra": extra,
    }
    agent_tools: list[dict[str, Any]] = []
    if use_agent:
        agent_rules = prompts.get(
            "function.agent_rules",
            "你现在处于只读工具模式。必要时可以调用系统提供的检索工具；工具结果不足时明确说明，不要编造。")
        if msgs and msgs[0].get("role") == "system":
            msgs[0]["content"] = (str(msgs[0].get("content") or "") + "\n\n" + agent_rules).strip()
        else:
            msgs.insert(0, {"role": "system", "content": agent_rules})
        agent_tools = agent.build_tools(agent_ctx)
        if not agent_tools:
            use_agent = False
        else:
            extra["agent_mode"] = True
            extra["agent_tools"] = [t["function"]["name"] for t in agent_tools]
    ctx["decision"] = decision
    if model_switch:
        extra["model_switch"] = model_switch
    model_name = decision["model"]
    params = {
        "temperature": body.temperature if body.temperature is not None else 0.7,
        "max_tokens": max_tokens,
    }
    prompt_text = "\n".join(_content_text(m) for m in msgs)[:12000]
    ctx["prompt"] = prompt_text
    ctx["prompt_hash"] = pipeline.prompt_hash(model_name, prompt_text, params)
    await pipeline.run("before_call", ctx)
    # 钩子可以改写最终调用目标（缓存命中、灰度换模型等）
    base = str(ctx.get("base") or decision["base"]).rstrip("/")
    key = str(ctx.get("key") or decision["key"])
    model_name = str(ctx.get("model") or model_name)
    if use_agent and not base:
        use_agent = False
        agent_tools = []
    is_pool = bool(decision.get("pool_id")) and not ctx.get("base")
    pool_candidates: list[dict] = []
    pool_info: dict | None = None
    if is_pool:
        pool_info, pool_candidates = await cluster.candidates(str(decision.get("pool") or ""))
        if not pool_candidates:
            raise HTTPException(503, "模型池还没有可用节点")

    payload = {
        "model": model_name,
        "messages": msgs,
        "stream": True,
        **params,
    }
    upstream_started = time.monotonic()
    retrieve_ms = int((upstream_started - ctx["t0"]) * 1000)
    mod_cfg = moderation.settings()
    mod_words = await moderation.active_words() if mod_cfg["enabled"] else []
    output_filter = moderation.StreamFilter(
        action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
        words=mod_words, replacement=mod_cfg["replace_with"], min_chars=mod_cfg["min_chars"])
    reason_filter = moderation.StreamFilter(
        action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
        words=mod_words, replacement=mod_cfg["replace_with"], min_chars=mod_cfg["min_chars"])

    async def event_stream() -> AsyncIterator[bytes]:
        content_buf: list[str] = []
        reason_buf: list[str] = []
        err = ""
        msg_id = 0
        ttft_ms = 0
        usage: dict = {}
        first_token = True
        status = "ok"
        mod_blocked = False
        admission_token = None
        agent_result: dict[str, Any] | None = None
        agent_trace: list[dict[str, Any]] = []

        async def upstream_lines():
            if use_agent:
                return
            if not is_pool:
                if not base:
                    raise RuntimeError("未配置上游模型服务地址")
                timeout = httpx.Timeout(connect=10, read=None, write=10, pool=10)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    headers = {"Content-Type": "application/json"}
                    if key:
                        headers["Authorization"] = f"Bearer {key}"
                    async with client.stream(
                            "POST", f"{base}/chat/completions", json=payload,
                            headers=headers) as r:
                        if r.status_code != 200:
                            detail = (await r.aread()).decode("utf-8", "replace")[:300]
                            raise RuntimeError(f"上游返回 {r.status_code}: {detail}")
                        async for line in r.aiter_lines():
                            yield line
                return

            attempts = pool_candidates[:max(
                1, min(len(pool_candidates), 1 + int((pool_info or {}).get("retries") or 0)))]
            errors: list[str] = []
            for candidate in attempts:
                if await request.is_disconnected():
                    raise asyncio.CancelledError()
                cluster.begin(candidate["node_id"])
                sent = False
                try:
                    upstream = {**payload, "model": candidate["model"]}
                    timeout = httpx.Timeout(connect=10, read=None, write=10, pool=10)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        async with client.stream(
                                "POST", f"{candidate['base']}/chat/completions", json=upstream,
                                headers=(_node_headers(candidate))) as r:
                            if r.status_code != 200:
                                detail = (await r.aread()).decode("utf-8", "replace")[:300]
                                if r.status_code >= 500:
                                    await cluster.record_failure(candidate["node_id"], detail)
                                if r.status_code == 429 or r.status_code >= 500:
                                    errors.append(f"{candidate['node_name']} HTTP {r.status_code}")
                                    continue
                                raise RuntimeError(
                                    f"上游 {candidate['node_name']} 返回 {r.status_code}: {detail[:200]}")
                            async for line in r.aiter_lines():
                                sent = True
                                yield line
                    await cluster.record_success(candidate["node_id"], 0)
                    decision["node"] = candidate["node_name"]
                    decision["remote_model"] = candidate["model"]
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if sent:
                        await cluster.record_failure(candidate["node_id"], str(exc))
                        raise RuntimeError(f"上游 {candidate['node_name']} 中断：{str(exc)[:160]}")
                    await cluster.record_failure(candidate["node_id"], str(exc))
                    errors.append(f"{candidate['node_name']}：{str(exc)[:120]}")
                    continue
                finally:
                    cluster.end(candidate["node_id"])
            raise RuntimeError("所有节点都失败" + ("：" + "；".join(errors[-3:]) if errors else ""))

        # 全局并发上限 + 单账号限流：拿不到名额直接在流里返回错误事件，不占用模型。
        try:
            admission_token = await admission.get_admission().enter(str(user["id"]))
        except admission.AdmissionRejected as e:
            yield f"data: {json.dumps({'type':'error','message':e.message,'code':'admission_limited'}, ensure_ascii=False)}\n\n".encode()
            return

        # 本地 llama.cpp 是全局单模型：这里登记占用，切换模型前会检查。
        usage_model = ""
        if decision.get("provider") == "local" and not is_pool:
            usage_model = str(getattr(llama.server, "model_key", "") or model_name)
            model_usage.begin(usage_model, str(user.get("username") or ""))

        try:
            yield f"data: {json.dumps({'type':'meta','conversation_id':cid,'kb':extra.get('kb',[]),'web':extra.get('web') or None,'memory':extra.get('memory') or None,'model':model_name,'provider':decision['provider'],'trace_id':ctx['trace_id'],'route':decision['strategy'],'file_mode':bool(extra.get('file_mode')),'output_format':extra.get('output_format') or None,'model_switch':extra.get('model_switch') or None,'agent_mode':bool(use_agent),'agent_tools':extra.get('agent_tools') or []}, ensure_ascii=False)}\n\n".encode()
            if extra.get("web_fallback"):
                note = "原文档链接需要登录，无法直接读取；以下是按文档标题检索到的公开资料概要，并非原文档内容。\n\n"
                content_buf.append(note)
                yield f"data: {json.dumps({'type':'delta','text':note}, ensure_ascii=False)}\n\n".encode()
            if use_agent:
                agent_result = await agent.run_agent(
                    messages=msgs, tools=agent_tools, base=base, key=key,
                    model=model_name, params=params, ctx=agent_ctx)
                agent_trace = agent_result.get("trace") or []
                extra["agent_trace"] = agent_trace
                usage = agent_result.get("usage") or {}
                for action in agent_trace:
                    yield f"data: {json.dumps({'type':'agent_action','action':action}, ensure_ascii=False)}\n\n".encode()
                agent_reason = str(agent_result.get("reasoning") or "")
                if agent_reason:
                    safe_rc = reason_filter.feed(agent_reason)
                    if reason_filter.blocked:
                        mod_blocked = True
                        err = "回复触发内容安全策略，已拦截"
                        status = "moderation_blocked"
                        yield f"data: {json.dumps({'type':'error','message':err,'code':'content_blocked'}, ensure_ascii=False)}\n\n".encode()
                    else:
                        if first_token:
                            ttft_ms = int((time.monotonic() - upstream_started) * 1000)
                            first_token = False
                        if safe_rc:
                            reason_buf.append(safe_rc)
                            yield f"data: {json.dumps({'type':'reasoning','text':safe_rc}, ensure_ascii=False)}\n\n".encode()
                agent_content = str(agent_result.get("content") or "")
                if agent_content and not mod_blocked:
                    safe_c = output_filter.feed(agent_content)
                    if output_filter.blocked:
                        mod_blocked = True
                        err = "回复触发内容安全策略，已拦截"
                        status = "moderation_blocked"
                        yield f"data: {json.dumps({'type':'error','message':err,'code':'content_blocked'}, ensure_ascii=False)}\n\n".encode()
                    else:
                        if first_token:
                            ttft_ms = int((time.monotonic() - upstream_started) * 1000)
                            first_token = False
                        if safe_c:
                            content_buf.append(safe_c)
                            yield f"data: {json.dumps({'type':'delta','text':safe_c}, ensure_ascii=False)}\n\n".encode()
            async for line in upstream_lines():
                if await request.is_disconnected():
                    raise asyncio.CancelledError()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                choice = (obj.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                rc = delta.get("reasoning_content") or ""
                if rc:
                    if first_token:
                        ttft_ms = int((time.monotonic() - upstream_started) * 1000)
                        first_token = False
                    safe_rc = reason_filter.feed(rc)
                    if reason_filter.blocked:
                        mod_blocked = True
                        err = "回复触发内容安全策略，已拦截"
                        status = "moderation_blocked"
                        yield f"data: {json.dumps({'type':'error','message':err,'code':'content_blocked'}, ensure_ascii=False)}\n\n".encode()
                        break
                    if safe_rc:
                        reason_buf.append(safe_rc)
                        yield f"data: {json.dumps({'type':'reasoning','text':safe_rc}, ensure_ascii=False)}\n\n".encode()
                c = delta.get("content") or ""
                if c:
                    if first_token:
                        ttft_ms = int((time.monotonic() - upstream_started) * 1000)
                        first_token = False
                    safe_c = output_filter.feed(c)
                    if output_filter.blocked:
                        mod_blocked = True
                        err = "回复触发内容安全策略，已拦截"
                        status = "moderation_blocked"
                        yield f"data: {json.dumps({'type':'error','message':err,'code':'content_blocked'}, ensure_ascii=False)}\n\n".encode()
                        break
                    if safe_c:
                        content_buf.append(safe_c)
                        yield f"data: {json.dumps({'type':'delta','text':safe_c}, ensure_ascii=False)}\n\n".encode()
            if not mod_blocked:
                # 上游正常结束后，把过滤器里为避免跨块漏检而保留的尾巴吐出来。
                safe_tail = output_filter.flush()
                if safe_tail:
                    content_buf.append(safe_tail)
                    yield f"data: {json.dumps({'type':'delta','text':safe_tail}, ensure_ascii=False)}\n\n".encode()
                safe_reason = reason_filter.flush()
                if safe_reason:
                    reason_buf.append(safe_reason)
                    yield f"data: {json.dumps({'type':'reasoning','text':safe_reason}, ensure_ascii=False)}\n\n".encode()
        except asyncio.CancelledError:
            err = "stopped"
            status = "stopped"
        except Exception as e:
            err = str(e)[:500]
            status = "error"
            yield f"data: {json.dumps({'type':'error','message':err}, ensure_ascii=False)}\n\n".encode()
        finally:
            if admission_token:
                try:
                    await admission_token.release()
                except Exception:
                    pass
            if usage_model:
                model_usage.end(usage_model, str(user.get("username") or ""))
            if not body.regenerate:
                try:
                    await memory.maybe_capture(user["id"], body.message, cid)
                except Exception:
                    pass
            full = "".join(content_buf)
            reason = "".join(reason_buf)
            display = full
            files: list[dict[str, Any]] = []
            file_error = ""
            file_fmt = extra.get("output_format") or ""
            if file_fmt and status == "ok" and not mod_blocked and len(full.strip()) >= 40:
                try:
                    made = await docgen.build(user["id"], cid, full, file_fmt)
                    files.append(made)
                    display = docgen.summary(made)
                except Exception as exc:
                    file_error = f"文件生成失败：{str(exc)[:160]}"
                    log.exception("生成 %s 失败", file_fmt)

            hit_words = list(dict.fromkeys(output_filter.matched + reason_filter.matched))
            if hit_words:
                await moderation.record_hit(
                    user=user, direction="output",
                    action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
                    words=hit_words, text=full or reason, model=model_name, conversation_id=cid)
            if full or reason:
                meta = {"model": model_name, "stopped": status == "stopped",
                        "kb": extra.get("kb", []), "trace_id": ctx["trace_id"],
                        "provider": decision["provider"], "web": extra.get("web") or None,
                        "agent": ({"id": agent["id"], "name": agent["name"],
                                   "avatar": agent["avatar"]} if agent else None),
                        "memory": extra.get("memory") or None,
                        "output_format": file_fmt or None, "files": files,
                        "agent_mode": bool(use_agent),
                        "agent_trace": agent_trace,
                        "file_error": file_error or None,
                        "model_switch": extra.get("model_switch") or None}
                msg_id = await execute(
                    "INSERT INTO messages(conversation_id,role,content,reasoning,tokens,meta,created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (cid, "assistant", display, reason, _tokens(full),
                     json.dumps(meta, ensure_ascii=False), time.time()))
                for f in files:
                    try:
                        await execute("UPDATE generated_files SET message_id=? WHERE id=?",
                                     (msg_id, f["id"]))
                    except Exception:
                        pass
                await execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), cid))
            total_ms = int((time.monotonic() - upstream_started) * 1000)
            ptok = int(usage.get("prompt_tokens") or 0)
            ctok = int(usage.get("completion_tokens") or 0)
            estimated = False
            if not ptok:
                ptok = pipeline.estimate_tokens(prompt_text)
                estimated = True
            if not ctok:
                ctok = pipeline.estimate_tokens(full + reason)
                estimated = True
            price_in = float(decision.get("price_in") or 0)
            price_out = float(decision.get("price_out") or 0)
            cost = round((ptok * price_in + ctok * price_out) / 1_000_000, 6)
            await pipeline.run("after_call", ctx)
            event = {
                "request": {
                    "trace_id": ctx["trace_id"], "user_id": user["id"], "conversation_id": cid,
                    "route_id": decision.get("route_id"), "provider": decision["provider"],
                    "provider_id": decision.get("provider_id"), "model": model_name, "stream": True,
                    "status": status, "error": err or None,
                    "prompt_hash": ctx["prompt_hash"], "prompt_rendered": prompt_text,
                    "params_json": json.dumps(params, ensure_ascii=False),
                    "decision_json": json.dumps(
                        {k: v for k, v in decision.items() if k != "key"}, ensure_ascii=False),
                    "prompt_tokens": ptok, "completion_tokens": ctok,
                    "total_tokens": ptok + ctok, "tokens_estimated": estimated,
                    "cost": cost, "price_in": price_in, "price_out": price_out,
                    "ttft_ms": ttft_ms, "total_ms": total_ms, "queue_ms": retrieve_ms,
                    "retries": 0, "cache_hit": bool(ctx.get("cache_hit")),
                    "cache_id": ctx.get("cache_id"), "experiment_id": ctx.get("experiment_id"),
                    "bucket": int(ctx.get("bucket") or 0), "shadow_of": ctx.get("shadow_of"),
                    "created_at": time.time(),
                },
                "spans": [
                    {"kind": "retrieval", "name": "kb.search", "start_ms": 0,
                     "dur_ms": retrieve_ms,
                     "attrs": {"kb": extra.get("kb", []), "top_k": cfg.get("kb_top_k")}},
                    {"kind": "llm", "name": model_name, "start_ms": retrieve_ms,
                     "dur_ms": total_ms,
                     "attrs": {"provider": decision["provider"], "ttft_ms": ttft_ms,
                               "tokens": ptok + ctok, "status": status}},
                ],
            }
            await logbus.put(event)
            yield f"data: {json.dumps({'type':'done','message_id':msg_id,'stopped':status=='stopped','chars':len(full),'trace_id':ctx['trace_id'],'ttft_ms':ttft_ms,'tokens':ptok+ctok,'files':files,'file_error':file_error or None,'summary':display if files else ''}, ensure_ascii=False)}\n\n".encode()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chat/tts")
async def chat_tts(body: TTSBody, user: dict = Depends(current_user)):
    try:
        return await tts.synthesize(body.text, body.voice)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/tts/audio/{name}")
async def get_audio(name: str, request: Request, token: str | None = None):
    """音频地址可带 ?token=，供 <audio> 标签在前后端分离场景下播放。"""
    user = await user_from_any_token(token) if token else None
    if not user:
        try:
            user = await current_user(request)
        except HTTPException:
            user = None
    if not user:
        raise HTTPException(401, "未登录或令牌已失效")
    p = tts.audio_path(name)
    if not p:
        raise HTTPException(404, "音频不存在")
    return FileResponse(p, media_type="audio/mpeg")


@router.get("/tts/voices")
async def voices():
    return {"items": [{"group": g, "value": v, "label": n} for g, v, n in tts.VOICES]}
