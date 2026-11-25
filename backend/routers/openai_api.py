"""OpenAI 兼容 API：/v1/models、/v1/chat/completions。

只接受用户自己生成的 API Key（Authorization: Bearer 或 x-api-key），
不复用管理控制台的登录会话，避免 Key 权限过大。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import logbus, pipeline
from ..config import load_config
from ..services import access, apikeys, cluster, moderation, netinfo, quota, routing

router = APIRouter(tags=["openai"])


def _raw_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return request.headers.get("x-api-key", "").strip()


async def _api_user(request: Request) -> dict[str, Any] | None:
    raw = _raw_key(request)
    if not raw:
        return None
    net = netinfo.detect(request)
    user = await apikeys.authenticate(raw, net.get("client_ip", ""), net.get("label", ""))
    if user:
        user["_net_scope"] = net.get("label", "")
        user["_net_ip"] = net.get("client_ip", "")
    return user


def _error(message: str, status: int = 400, type_: str = "invalid_request_error",
           code: str | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": type_, "code": code or "bad_request"}},
        status_code=status)


async def _select_model(user: dict, requested: str | None) -> tuple[str | None, JSONResponse | None]:
    requested = (requested or "").strip()
    if requested:
        if not await access.can_use(user, requested):
            return None, _error("该模型未对当前用户开放", 403, "permission_error",
                                "model_not_allowed")
        return requested, None
    first = await access.first_model(user)
    if first == "":
        return None, _error("管理员尚未给该用户分配可用模型", 403, "permission_error")
    if first:
        return first, None
    cfg = load_config()
    if cfg.get("local_enabled", True) is False:
        from ..db import fetch_all
        for p in await fetch_all("SELECT models FROM providers WHERE enabled=1 ORDER BY id"):
            names = [x.strip() for x in (p["models"] or "").split(",") if x.strip()]
            if names:
                return names[0], None
        return None, _error("本地部署已关闭，且没有可用的第三方模型", 503, "server_error",
                            "local_disabled")
    return str(cfg.get("model") or ""), None


def _messages_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            parts.append(f"{m.get('role', 'user')}: {content}")
        else:
            parts.append(f"{m.get('role', 'user')}: {json.dumps(content, ensure_ascii=False)}")
    return "\n".join(parts)


def _replace_json(value: Any, words: list[str], replacement: str) -> Any:
    if isinstance(value, str):
        return moderation.replace_words(value, words, replacement)
    if isinstance(value, list):
        return [_replace_json(x, words, replacement) for x in value]
    if isinstance(value, dict):
        return {k: _replace_json(v, words, replacement) for k, v in value.items()}
    return value


def _stream_chunk(base: dict, model: str, text: str) -> dict:
    return {
        "id": base.get("id") or "chatcmpl-workbench",
        "object": "chat.completion.chunk",
        "created": base.get("created") or int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


async def _guard_api_messages(messages: list[dict], user: dict, model: str) -> tuple[list[dict], JSONResponse | None]:
    last = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    if not last:
        return messages, None
    content = last.get("content")
    scan = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    guard = await moderation.guard_input(scan, user=user, model=model)
    if guard["blocked"]:
        return messages, _error(
            "输入内容包含敏感词：" + "、".join(guard["matches"][:6]),
            400, "invalid_request_error", "content_blocked")
    if guard["matches"] and guard["action"] == "replace":
        cfg = moderation.settings()
        last["content"] = _replace_json(content, guard["matches"], cfg["replace_with"])
    return messages, None


async def _guard_api_output(data: dict, user: dict, model: str) -> tuple[str, bool]:
    """就地把非流式响应正文替换/拦截，返回（最终正文，是否拦截）。"""
    msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
    full = msg.get("content") if isinstance(msg.get("content"), str) else ""
    if not full:
        return "", False
    guard = await moderation.guard_output(full, user=user, model=model)
    if guard["matches"]:
        msg["content"] = guard["text"]
    return guard["text"], guard["blocked"]


async def _log_call(*, user: dict, trace_id: str, started_wall: float, started: float,
                    body: dict, prompt_text: str, decision: dict, model_name: str,
                    status: str, err: str, usage: dict, full: str, ttft_ms: int,
                    stream: bool) -> None:
    total_ms = int((time.monotonic() - started) * 1000)
    ptok = int(usage.get("prompt_tokens") or 0)
    ctok = int(usage.get("completion_tokens") or 0)
    estimated = False
    if not ptok:
        ptok = pipeline.estimate_tokens(prompt_text)
        estimated = True
    if not ctok:
        ctok = pipeline.estimate_tokens(full)
        estimated = True
    price_in = float(decision.get("price_in") or 0)
    price_out = float(decision.get("price_out") or 0)
    cost = round((ptok * price_in + ctok * price_out) / 1_000_000, 6)
    params = {k: body.get(k) for k in ("temperature", "top_p", "max_tokens",
                                       "max_completion_tokens", "stream")}
    event = {
        "request": {
            "trace_id": trace_id, "user_id": user["id"], "conversation_id": None,
            "route_id": decision.get("route_id"), "provider": decision.get("provider"),
            "provider_id": decision.get("provider_id"), "model": model_name, "stream": stream,
            "status": status, "error": err or None,
            "prompt_hash": pipeline.prompt_hash(model_name, prompt_text, params, "api"),
            "prompt_rendered": prompt_text[:12000],
            "params_json": json.dumps(params, ensure_ascii=False),
            "decision_json": json.dumps(
                {k: v for k, v in decision.items() if k != "key"}, ensure_ascii=False),
            "prompt_tokens": ptok, "completion_tokens": ctok,
            "total_tokens": ptok + ctok, "tokens_estimated": estimated,
            "cost": cost, "price_in": price_in, "price_out": price_out,
            "ttft_ms": ttft_ms, "total_ms": total_ms, "queue_ms": 0,
            "retries": 0, "cache_hit": False, "cache_id": None,
            "experiment_id": None, "bucket": 0, "shadow_of": None,
            "created_at": started_wall,
        },
        "spans": [
            {"kind": "llm", "name": model_name, "start_ms": 0, "dur_ms": total_ms,
             "attrs": {"provider": decision.get("provider"), "ttft_ms": ttft_ms,
                       "tokens": ptok + ctok, "status": status, "via": "openai_api",
                       "api_key": user.get("key_name", "")}},
        ],
    }
    await logbus.put(event)


def _pool_attempts(pool: dict, candidates: list[dict]) -> list[dict]:
    retries = max(0, min(int(pool.get("retries") or 0), 5))
    return candidates[:max(1, min(len(candidates), retries + 1))]


def _node_headers(candidate: dict) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if candidate.get("key"):
        headers["Authorization"] = f"Bearer {candidate['key']}"
    return headers


def _pool_decision(pool: dict, candidate: dict | None = None) -> dict:
    data = {
        "provider": f"算力池 · {pool['name']}",
        "pool": pool["name"],
        "pool_id": pool["id"],
        "strategy": pool.get("strategy"),
        "model": pool["name"],
        "price_in": 0,
        "price_out": 0,
    }
    if candidate:
        data.update({"node": candidate["node_name"], "node_id": candidate["node_id"],
                     "remote_model": candidate["model"]})
    return data


async def _pool_nonstream(*, user: dict, request: Request, pool: dict, candidates: list[dict],
                          payload: dict, trace_id: str, started_wall: float, started: float,
                          body: dict, prompt_text: str, model: str) -> JSONResponse:
    errors: list[str] = []
    last_decision = _pool_decision(pool)
    for candidate in _pool_attempts(pool, candidates):
        cluster.begin(candidate["node_id"])
        attempt_started = time.monotonic()
        try:
            upstream = {**payload, "model": candidate["model"]}
            timeout = httpx.Timeout(connect=10, read=max(30, float(pool.get("timeout") or 30)),
                                    write=10, pool=10)
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(f"{candidate['base']}/chat/completions",
                                      json=upstream, headers=_node_headers(candidate))
            latency = int((time.monotonic() - attempt_started) * 1000)
            last_decision = _pool_decision(pool, candidate)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    data["model"] = model
                await cluster.record_success(candidate["node_id"], latency)
                usage = data.get("usage") or {}
                choices = data.get("choices") or [{}]
                msg = (choices[0] or {}).get("message") or {}
                full = msg.get("content") if isinstance(msg.get("content"), str) else ""
                out, blocked = await _guard_api_output(data, user, model)
                await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                                started=attempt_started, body=body, prompt_text=prompt_text,
                                decision=last_decision, model_name=model,
                                status="moderation_blocked" if blocked else "ok",
                                err="输出触发内容安全策略" if blocked else "",
                                usage=usage, full=out or full or "", ttft_ms=latency, stream=False)
                return JSONResponse(data)
            detail = r.text[:500]
            errors.append(f"{candidate['node_name']} HTTP {r.status_code}")
            if r.status_code >= 500:
                await cluster.record_failure(candidate["node_id"], detail)
            if r.status_code == 429 or r.status_code >= 500:
                continue
            err = f"上游 {candidate['node_name']} 返回 {r.status_code}: {detail[:200]}"
            await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                            started=attempt_started, body=body, prompt_text=prompt_text,
                            decision=last_decision, model_name=model, status="error", err=err,
                            usage={}, full="", ttft_ms=0, stream=False)
            return _error(err, 502, "upstream_error", "upstream_error")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = f"{candidate['node_name']} 连接失败：{str(exc)[:160]}"
            errors.append(err)
            await cluster.record_failure(candidate["node_id"], str(exc))
        finally:
            cluster.end(candidate["node_id"])
    err = "所有节点都失败" + ("：" + "；".join(errors[-3:]) if errors else "")
    await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                    started=started, body=body, prompt_text=prompt_text,
                    decision=last_decision, model_name=model, status="error", err=err,
                    usage={}, full="", ttft_ms=0, stream=False)
    return _error(err, 503, "server_error", "pool_unavailable")


async def _pool_event_stream(*, request: Request, user: dict, pool: dict, candidates: list[dict],
                             payload: dict, trace_id: str, started_wall: float, started: float,
                             body: dict, prompt_text: str, model: str) -> AsyncIterator[bytes]:
    content: list[str] = []
    usage: dict = {}
    status, err = "ok", ""
    ttft_ms = 0
    selected: dict | None = None
    errors: list[str] = []
    success = False
    emitted_error = False
    last_obj: dict = {}
    mod_cfg = moderation.settings()
    mod_words = await moderation.active_words() if mod_cfg["enabled"] else []
    stream_filter = moderation.StreamFilter(
        action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
        words=mod_words, replacement=mod_cfg["replace_with"], min_chars=mod_cfg["min_chars"])
    for candidate in _pool_attempts(pool, candidates):
        if await request.is_disconnected():
            status = "stopped"
            break
        cluster.begin(candidate["node_id"])
        attempt_started = time.monotonic()
        committed = False
        try:
            upstream = {**payload, "model": candidate["model"]}
            timeout = httpx.Timeout(connect=10, read=None, write=10, pool=10)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{candidate['base']}/chat/completions",
                                         json=upstream, headers=_node_headers(candidate)) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        errors.append(f"{candidate['node_name']} HTTP {r.status_code}")
                        if r.status_code >= 500:
                            await cluster.record_failure(candidate["node_id"], detail)
                        if r.status_code == 429 or r.status_code >= 500:
                            continue
                        err = f"上游 {candidate['node_name']} 返回 {r.status_code}: {detail[:200]}"
                        status = "error"
                        yield f"data: {json.dumps({'error': {'message': err}}, ensure_ascii=False)}\n\n".encode()
                        emitted_error = True
                        break
                    selected = candidate
                    first = True
                    async for line in r.aiter_lines():
                        if await request.is_disconnected():
                            status = "stopped"
                            break
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            tail = stream_filter.flush()
                            if tail:
                                content.append(tail)
                                yield (f"data: {json.dumps(_stream_chunk(last_obj, model, tail), ensure_ascii=False)}\n\n").encode()
                            yield b"data: [DONE]\n\n"
                            break
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            yield (line + "\n\n").encode()
                            continue
                        last_obj = obj
                        obj["model"] = model
                        if obj.get("usage"):
                            usage = obj["usage"]
                        for ch in obj.get("choices") or []:
                            delta = ch.get("delta") or {}
                            piece = delta.get("content")
                            if isinstance(piece, str) and piece:
                                if first:
                                    ttft_ms = int((time.monotonic() - started) * 1000)
                                    first = False
                                    committed = True
                                safe = stream_filter.feed(piece)
                                if stream_filter.blocked:
                                    status = "moderation_blocked"
                                    err = "输出触发内容安全策略"
                                    delta["content"] = ""
                                    yield f"data: {json.dumps({'error': {'message': err, 'code': 'content_blocked'}}, ensure_ascii=False)}\n\n".encode()
                                    emitted_error = True
                                    yield b"data: [DONE]\n\n"
                                    break
                                delta["content"] = safe
                                if safe:
                                    content.append(safe)
                        if status == "moderation_blocked":
                            break
                        yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode()
                    if status == "stopped" or status == "moderation_blocked":
                        break
                    latency = int((time.monotonic() - attempt_started) * 1000)
                    await cluster.record_success(candidate["node_id"], latency)
                    success = True
                    break
        except asyncio.CancelledError:
            status = "stopped"
            raise
        except Exception as exc:
            errors.append(f"{candidate['node_name']} 连接失败：{str(exc)[:160]}")
            await cluster.record_failure(candidate["node_id"], str(exc))
            if committed:
                err = f"上游 {candidate['node_name']} 中断：{str(exc)[:160]}"
                status = "error"
                yield f"data: {json.dumps({'error': {'message': err}}, ensure_ascii=False)}\n\n".encode()
                emitted_error = True
                break
            continue
        finally:
            cluster.end(candidate["node_id"])
    if not success and status not in ("stopped", "moderation_blocked"):
        status = "error"
        err = "所有节点都失败" + ("：" + "；".join(errors[-3:]) if errors else "")
        if not content and not emitted_error:
            yield f"data: {json.dumps({'error': {'message': err}}, ensure_ascii=False)}\n\n".encode()
    decision = _pool_decision(pool, selected)
    if stream_filter.matched:
        await moderation.record_hit(
            user=user, direction="output",
            action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
            words=list(dict.fromkeys(stream_filter.matched)),
            text="".join(content), model=model, conversation_id=None)
    await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                    started=started, body=body, prompt_text=prompt_text, decision=decision,
                    model_name=model, status=status, err=err, usage=usage,
                    full="".join(content), ttft_ms=ttft_ms, stream=True)


@router.get("/v1/models")
async def models(request: Request):
    user = await _api_user(request)
    if not user:
        return _error("API Key 无效或已撤销", 401, "authentication_error", "invalid_api_key")
    items = await apikeys.models_for(user)
    return {
        "object": "list",
        "data": [{"id": m["id"], "object": "model", "created": 0,
                  "owned_by": m["owned_by"]} for m in items],
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    user = await _api_user(request)
    if not user:
        return _error("API Key 无效或已撤销", 401, "authentication_error", "invalid_api_key")
    ok, reason = await quota.check(user)
    if not ok:
        return _error(reason, 429, "insufficient_quota", "quota_exceeded")
    try:
        body = await request.json()
    except Exception:
        return _error("请求体必须是 JSON")
    if not isinstance(body, dict):
        return _error("请求体必须是 JSON 对象")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return _error("messages 不能为空")
    if not all(isinstance(m, dict) and m.get("role") for m in messages):
        return _error("messages 格式不正确")

    requested = body.get("model")
    model, bad = await _select_model(user, requested if isinstance(requested, str) else None)
    if bad:
        return bad
    messages, guard_error = await _guard_api_messages(messages, user, model)
    if guard_error:
        return guard_error
    cfg = load_config()
    pool = await cluster.pool_by_name(model)
    if pool:
        _, candidates = await cluster.candidates(model)
        if not candidates:
            return _error("模型池还没有可用节点，请先在控制台加入节点和成员",
                          503, "server_error", "pool_empty")
        decision = _pool_decision(pool)
    else:
        decision = await routing.resolve(SimpleNamespace(model=model), cfg)
        if decision.get("disabled"):
            return _error(decision.get("reason") or "本地部署已关闭", 503, "server_error",
                          "local_disabled")
        if not decision.get("base"):
            return _error("未配置上游模型服务地址", 503, "server_error", "upstream_not_configured")

    stream = bool(body.get("stream", False))
    try:
        max_tokens = int(body.get("max_tokens") or body.get("max_completion_tokens") or 2048)
    except (TypeError, ValueError):
        return _error("max_tokens 必须是整数")
    if max_tokens < 1 or max_tokens > 8192:
        return _error("max_tokens 需要在 1–8192 之间")
    payload: dict[str, Any] = {
        "model": decision["model"],
        "messages": messages,
        "stream": stream,
        "temperature": body.get("temperature", 0.7),
        "max_tokens": max_tokens,
    }
    for key in ("top_p", "stop", "presence_penalty", "frequency_penalty", "seed",
                "response_format", "tools", "tool_choice"):
        if key in body:
            payload[key] = body[key]

    trace_id = uuid.uuid4().hex[:16]
    started_wall = time.time()
    started = time.monotonic()
    prompt_text = _messages_text(messages)
    if pool:
        if not stream:
            return await _pool_nonstream(
                user=user, request=request, pool=pool, candidates=candidates,
                payload=payload, trace_id=trace_id, started_wall=started_wall,
                started=started, body=body, prompt_text=prompt_text, model=model)
        return StreamingResponse(
            _pool_event_stream(request=request, user=user, pool=pool, candidates=candidates,
                               payload=payload, trace_id=trace_id, started_wall=started_wall,
                               started=started, body=body, prompt_text=prompt_text, model=model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    base = str(decision["base"]).rstrip("/")
    key = str(decision.get("key") or "")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout = httpx.Timeout(connect=10, read=None if stream else 300, write=10, pool=10)

    if not stream:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
            if r.status_code != 200:
                err = r.text[:500]
                await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                                started=started, body=body, prompt_text=prompt_text,
                                decision=decision, model_name=decision["model"],
                                status="error", err=err, usage={}, full="", ttft_ms=0,
                                stream=False)
                return _error(f"上游返回 {r.status_code}: {err[:200]}", 502,
                              "upstream_error", "upstream_error")
            data = r.json()
        except Exception as e:
            err = str(e)[:500]
            await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                            started=started, body=body, prompt_text=prompt_text,
                            decision=decision, model_name=decision["model"],
                            status="error", err=err, usage={}, full="", ttft_ms=0,
                            stream=False)
            return _error(f"上游连接失败：{err[:200]}", 502, "upstream_error")
        usage = data.get("usage") or {}
        choices = data.get("choices") or [{}]
        msg = (choices[0] or {}).get("message") or {}
        full = msg.get("content") if isinstance(msg.get("content"), str) else ""
        out, blocked = await _guard_api_output(data, user, model)
        await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                        started=started, body=body, prompt_text=prompt_text,
                        decision=decision, model_name=decision["model"],
                        status="moderation_blocked" if blocked else "ok",
                        err="输出触发内容安全策略" if blocked else "",
                        usage=usage, full=out or full or "",
                        ttft_ms=int((time.monotonic() - started) * 1000), stream=False)
        return JSONResponse(data)

    mod_cfg = moderation.settings()
    mod_words = await moderation.active_words() if mod_cfg["enabled"] else []
    stream_filter = moderation.StreamFilter(
        action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
        words=mod_words, replacement=mod_cfg["replace_with"], min_chars=mod_cfg["min_chars"])

    async def event_stream() -> AsyncIterator[bytes]:
        content: list[str] = []
        usage: dict = {}
        status, err = "ok", ""
        ttft_ms = 0
        first = True
        last_obj: dict = {}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{base}/chat/completions",
                                         json=payload, headers=headers) as r:
                    if r.status_code != 200:
                        detail = (await r.aread()).decode("utf-8", "replace")[:300]
                        err = f"上游返回 {r.status_code}: {detail}"
                        status = "error"
                        yield f"data: {json.dumps({'error': {'message': err}}, ensure_ascii=False)}\n\n".encode()
                        return
                    async for line in r.aiter_lines():
                        if await request.is_disconnected():
                            status = "stopped"
                            break
                        if not line:
                            continue
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            tail = stream_filter.flush()
                            if tail:
                                content.append(tail)
                                yield (f"data: {json.dumps(_stream_chunk(last_obj, model, tail), ensure_ascii=False)}\n\n").encode()
                            yield b"data: [DONE]\n\n"
                            break
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            yield (line + "\n\n").encode()
                            continue
                        last_obj = obj
                        if obj.get("usage"):
                            usage = obj["usage"]
                        for ch in obj.get("choices") or []:
                            delta = ch.get("delta") or {}
                            piece = delta.get("content")
                            if isinstance(piece, str) and piece:
                                if first:
                                    ttft_ms = int((time.monotonic() - started) * 1000)
                                    first = False
                                safe = stream_filter.feed(piece)
                                if stream_filter.blocked:
                                    status = "moderation_blocked"
                                    err = "输出触发内容安全策略"
                                    delta["content"] = ""
                                    yield f"data: {json.dumps({'error': {'message': err, 'code': 'content_blocked'}}, ensure_ascii=False)}\n\n".encode()
                                    yield b"data: [DONE]\n\n"
                                    break
                                delta["content"] = safe
                                if safe:
                                    content.append(safe)
                        if status == "moderation_blocked":
                            break
                        yield (f"data: {json.dumps(obj, ensure_ascii=False)}\n\n").encode()
        except asyncio.CancelledError:
            status = "stopped"
            raise
        except Exception as e:
            err = str(e)[:500]
            status = "error"
            yield f"data: {json.dumps({'error': {'message': err}}, ensure_ascii=False)}\n\n".encode()
        finally:
            if stream_filter.matched:
                await moderation.record_hit(
                    user=user, direction="output",
                    action=mod_cfg["output_action"] if mod_cfg["enabled"] else "warn",
                    words=list(dict.fromkeys(stream_filter.matched)),
                    text="".join(content), model=model, conversation_id=None)
            await _log_call(user=user, trace_id=trace_id, started_wall=started_wall,
                            started=started, body=body, prompt_text=prompt_text,
                            decision=decision, model_name=decision["model"],
                            status=status, err=err, usage=usage, full="".join(content),
                            ttft_ms=ttft_ms, stream=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
