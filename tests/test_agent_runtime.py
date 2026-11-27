"""只读工具 Agent 运行时回归测试。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.services import agent


def _ctx(**overrides):
    cfg = {
        "kb_enabled": True,
        "library_enabled": True,
        "agent_max_turns": 2,
    }
    cfg.update(overrides.pop("cfg", {}) or {})
    body = SimpleNamespace(web=False)
    body.__dict__.update(overrides.pop("body", {}) or {})
    return {"user": {"id": 1, "username": "tester"}, "cfg": cfg,
            "body": body, "attachments": [], "extra": {}}


def _tool_call(call_id: str, name: str, args: dict | None = None) -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": args or {}}}


def test_build_tools_respects_switches():
    ctx = _ctx(cfg={"kb_enabled": False, "library_enabled": False}, body={"web": False})
    tools = agent.build_tools(ctx)
    names = {t["function"]["name"] for t in tools}
    assert names == {"read_attachments"}

    ctx2 = _ctx(body={"web": True})
    tools2 = agent.build_tools(ctx2)
    names2 = {t["function"]["name"] for t in tools2}
    assert "search_web" in names2


def test_run_agent_executes_tool_then_final_answer():
    ctx = _ctx()
    tools = agent.build_tools(ctx)
    payloads: list[dict] = []

    async def caller(payload: dict) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [_tool_call("call_1", "read_attachments")],
            }}], "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}
        return {"choices": [{"message": {"content": "附件里只有一句测试文本。"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}}

    result = asyncio.run(agent.run_agent(
        messages=[{"role": "user", "content": "读一下附件"}],
        tools=tools, base="http://127.0.0.1:8000", key="", model="test-model",
        params={"temperature": 0.7, "max_tokens": 2048}, ctx=ctx, caller=caller))

    assert result["content"] == "附件里只有一句测试文本。"
    assert len(result["trace"]) == 1
    assert result["trace"][0]["tool"] == "read_attachments"
    assert result["trace"][0]["status"] == "ok"
    assert result["usage"]["prompt_tokens"] == 13
    assert result["usage"]["completion_tokens"] == 6
    assert any(m["role"] == "tool" and m["tool_call_id"] == "call_1" for m in result["messages"])
    assert payloads[0]["tools"]
    assert payloads[0]["tool_choice"] == "auto"


def test_run_agent_unknown_tool_returns_error_message():
    ctx = _ctx()
    tools = agent.build_tools(ctx)
    payloads: list[dict] = []

    async def caller(payload: dict) -> dict:
        payloads.append(payload)
        if len(payloads) == 1:
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [_tool_call("bad_1", "delete_all_files")],
            }}]}
        return {"choices": [{"message": {"content": "没有可执行的工具，直接回答。"}}]}

    result = asyncio.run(agent.run_agent(
        messages=[{"role": "user", "content": "测试"}],
        tools=tools, base="http://127.0.0.1:8000", key="", model="test-model",
        params={}, ctx=ctx, caller=caller))

    assert result["content"] == "没有可执行的工具，直接回答。"
    assert result["trace"][0]["status"] == "error"
    tool_msg = next(m for m in result["messages"] if m["role"] == "tool")
    assert "未知工具" in tool_msg["content"]


def test_run_agent_stops_after_max_turns_and_forces_final_answer():
    ctx = _ctx(cfg={"agent_max_turns": 1})
    tools = agent.build_tools(ctx)

    async def caller(payload: dict) -> dict:
        if len(caller.calls) < 2:
            caller.calls.append(payload)
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [_tool_call(f"call_{len(caller.calls)}", "read_attachments")],
            }}]}
        return {"choices": [{"message": {"content": "达到上限，基于已有结果回答。"}}]}

    caller.calls = []
    result = asyncio.run(agent.run_agent(
        messages=[{"role": "user", "content": "反复读附件"}],
        tools=tools, base="http://127.0.0.1:8000", key="", model="test-model",
        params={}, ctx=ctx, caller=caller))

    assert len(caller.calls) == 2
    assert result["content"] == "达到上限，基于已有结果回答。"
    assert len(result["trace"]) == 1
    assert result["messages"][-2]["role"] == "system"
