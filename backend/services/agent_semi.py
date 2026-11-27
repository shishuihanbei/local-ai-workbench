"""半自主检索编排：固定顺序、逐级降级、每步留痕。

和 `agent.py` 的区别：这里不依赖模型发 `tool_calls`，顺序由代码写死，
因此在不支持 Function Calling 的本地模型上也能用，CPU 上轮次固定、耗时可预期。

顺序：附件（已内联）→ 知识库 → 资料库 → 联网。
每一级都能"命中就够、够了就停"：本地资料已经能回答时不再联网。
模型只负责最终措辞，检索词沿用现有的规则改写。
"""
from __future__ import annotations

import re
import time
from typing import Any

from ..db import fetch_one
from ..config import load_config
from . import kb, library, prompts, websearch

TIME_SENSITIVE = re.compile(
    r"(今天|今日|昨天|最新|本周|这周|上周|本月|刚刚|实时|现在|当前|最近|新闻|股价|汇率|天气|比分|发布|上线)")

# 半自主最多给资料库自动挑几篇、正文预算多少字符
AUTO_LIBRARY_DOCS = 2
AUTO_LIBRARY_CHARS = 4000
MAX_BLOCK_CHARS = 3200


def _now() -> float:
    return time.monotonic()


def _step(tool: str, status: str, *, query: str = "", count: int = 0,
          dur_ms: int = 0, summary: str = "", error: str = "",
          sources: list[dict[str, Any]] | None = None, turn: int = 1) -> dict[str, Any]:
    return {
        "tool": tool,
        "turn": turn,
        "arguments": {"query": query} if query else {},
        "status": status,          # ok / skip / error
        "count": count,
        "summary": summary[:220],
        "sources": (sources or [])[:5],
        "error": error[:300],
        "dur_ms": dur_ms,
    }


def _label(action: dict[str, Any]) -> str:
    return {"search_knowledge_base": "知识库", "search_library": "资料库",
            "search_web": "联网检索", "read_attachments": "附件"}.get(action["tool"], action["tool"])


async def _kb_flags(user_id: int, cfg: dict[str, Any]) -> tuple[bool, bool]:
    flags = await fetch_one(
        "SELECT kb_personal_enabled,kb_use_public,kb_use_personal FROM users WHERE id=?",
        (user_id,)) or {}
    include_global = bool(cfg.get("kb_enabled")) and int(flags.get("kb_use_public") or 0) == 1
    include_personal = (int(flags.get("kb_personal_enabled") or 0) == 1
                        and int(flags.get("kb_use_personal") or 0) == 1)
    return include_global, include_personal


async def _run_kb(message: str, user: dict, cfg: dict[str, Any], body: Any,
                  turn: int) -> tuple[dict[str, Any], str, list[str]]:
    use_kb = cfg.get("kb_enabled", False) if getattr(body, "use_kb", None) is None else body.use_kb
    if not use_kb:
        return _step("search_knowledge_base", "skip", turn=turn,
                     summary="知识库未开启，跳过"), "", []
    started = _now()
    try:
        include_global, include_personal = await _kb_flags(user["id"], cfg)
        hits = await kb.search(message, int(cfg.get("kb_top_k") or 3), user_id=user["id"],
                               include_global=include_global, include_personal=include_personal)
    except Exception as exc:
        return (_step("search_knowledge_base", "error", query=message, turn=turn,
                      dur_ms=int((_now() - started) * 1000), error=str(exc),
                      summary=f"知识库检索失败：{str(exc)[:80]}"), "", [])
    dur = int((_now() - started) * 1000)
    if not hits:
        return (_step("search_knowledge_base", "skip", query=message, turn=turn, dur_ms=dur,
                      summary="知识库没有匹配内容"), "", [])
    ctx = "\n\n".join(f"【{h['title']}】{h['snippet']}" for h in hits)
    block = (prompts.get("function.kb_hint", "以下是本机知识库中的相关资料，回答时优先参考：")
             + "\n" + ctx[:MAX_BLOCK_CHARS])
    titles = [h["title"] for h in hits]
    return (_step("search_knowledge_base", "ok", query=message, turn=turn, dur_ms=dur,
                  count=len(hits), summary="命中 " + "、".join(titles[:3]),
                  sources=[{"title": t, "url": ""} for t in titles]), block, titles)


