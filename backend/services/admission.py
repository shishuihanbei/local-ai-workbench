"""聊天生成准入控制：全局并发上限 + 单账号每分钟限流。

面向局域网多人同时使用：
- 全局信号量限制同时进行的生成数，超出的请求先排队等待，避免把模型/线程池打满；
- 按账号做滑动窗口限流，防止一个人刷屏挤占名额；
- 排队等待超过阈值直接拒绝，让前端提示稍后再试，而不是无限挂着。
"""
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any


class AdmissionRejected(Exception):
    """准入被拒绝：status 用 429，extra 带当前排队/在跑数量。"""

    def __init__(self, status: int, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra or {}


class _Token:
    __slots__ = ("_adm",)

    def __init__(self, adm: "ChatAdmission"):
        self._adm = adm

    async def release(self) -> None:
        await self._adm.leave()


class ChatAdmission:
    def __init__(self, max_active: int = 4, rpm: int = 30, queue_timeout: float = 30.0):
        self._sem = asyncio.Semaphore(max(1, max_active))
        self._lock = asyncio.Lock()
        self._active = 0
        self._waiting = 0
        self._windows: dict[str, deque[float]] = {}
        self.max_active = max_active
        self.rpm = rpm
        self.queue_timeout = queue_timeout

    def snapshot(self) -> dict[str, Any]:
        return {"active": self._active, "waiting": self._waiting,
                "max_active": self.max_active, "rpm": self.rpm}

    async def enter(self, key: str) -> _Token:
        now = time.time()
        async with self._lock:
            window = self._windows.setdefault(key, deque())
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.rpm:
                raise AdmissionRejected(
                    429, f"发送太频繁：每账号每分钟最多 {self.rpm} 条，请稍后再试",
                    self.snapshot())
            window.append(now)
            self._waiting += 1

        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self.queue_timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                self._waiting -= 1
            raise AdmissionRejected(
                429, "当前使用人数较多，请稍等片刻后再发送", self.snapshot())
        except BaseException:
            async with self._lock:
                self._waiting -= 1
            raise

        async with self._lock:
            self._waiting -= 1
            self._active += 1
        return _Token(self)

    async def leave(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)
        self._sem.release()


_admission: ChatAdmission | None = None


def get_admission() -> ChatAdmission:
    global _admission
    if _admission is None:
        from ..config import load_config
        cfg = load_config()
        max_active = int(os.getenv("WORKBENCH_CHAT_MAX_ACTIVE") or cfg.get("chat_max_active") or 4)
        rpm = int(os.getenv("WORKBENCH_CHAT_RPM") or cfg.get("chat_rpm") or 30)
        _admission = ChatAdmission(max_active=max_active, rpm=rpm)
    return _admission


def reset_for_tests() -> None:
    """测试之间重置单例计数。"""
    global _admission
    _admission = None
