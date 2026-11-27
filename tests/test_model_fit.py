"""模型适配：小模型不接大任务。"""
from __future__ import annotations

import asyncio

from backend.services import model_fit, platform_models


def test_params_and_light_model():
    assert model_fit.params_b("qwen2.5:0.5b") == 0.5
    assert model_fit.params_b("qwen3-8b") == 8.0
    assert model_fit.params_b("R1-1.5B") == 1.5
    assert model_fit.is_light("qwen2.5:0.5b") is True
    assert model_fit.is_light("qwen3-8b") is False
    assert model_fit.is_light("custom-large") is False


def test_needs_strong():
    assert model_fit.needs_strong("初中二次方程生成一个ppt，内容要全") is True
    assert model_fit.needs_strong("你好") is False
    assert model_fit.needs_strong("随便聊聊", "docx") is True


class _Body:
    def __init__(self, model: str, message: str):
        self.model = model
        self.message = message


def test_small_model_escalates_for_real_task(monkeypatch, client):
    async def no_platforms(cfg):
        return []

    async def no_pools(sql, params=None):
        return []

    monkeypatch.setattr(platform_models, "reachable", no_platforms)
    monkeypatch.setattr("backend.db.fetch_all", no_pools)
    sw = asyncio.run(model_fit.maybe_escalate(
        _Body("qwen2.5:0.5b", "帮我生成一份初中二次方程 PPT，内容要全"), {"model": "qwen3-8b"}, "pptx"))
    assert sw and sw["from"] == "qwen2.5:0.5b" and sw["to"] == "qwen3-8b"

    # 简单问候仍然允许用轻量模型，不强行切换
    assert asyncio.run(model_fit.maybe_escalate(
        _Body("qwen2.5:0.5b", "你好"), {"model": "qwen3-8b"}, "")) is None