async def _run_library(message: str, user: dict, cfg: dict[str, Any], body: Any,
                       turn: int) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    selected = list(getattr(body, "library_docs", None) or [])
    if selected:
        return (_step("search_library", "skip", turn=turn, count=len(selected),
                      summary=f"用户已手动选择 {len(selected)} 篇资料，直接使用"), "", None)
    state = await library.user_state(user["id"], cfg)
    if not (state["global_enabled"] and state["use_global"]
            or state["personal_enabled"] and state["use_personal"]):
        return _step("search_library", "skip", turn=turn,
                     summary="资料库未开启，跳过"), "", None
    started = _now()
    try:
        hits = await kb.search(message, AUTO_LIBRARY_DOCS, user_id=user["id"],
                               include_global=bool(state["global_enabled"] and state["use_global"]),
                               include_personal=bool(state["personal_enabled"] and state["use_personal"]),
                               module="library")
        rows = await kb.full_texts([int(h["doc_id"]) for h in hits]) if hits else []
    except Exception as exc:
        return (_step("search_library", "error", query=message, turn=turn,
                      dur_ms=int((_now() - started) * 1000), error=str(exc),
                      summary=f"资料库检索失败：{str(exc)[:80]}"), "", None)
    dur = int((_now() - started) * 1000)
    if not rows:
        return (_step("search_library", "skip", query=message, turn=turn, dur_ms=dur,
                      summary="资料库没有匹配内容"), "", None)
    parts: list[str] = []
    used = 0
    picked: list[dict[str, Any]] = []
    for row in rows[:AUTO_LIBRARY_DOCS]:
        text = str(row.get("content") or "").strip()
        if not text or used >= AUTO_LIBRARY_CHARS:
            continue
        remain = AUTO_LIBRARY_CHARS - used
        piece = text[:remain]
        parts.append(f"【资料库：{row.get('title') or '未命名'}】\n{piece}")
        used += len(piece)
        picked.append({"id": row.get("id"), "title": row.get("title"), "scope": row.get("scope")})
    if not parts:
        return (_step("search_library", "skip", query=message, turn=turn, dur_ms=dur,
                      summary="资料库命中但正文为空"), "", None)
    block = (prompts.get("function.library_hint",
                         "以下是用户资料库中与问题相关的资料，回答时优先参考：")
             + "\n" + "\n\n".join(parts))
    meta = {"items": picked, "chars": used}
    return (_step("search_library", "ok", query=message, turn=turn, dur_ms=dur,
                  count=len(picked), summary="命中 " + "、".join(str(p["title"] or "") for p in picked),
                  sources=[{"title": str(p["title"] or ""), "url": ""} for p in picked]), block, meta)


