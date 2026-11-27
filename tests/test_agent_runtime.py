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


def test_build_tools_respects_per_tool_switches():
    ctx = _ctx(cfg={"agent_tool_kb": False, "agent_tool_library": False,
                    "agent_tool_attachments": False}, body={"web": True})
    names = {t["function"]["name"] for t in agent.build_tools(ctx)}
    assert names == {"search_web"}

    ctx2 = _ctx(cfg={"agent_tool_web": False}, body={"web": True})
    names2 = {t["function"]["name"] for t in agent.build_tools(ctx2)}
    assert "search_web" not in names2
    assert {"search_knowledge_base", "search_library", "read_attachments"} <= names2


def test_trace_records_turn_number():
    ctx = _ctx(cfg={"agent_max_turns": 2})
    tools = agent.build_tools(ctx)

    async def caller(payload: dict) -> dict:
        caller.calls += 1
        if caller.calls <= 2:
            return {"choices": [{"message": {
                "content": "",
                "tool_calls": [_tool_call(f"call_{caller.calls}", "read_attachments")],
            }}]}
        return {"choices": [{"message": {"content": "好了。"}}]}

    caller.calls = 0
    result = asyncio.run(agent.run_agent(
        messages=[{"role": "user", "content": "读两轮"}], tools=tools,
        base="http://127.0.0.1:8000", key="", model="test-model",
        params={}, ctx=ctx, caller=caller))
    assert [a["turn"] for a in result["trace"]] == [1, 2]


def test_agent_settings_are_saved_and_exposed(client, admin_token):
    from tests.conftest import auth  # noqa: PLC0415

    from backend.config import load_config

    before = {k: v for k, v in load_config().items() if k.startswith("agent_")}
    try:
        r = client.put("/api/system/settings", headers=auth(admin_token),
                       json={"agent_mode_enabled": False, "agent_max_turns": 5,
                             "agent_tool_kb": False, "agent_tool_library": True,
                             "agent_tool_web": False, "agent_tool_attachments": True})
        assert r.status_code == 200, r.text
        assert set(r.json()["changed"]) >= {
            "agent_mode_enabled", "agent_max_turns", "agent_tool_kb",
            "agent_tool_library", "agent_tool_web", "agent_tool_attachments"}

        body = client.get("/api/system/settings", headers=auth(admin_token)).json()
        assert body["agent_mode_enabled"] is False
        assert body["agent_max_turns"] == 5
        assert body["agent_tool_kb"] is False
        assert body["agent_tool_web"] is False

        tools = agent.build_tools(_ctx(cfg={
            "agent_mode_enabled": False, "agent_tool_kb": False,
            "agent_tool_web": False, "agent_tool_library": True,
            "agent_tool_attachments": True}, body={"web": True}))
        names = {t["function"]["name"] for t in tools}
        assert "search_knowledge_base" not in names
        assert "search_web" not in names
        assert {"search_library", "read_attachments"} <= names
    finally:
        client.put("/api/system/settings", headers=auth(admin_token), json=before)


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
