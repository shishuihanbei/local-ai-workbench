"""本地只读工具 Agent 运行时。

第一版只开放安全的只读工具：知识库检索、资料库检索、联网检索、读取当前附件。
不开放本地文件写入、代码执行、浏览器或软件操作。模型返回工具调用后，后端执行工具、
把结果回灌给模型，再由模型决定是否继续调用，直到给出最终回答或达到最大工具轮次。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Awaitable, Callable

import httpx

from ..db import fetch_one
from . import attachments, kb, library, websearch

log = logging.getLogger(__name__)

MAX_TOOL_RESULT_CHARS = 3000
MAX_TOOL_QUERY_CHARS = 180

ToolCaller = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _clean_text(value: Any, limit: int = MAX_TOOL_QUERY_CHARS) -> str:
    return str(value or "").strip()[:limit]


def _args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _arg_int(args: dict[str, Any], name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…（结果已截断）"


def _hit_lines(hits: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for i, hit in enumerate(hits, 1):
        title = str(hit.get("title") or "未命名").strip()
        snippet = str(hit.get("snippet") or hit.get("content") or "").strip()
        scope = str(hit.get("scope") or "")
        folder = str(hit.get("folder") or "")
        meta = " · ".join(x for x in (scope, folder) if x)
        lines.append(f"[{i}] {title}" + (f"（{meta}）" if meta else "") + f"\n{snippet[:400]}")
    return lines


async def _search_kb(ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    user = ctx["user"]
    cfg = ctx["cfg"]
    query = _clean_text(args.get("query"))
    if not query:
        return {"ok": False, "error": "检索词不能为空"}
    top_k = _arg_int(args, "top_k", int(cfg.get("kb_top_k") or 3), 1, 5)
    flags = await fetch_one(
        "SELECT kb_personal_enabled,kb_use_public,kb_use_personal "
        "FROM users WHERE id=?", (user["id"],)) or {}
    include_global = bool(cfg.get("kb_enabled")) and int(flags.get("kb_use_public") or 0) == 1
    include_personal = (int(flags.get("kb_personal_enabled") or 0) == 1
                        and int(flags.get("kb_use_personal") or 0) == 1)
    hits = await kb.search(query, top_k, user_id=user["id"],
                           include_global=include_global, include_personal=include_personal)
    if not hits:
        return {"ok": True, "count": 0, "text": "本机知识库没有检索到相关资料。"}
    return {"ok": True, "count": len(hits), "sources": hits,
            "text": "本机知识库检索结果：\n" + "\n\n".join(_hit_lines(hits))}


async def _search_library(ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    user = ctx["user"]
    cfg = ctx["cfg"]
    query = _clean_text(args.get("query"))
    if not query:
        return {"ok": False, "error": "检索词不能为空"}
    top_k = _arg_int(args, "top_k", 3, 1, 5)
    state = await library.user_state(user["id"], cfg)
    include_global = bool(state["global_enabled"] and state["use_global"])
    include_personal = bool(state["personal_enabled"] and state["use_personal"])
    hits = await kb.search(query, top_k, user_id=user["id"],
                           include_global=include_global, include_personal=include_personal,
                           module="library")
    if not hits:
        return {"ok": True, "count": 0, "text": "资料库没有检索到相关资料。"}
    return {"ok": True, "count": len(hits), "sources": hits,
            "text": "资料库检索结果：\n" + "\n\n".join(_hit_lines(hits))}


async def _search_web(ctx: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    body = ctx["body"]
    if not websearch.is_enabled():
        return {"ok": False, "error": "管理员已关闭联网检索"}
    if not getattr(body, "web", False):
        return {"ok": False, "error": "本轮用户没有开启联网，不能主动调用网页检索"}
    query = _clean_text(args.get("query"))
    if not query:
        return {"ok": False, "error": "检索词不能为空"}
    prefer_news = bool(args.get("prefer_news") or False)
    web = await websearch.research(query, prefer_news=prefer_news)
    sources = [{"title": s.get("title") or "", "url": s.get("url") or "",
                "snippet": s.get("snippet") or s.get("text") or ""}
               for s in (web.get("sources") or [])]
    if web.get("error"):
        return {"ok": False, "error": str(web["error"])[:300], "sources": sources}
    if not sources:
        return {"ok": True, "count": 0, "text": "联网没有检索到相关公开资料。"}
    lines = [f"联网检索词：{web.get('query') or query}"]
    for i, src in enumerate(sources, 1):
        lines.append(f"[{i}] {src['title']}\n网址：{src['url']}\n摘要：{src['snippet'][:300]}")
    return {"ok": True, "count": len(sources), "sources": sources,
            "text": "联网检索结果：\n" + "\n\n".join(lines)}


async def _read_attachments(ctx: dict[str, Any], _args: dict[str, Any]) -> dict[str, Any]:
    rows = ctx.get("attachments") or []
    if not rows:
        return {"ok": True, "count": 0, "text": "本轮没有上传附件。"}
    block = attachments.context_block(rows)
    images = [r for r in rows if r.get("kind") == "image"]
    note = ""
    if images:
        note = f"\n（另有 {len(images)} 张图片已作为视觉输入发送给模型；这里只返回 OCR/文件名信息。）"
    return {"ok": True, "count": len(rows), "text": "当前附件内容：\n" + block + note}


def build_tools(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """按当前用户权限和开关生成可调用工具清单。"""
    cfg = ctx["cfg"]
    body = ctx["body"]
    tools: list[dict[str, Any]] = []
    if cfg.get("kb_enabled") and cfg.get("agent_tool_kb", True):
        tools.append({
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": "检索本机/个人知识库中与问题相关的条目；只在本地知识可能回答问题时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "简短、具体的检索词或问题"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 5, "description": "返回条数，默认 3"},
                    },
                    "required": ["query"],
                },
            },
        })
    if cfg.get("library_enabled") and cfg.get("agent_tool_library", True):
        tools.append({
            "type": "function",
            "function": {
                "name": "search_library",
                "description": "检索用户长期资料库中的文档；优先于模型自身记忆。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "简短、具体的检索词或问题"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 5, "description": "返回条数，默认 3"},
                    },
                    "required": ["query"],
                },
            },
        })
    if websearch.is_enabled() and getattr(body, "web", False) and cfg.get("agent_tool_web", True):
        tools.append({
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "联网检索公开网页资料；需要最新、外部事实或新闻时使用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索词"},
                        "prefer_news": {"type": "boolean", "description": "是否按新闻资讯检索"},
                    },
                    "required": ["query"],
                },
            },
        })
    if cfg.get("agent_tool_attachments", True):
        tools.append({
            "type": "function",
            "function": {
                "name": "read_attachments",
                "description": "读取本轮已上传附件的文件名、解析正文和 OCR 摘要；图片以视觉输入为准。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        })
    return tools


async def _execute_tool(name: str, args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "search_knowledge_base": _search_kb,
        "search_library": _search_library,
        "search_web": _search_web,
        "read_attachments": _read_attachments,
    }
    handler = handlers.get(name)
    if not handler:
        return {"ok": False, "error": f"未知工具：{name}", "text": f"未知工具：{name}"}
    try:
        result = await handler(ctx, args)
    except Exception as exc:  # 工具失败要回灌给模型，不能让整条对话崩掉
        log.warning("Agent 工具 %s 执行失败: %s", name, exc)
        return {"ok": False, "error": str(exc)[:300], "text": f"工具执行失败：{str(exc)[:300]}"}
    result.setdefault("text", json.dumps(result, ensure_ascii=False)[:MAX_TOOL_RESULT_CHARS])
    result["text"] = _truncate(result["text"])
    return result


def _tool_calls_of(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = message.get("tool_calls") or []
    return calls if isinstance(calls, list) else []


def _normalize_call(call: dict[str, Any], index: int) -> dict[str, Any]:
    fn = call.get("function") or {}
    name = str(fn.get("name") or call.get("name") or "").strip()
    raw_args = fn.get("arguments", call.get("arguments") or {})
    args = _args(raw_args)
    call_id = str(call.get("id") or f"call_{index}_{time.time_ns()}")
    return {"id": call_id, "name": name, "args": args}


def _add_usage(total: dict[str, Any], usage: dict[str, Any]) -> None:
    if not isinstance(usage, dict):
        return
    total["prompt_tokens"] = int(total.get("prompt_tokens") or 0) + int(usage.get("prompt_tokens") or 0)
    total["completion_tokens"] = (int(total.get("completion_tokens") or 0)
                                   + int(usage.get("completion_tokens") or 0))
    total["total_tokens"] = int(total.get("total_tokens") or 0) + int(usage.get("total_tokens") or 0)


async def run_agent(*, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                    base: str, key: str, model: str, params: dict[str, Any],
                    ctx: dict[str, Any], caller: ToolCaller | None = None) -> dict[str, Any]:
    """执行只读工具闭环，返回最终回答、推理内容、用量和工具轨迹。"""
    cfg = ctx["cfg"]
    max_turns = max(1, min(int(cfg.get("agent_max_turns") or 4), 6))
    usage: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    final_content = ""
    final_reasoning = ""

    async def default_caller(payload: dict[str, Any]) -> dict[str, Any]:
        timeout = httpx.Timeout(connect=10, read=300, write=10, pool=10)
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
        if r.status_code != 200:
            detail = (r.text or "")[:300]
            raise RuntimeError(f"上游返回 {r.status_code}: {detail}")
        return r.json()

    call_llm = caller or default_caller

    async def call_once() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": params.get("temperature", 0.7),
            "max_tokens": params.get("max_tokens", 2048),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = await call_llm(payload)
        _add_usage(usage, data.get("usage") or {})
        choices = data.get("choices") or [{}]
        message = (choices[0] or {}).get("message") or {}
        content = str(message.get("content") or "")
        reasoning = str(message.get("reasoning_content") or message.get("reasoning") or "")
        calls = [_normalize_call(c, i) for i, c in enumerate(_tool_calls_of(message))]
        return {"message": message, "content": content, "reasoning": reasoning,
                "calls": calls}

    async def finish_with(result: dict[str, Any]) -> None:
        nonlocal final_content, final_reasoning
        final_content = result["content"].strip()
        final_reasoning = result["reasoning"].strip()
        final_message: dict[str, Any] = {"role": "assistant", "content": final_content}
        if final_reasoning:
            final_message["reasoning_content"] = final_reasoning
        messages.append(final_message)

    first = await call_once()
    if not first["calls"]:
        await finish_with(first)
    else:
        current = first
        for turn in range(1, max_turns + 1):
            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": current["content"] or "",
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"],
                                  "arguments": json.dumps(c["args"], ensure_ascii=False)}}
                    for c in current["calls"]
                ],
            }
            if current["reasoning"]:
                assistant_message["reasoning_content"] = current["reasoning"]
            messages.append(assistant_message)

            for call in current["calls"]:
                started = time.monotonic()
                result = await _execute_tool(call["name"], call["args"], ctx)
                dur_ms = int((time.monotonic() - started) * 1000)
                trace.append({
                    "tool": call["name"],
                    "turn": turn,
                    "arguments": call["args"],
                    "status": "ok" if result.get("ok") else "error",
                    "summary": result.get("text", "")[:220],
                    "count": result.get("count") or 0,
                    "sources": result.get("sources") or [],
                    "error": result.get("error") or "",
                    "dur_ms": dur_ms,
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": result["text"],
                })

            current = await call_once()
            if not current["calls"]:
                await finish_with(current)
                break
        else:
            messages.append({"role": "system",
                             "content": "已达到本轮最大工具调用次数。请基于已有工具结果直接回答用户，不要再调用工具。"})
            current = await call_once()
            await finish_with(current)

    return {
        "content": final_content.strip(),
        "reasoning": final_reasoning.strip(),
        "usage": usage,
        "trace": trace,
        "messages": messages,
    }
