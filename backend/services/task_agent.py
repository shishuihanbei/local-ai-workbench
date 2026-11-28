"""任务 Agent：把「定时跑一轮对话」升级成 计划 → 执行 → 自检 → 重试 的闭环。

设计取舍：
- 计划阶段不再额外调用一次模型（本机弱 CPU 上一次多轮规划代价太高），
  而是按任务配置（是否联网、是否有输出格式、是否续接档案）生成
  可读的固定计划，再把模型自己的工具轨迹当作执行记录，一起落进 task_runs。
- 自检先用规则判定（空回答、套话式“无法提供”、过短结论、接口报错），
  只有判为不可用时才重试一次，避免每条任务都多花一倍算力。
- 任务档案保存最近几条结论，下一次运行把它当背景，实现“持续跟进同一件事”。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Awaitable, Callable

MAX_ATTEMPTS = 2
MEMORY_LINES = 3
MEMORY_LINE_CHARS = 320
SUMMARY_CHARS = 800

WEAK_MARKERS = (
    "无法提供", "无法获取", "无法回答", "暂时无法", "没有找到相关",
    "没有相关信息", "我不知道", "抱歉，我", "对不起，我",
)


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def build_plan(task: dict[str, Any]) -> list[dict[str, Any]]:
    """按任务配置生成可读计划；不消耗模型算力，也不会假装做过没做的事。"""
    goal = str(task.get("prompt") or task.get("title") or "").strip()
    plan: list[dict[str, Any]] = [{
        "step": "plan",
        "title": "确认目标",
        "status": "ok",
        "detail": _clip(goal, 160),
    }]
    collects: list[str] = []
    if bool(task.get("web_enabled")):
        collects.append("联网检索最新信息并保留来源")
    if bool(task.get("agent_id")):
        collects.append("按指定智能体的人设与规则作答")
    plan.append({
        "step": "collect",
        "title": "收集材料",
        "status": "ok",
        "detail": "；".join(collects) if collects else "不额外检索，直接用模型知识与任务档案",
    })
    fmt = str(task.get("output_format") or "").strip()
    plan.append({
        "step": "produce",
        "title": "产出结果",
        "status": "ok",
        "detail": f"整理成 {fmt} 交付" if fmt else "整理成一段可直接阅读的结论",
    })
    plan.append({
        "step": "verify",
        "title": "自检交付",
        "status": "ok",
        "detail": "检查结论是否空泛、是否只给了套话；不合格就换思路重试一次",
    })
    return plan


def compose_message(task: dict[str, Any], memory: str = "", attempt: int = 1) -> str:
    """把目标、任务档案和本轮要求拼成一条消息，交给通用助手执行。"""
    parts: list[str] = []
    goal = str(task.get("prompt") or "").strip()
    criteria = str(task.get("goal") or "").strip()
    parts.append(f"【任务目标】\n{goal}" if goal else "【任务目标】\n按任务标题完成一次结果整理。")
    if criteria:
        parts.append(f"【成功标准】\n{criteria}")
    if memory.strip():
        parts.append("【任务档案·上次结论，可在此基础上延续或修正】\n" + memory.strip())
    parts.append(
        "【执行要求】\n"
        "1. 先判断目标需要哪些最新或本地信息，需要就去查，再动笔。\n"
        "2. 结论要具体：关键数字、时间、人名、来源都写清楚；查不到就明说查不到。\n"
        "3. 只输出最终结果，不要复述任务，不要写“我将如何执行”的过程。")
    if attempt > 1:
        parts.append(
            "【重试提示】上一轮没有产出可用结论。这一轮换个思路："
            "把目标拆成两三个小问题逐个查证，再汇总成结论，不要沿用上一轮的写法。")
    return "\n\n".join(parts)


def judge(content: str, *, error: str = "", files: list[dict[str, Any]] | None = None) -> tuple[str, str]:
    """规则自检：返回 (verdict, reason)。verdict 取 ok / weak / failed。"""
    if error:
        return "failed", _clip(error, 160)
    if files:
        return "ok", "已生成文件交付"
    text = (content or "").strip()
    if not text:
        return "failed", "本轮没有产出正文"
    clipped = text[:400]
    if any(marker in clipped for marker in WEAK_MARKERS):
        if len(text) < 200:
            return "weak", "回答停留在“查不到/无法提供”，没有给出可用结论"
        return "weak", "回答里有较多免责表述，结论不够明确"
    if len(text) < 40:
        return "weak", "回答过短，信息量不足"
    return "ok", "结论具备可用信息量"


def merge_memory(previous: str, task: dict[str, Any], conclusion: str) -> str:
    """任务档案滚动保存最近几条结论，控制长度，避免撑爆上下文。"""
    lines = [line.strip() for line in str(previous or "").splitlines() if line.strip()]
    stamp = datetime.now().strftime("%m-%d %H:%M")
    title = _clip(str(task.get("title") or "任务"), 24)
    body = _clip(" ".join(str(conclusion or "").split()), MEMORY_LINE_CHARS)
    if body:
        lines.append(f"{stamp} · {title}：{body}")
    return "\n".join(lines[-MEMORY_LINES:])


def parse_steps(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(str(raw or "") or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def summarize(steps: list[dict[str, Any]], verdict: str, content: str,
              attempts: int = 1) -> str:
    """给任务列表用的一句话结论：先给自检判断，再给结论摘要。"""
    body = _clip(" ".join(str(content or "").split()), SUMMARY_CHARS)
    head = {"ok": "已完成", "weak": "结论偏弱", "failed": "未完成"}.get(verdict, "已完成")
    return f"{head}{'（已重试）' if attempts > 1 else ''}：{body}" if body else head


CallFn = Callable[[str, int], Awaitable[dict[str, Any]]]
StepHook = Callable[[list[dict[str, Any]]], Awaitable[None]]


def _tool_steps(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把助手运行时上报的工具动作转成任务步骤，让控制台看到真实的执行轨迹。"""
    out: list[dict[str, Any]] = []
    for item in trace or []:
        tool = str(item.get("tool") or "").strip()
        if not tool:
            continue
        out.append({
            "step": "tool",
            "title": tool,
            "status": str(item.get("status") or "ok"),
            "detail": _clip(str(item.get("summary") or item.get("error") or ""), 180),
            "dur_ms": int(item.get("dur_ms") or 0),
            "attempt": int(item.get("turn") or 0),
        })
    return out