async def _run_web(message: str, cfg: dict[str, Any], body: Any, *, local_hits: int,
                   has_attachments: bool, has_library: bool,
                   turn: int) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    if not getattr(body, "web", False):
        return _step("search_web", "skip", turn=turn, summary="本轮未开启联网"), "", None
    if not websearch.is_enabled():
        return _step("search_web", "skip", turn=turn,
                     summary="管理后台已关闭联网检索"), "", {
            "query": "", "sources": [], "error": "", "skipped": "管理后台已关闭联网检索"}
    plan = websearch.plan_query(message, has_attachments=has_attachments, has_library=has_library)
    if local_hits >= 2 and not TIME_SENSITIVE.search(message) and plan.get("intent") != "news":
        reason = f"本地资料已命中 {local_hits} 条，跳过联网"
        return _step("search_web", "skip", query=plan.get("query") or message, turn=turn,
                     summary=reason), "", {"query": plan.get("query") or "", "sources": [],
                                           "error": "", "skipped": reason}
    if plan.get("skip"):
        return _step("search_web", "skip", query=plan.get("query") or message, turn=turn,
                     summary=str(plan["skip"])), "", {
            "query": "", "sources": [], "error": "", "skipped": str(plan["skip"])}
    started = _now()
    try:
        web = await websearch.research(plan["query"],
                                       prefer_news=(plan.get("intent") == "news"))
    except Exception as exc:
        dur = int((_now() - started) * 1000)
        note = prompts.get(
            "function.web_error",
            "【联网失败】本次联网检索出错，回答时明确说明没能获取实时资料，不要编造来源。")
        return (_step("search_web", "error", query=plan["query"], turn=turn, dur_ms=dur,
                      error=str(exc), summary=f"联网检索失败：{str(exc)[:80]}"), note, {
            "query": plan["query"], "sources": [], "error": str(exc)[:120] or "联网检索失败",
            "skipped": "", "intent": plan.get("intent") or "general"})
    dur = int((_now() - started) * 1000)
    sources = [{"title": s["title"], "url": s["url"]} for s in (web.get("sources") or [])]
    meta = {"query": web.get("query") or plan["query"], "sources": sources,
            "error": web.get("error") or "", "skipped": "",
            "intent": plan.get("intent") or "general"}
    if not sources:
        note = prompts.get(
            "function.web_empty",
            "【联网无结果】本次没有检索到可用来源，回答时说明没有找到实时资料，不要编造。")
        return (_step("search_web", "skip", query=plan["query"], turn=turn, dur_ms=dur,
                      error=web.get("error") or "",
                      summary=web.get("error") or "没有检索到可用来源"), note, meta)
    block = str(web.get("prompt") or "")
    if plan.get("intent") == "news":
        block += "\n\n" + prompts.get(
            "function.web_news_hint",
            "以上是新闻类检索结果，回答时注明日期与来源，不要编造未出现的条目。")
    return (_step("search_web", "ok", query=web.get("query") or plan["query"], turn=turn,
                  dur_ms=dur, count=len(sources), summary="、".join(s["title"] for s in sources[:3]),
                  sources=sources), block, meta)


async def run(message: str, *, user: dict, cfg: dict[str, Any], body: Any,
              attachments: list[dict[str, Any]] | None = None,
              ) -> dict[str, Any]:
    """按固定顺序跑一遍检索，返回材料块、逐步轨迹和可回填的 meta。"""
    cfg = cfg or load_config()
    attachments = attachments or []
    steps: list[dict[str, Any]] = []
    blocks: list[str] = []
    meta: dict[str, Any] = {"kb": [], "library": None, "web": None}

    turn = 1
    steps.append(_step("read_attachments", "ok" if attachments else "skip", turn=turn,
                       count=len(attachments),
                       summary=(f"本轮 {len(attachments)} 个附件正文已直接内联，无需再读"
                                if attachments else "本轮没有附件")))
    turn += 1

    kb_step, kb_block, kb_titles = await _run_kb(message, user, cfg, body, turn)
    steps.append(kb_step)
    if kb_block:
        blocks.append(kb_block)
    meta["kb"] = kb_titles
    web_info: dict[str, Any] | None = None
    lib_step, lib_block, lib_meta = await _run_library(message, user, cfg, body, turn + 1)
    steps.append(lib_step)
    if lib_block:
        blocks.append(lib_block)
    meta["library"] = lib_meta

    local_hits = int(kb_step.get("count") or 0) + int(lib_step.get("count") or 0)
    web_step, web_block, web_info = await _run_web(
        message, cfg, body, local_hits=local_hits,
        has_attachments=bool(attachments),
        has_library=bool(getattr(body, "library_docs", None) or lib_meta),
        turn=turn + 2)
    steps.append(web_step)
    if web_block:
        blocks.append(web_block)
    meta["web"] = web_info

    ok_steps = [s for s in steps if s["status"] == "ok"]
    summary = "；".join(f"{_label(s)} {'成功' if s['status'] == 'ok' else s['status']}"
                        f"{('(' + str(s['count']) + ' 条)') if s.get('count') else ''}"
                        for s in steps)
    prompt = ""
    if blocks:
        prompt = (prompts.get("function.semi_intro",
                              "以下是系统按固定顺序检索到的材料（知识库 → 资料库 → 联网），"
                              "回答时优先使用；没有的内容不要编造。")
                  + "\n\n" + "\n\n".join(blocks))

    return {
        "steps": steps,
        "trace": steps,
        "prompt": prompt,
        "meta": meta,
        "summary": summary,
        "ok_count": len(ok_steps),
        # 这两步由半自主接管，chat 的默认检索不要再重复跑
        "handles_kb": True,
        "handles_web": True,
    }
