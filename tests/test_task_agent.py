"""任务 Agent：计划、自检、重试与任务档案。"""
from __future__ import annotations

import asyncio

from backend.services import task_agent

TASK = {
    "id": 1,
    "title": "每日 AI 简报",
    "prompt": "整理今天的 AI 行业动态，输出 5 条带来源。",
    "goal": "每条都有来源链接",
    "web_enabled": 1,
    "output_format": "",
}


def test_build_plan_reflects_task_config():
    steps = task_agent.build_plan(TASK)
    names = [s["step"] for s in steps]
    assert names == ["plan", "collect", "produce", "verify"]
    collect = next(s for s in steps if s["step"] == "collect")
    assert "联网检索" in collect["detail"]
    produce = next(s for s in steps if s["step"] == "produce")
    assert "结论" in produce["detail"]


def test_compose_message_carries_memory_and_retry_hint():
    msg = task_agent.compose_message(
        TASK, memory="11-27 09:00 · 每日 AI 简报：昨天三条要闻…", attempt=2)
    assert "任务目标" in msg
    assert "成功标准" in msg
    assert "任务档案" in msg and "昨天三条要闻" in msg
    assert "重试提示" in msg

    plain = task_agent.compose_message(TASK, memory="", attempt=1)
    assert "重试提示" not in plain and "任务档案" not in plain


def test_judge_rules():
    assert task_agent.judge("今天有三条重要动态：" + "内容" * 20) == (
        "ok", "结论具备可用信息量")
    assert task_agent.judge("", error="上游 500")[0] == "failed"
    assert task_agent.judge("")[0] == "failed"
    assert task_agent.judge("抱歉，我无法获取实时数据。")[0] == "weak"
    assert task_agent.judge("太短")[0] == "weak"
    assert task_agent.judge("", files=[{"name": "简报.docx"}])[0] == "ok"


def test_merge_memory_keeps_last_three_lines():
    prev = "\n".join(f"line{i}" for i in range(1, 5))
    merged = task_agent.merge_memory(prev, TASK, "新的结论正文")
    lines = merged.splitlines()
    assert len(lines) == 3
    assert lines[-1].endswith("新的结论正文")
    assert "line4" in merged and "line1" not in merged


def test_run_task_retries_once_after_weak_answer():
    calls: list[int] = []

    async def call(message: str, attempt: int) -> dict:
        calls.append(attempt)
        if attempt == 1:
            return {"content": "抱歉，我无法获取最新数据。", "trace": [
                {"tool": "web_search", "status": "ok", "summary": "7 条结果", "turn": 1}]}
        return {"content": "11 月 28 日有三条值得关注的动态：" + "细节描述。" * 20,
                "conversation_id": 99}

    result = asyncio.run(task_agent.run_task(TASK, memory="", call=call))
    assert calls == [1, 2]
    assert result["status"] == "ok" and result["verdict"] == "ok"
    assert result["attempts"] == 2
    assert result["conversation_id"] == 99
    steps = [s["step"] for s in result["steps"]]
    assert "retry1" in steps and "verify" in steps
    assert any(s["step"] == "tool" and s["title"] == "web_search" for s in result["steps"])
    assert "每日 AI 简报" in result["memory"]


def test_run_task_gives_up_after_second_failure():
    async def call(message: str, attempt: int) -> dict:
        return {"content": "", "error": "模型无响应"}

    result = asyncio.run(task_agent.run_task(TASK, memory="旧档案", call=call))
    assert result["status"] == "error" and result["verdict"] == "failed"
    assert result["attempts"] == 2
    assert result["memory"] == "旧档案"
    assert "模型无响应" in result["error"]