async def run_task(task: dict[str, Any], *, memory: str, call: CallFn,
                   on_steps: StepHook | None = None) -> dict[str, Any]:
    """执行一次任务：计划 → 执行 → 自检 → 必要时重试。

    `call(message, attempt)` 负责真正跑一轮对话，返回
    {"content", "files", "error", "conversation_id", "trace"}。
    `on_steps` 用于执行中就把步骤写进运行记录，前端能边跑边看。
    """
    steps: list[dict[str, Any]] = build_plan(task)
    attempts = 0
    verdict = "failed"
    reason = "尚未执行"
    content = ""
    error = ""
    files: list[dict[str, Any]] = []
    conversation_id: int | None = None

    async def flush() -> None:
        if on_steps:
            try:
                await on_steps(steps)
            except Exception:
                pass

    await flush()
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        message = compose_message(task, memory, attempts)
        result = await call(message, attempts)
        content = str(result.get("content") or "").strip()
        error = str(result.get("error") or "").strip()
        files = list(result.get("files") or [])
        if result.get("conversation_id"):
            conversation_id = int(result["conversation_id"])
        steps.extend(_tool_steps(result.get("trace") or []))
        verdict, reason = judge(content, error=error, files=files)
        steps.append({
            "step": f"run{attempts}",
            "title": f"第 {attempts} 轮执行",
            "status": "ok" if verdict == "ok" else ("skip" if verdict == "weak" else "error"),
            "detail": _clip(reason, 200),
            "attempt": attempts,
        })
        await flush()
        if verdict == "ok":
            break
        if attempts < MAX_ATTEMPTS:
            steps.append({
                "step": f"retry{attempts}",
                "title": "自检未通过，换思路重试",
                "status": "retry",
                "detail": _clip(reason, 200),
                "attempt": attempts,
            })
            await flush()

    steps.append({
        "step": "verify",
        "title": "自检结论",
        "status": "ok" if verdict == "ok" else "error",
        "detail": _clip(reason, 200),
        "attempt": attempts,
    })
    await flush()

    status = "ok" if verdict == "ok" else "error"
    summary = summarize(steps, verdict, content, attempts) if verdict == "ok" else _clip(error or reason, 300)
    if verdict != "ok" and not error:
        error = f"自检未通过：{reason}"
    new_memory = merge_memory(memory, task, content) if verdict == "ok" else memory

    return {
        "status": status,
        "verdict": verdict,
        "reason": reason,
        "summary": summary,
        "content": content,
        "error": error,
        "files": files,
        "steps": steps,
        "attempts": attempts,
        "conversation_id": conversation_id,
        "memory": new_memory,
    }
