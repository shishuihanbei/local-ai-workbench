"""半自主检索编排的单测：顺序固定、逐级降级、每步留痕。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.services import agent_semi


def _body(**kw):
    base = {"use_kb": None, "web": False, "library_docs": []}
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def cfg():
    from backend import config as cfgmod
    data = dict(cfgmod.load_config())
    return data


@pytest.mark.asyncio
async def test_all_sources_off_keeps_four_steps(monkeypatch, cfg):
    cfg["kb_enabled"] = False
    cfg["library_enabled"] = False

    async def no_flags(user_id, cfg):
        return False, False

    monkeypatch.setattr(agent_semi, "_kb_flags", no_flags)
    monkeypatch.setattr(agent_semi.library, "user_state", _state_off)
    res = await agent_semi.run("你好", user={"id": 1}, cfg=cfg, body=_body())
    steps = res["steps"]
    assert [s["tool"] for s in steps] == [
        "read_attachments", "search_knowledge_base", "search_library", "search_web"]
    assert all(s["status"] == "skip" for s in steps)
    assert res["prompt"] == ""
    assert res["handles_kb"] is True and res["handles_web"] is True


@pytest.mark.asyncio
async def test_kb_hits_skip_web_when_not_time_sensitive(monkeypatch, cfg):
    cfg["kb_enabled"] = True
    cfg["library_enabled"] = False

    async def flags(user_id, cfg):
        return True, False

    async def fake_search(query, top_k=3, **kw):
        return [{"title": "报销制度", "snippet": "线上提交", "doc_id": 3},
                {"title": "报销时限", "snippet": "7 个工作日", "doc_id": 4}]

    monkeypatch.setattr(agent_semi, "_kb_flags", flags)
    monkeypatch.setattr(agent_semi.kb, "search", fake_search)
    monkeypatch.setattr(agent_semi.library, "user_state", _state_off)
    for name in ("research",):
        monkeypatch.setattr(agent_semi.websearch, name, _boom)

    res = await agent_semi.run("报销怎么提交", user={"id": 1}, cfg=cfg, body=_body(web=True))
    kb_step = next(s for s in res["steps"] if s["tool"] == "search_knowledge_base")
    web_step = next(s for s in res["steps"] if s["tool"] == "search_web")
    assert kb_step["status"] == "ok" and kb_step["count"] == 2
    assert web_step["status"] == "skip"
    assert "跳过联网" in web_step["summary"]
    assert "报销制度" in res["prompt"]


@pytest.mark.asyncio
async def test_time_sensitive_still_searches_web(monkeypatch, cfg):
    cfg["kb_enabled"] = True

    async def flags(user_id, cfg):
        return True, False

    async def fake_search(query, top_k=3, **kw):
        return [{"title": "旧制度", "snippet": "老版本", "doc_id": 1},
                {"title": "旧制度2", "snippet": "老版本", "doc_id": 2}]

    async def fake_research(query, prefer_news=False):
        return {"query": query, "sources": [{"title": "今日新闻", "url": "http://news.local/1"}],
                "error": "", "prompt": "【联网】今日新闻 1 条"}

    monkeypatch.setattr(agent_semi, "_kb_flags", flags)
    monkeypatch.setattr(agent_semi.kb, "search", fake_search)
    monkeypatch.setattr(agent_semi.library, "user_state", _state_off)
    monkeypatch.setattr(agent_semi.websearch, "research", fake_research)

    res = await agent_semi.run("今天的新闻是什么", user={"id": 1}, cfg=cfg,
                               body=_body(web=True))
    web_step = next(s for s in res["steps"] if s["tool"] == "search_web")
    assert web_step["status"] == "ok" and web_step["count"] == 1
    assert res["meta"]["web"]["sources"][0]["url"] == "http://news.local/1"


@pytest.mark.asyncio
async def test_web_failure_leaves_explicit_note(monkeypatch, cfg):
    cfg["kb_enabled"] = False

    async def boom(query, prefer_news=False):
        raise RuntimeError("上游超时")

    monkeypatch.setattr(agent_semi.websearch, "research", boom)
    monkeypatch.setattr(agent_semi.library, "user_state", _state_off)
    res = await agent_semi.run("今天股价多少", user={"id": 1}, cfg=cfg,
                               body=_body(web=True))
    web_step = next(s for s in res["steps"] if s["tool"] == "search_web")
    assert web_step["status"] == "error"
    assert "联网" in res["prompt"] and "不要编造" in res["prompt"]


def _state(global_enabled: bool, personal_enabled: bool) -> dict:
    return {"global_enabled": global_enabled, "use_global": global_enabled,
            "personal_enabled": personal_enabled, "use_personal": personal_enabled,
            "max_docs": 10, "max_chars": 12000}


async def _state_off(user_id, cfg):
    return _state(False, False)


def _boom(*a, **kw):
    raise AssertionError("这一级不应该被调用")


@pytest.mark.asyncio
async def test_chat_marks_agent_plan_semi(client, admin_token, monkeypatch):
    """半自主跑通后，meta 与调用记录都要能看出走的是半自主。"""
    from backend.routers import chat as chat_mod

    async def fake_run(message, **kw):
        return {
            "steps": [{"tool": "search_knowledge_base", "turn": 2, "status": "ok",
                       "arguments": {"query": message}, "count": 1,
                       "summary": "命中 1 条", "sources": [], "error": "", "dur_ms": 30}],
            "trace": [],
            "prompt": "【材料】报销走线上流程。",
            "meta": {"kb": ["报销制度"], "library": None, "web": None},
            "summary": "知识库成功(1 条)",
            "ok_count": 1,
            "handles_kb": True,
            "handles_web": True,
        }

    monkeypatch.setattr(chat_mod.agent_semi, "run", fake_run)
    with client.stream("POST", "/api/chat/stream", headers=_auth(admin_token),
                       json={"message": "报销怎么走", "agent_mode": False}) as r:
        assert r.status_code == 200
        body = "\n".join(r.iter_lines())
    meta = next(json.loads(line[5:]) for line in body.splitlines()
                if line.startswith("data:") and '"type": "meta"' in line)
    assert meta["agent_plan"] == "semi"
    assert meta["agent_tools"][0] == "search_knowledge_base"
    assert meta["kb"] == ["报销制度"]


def _auth(token):
    return {"Authorization": "Bearer " + token}
