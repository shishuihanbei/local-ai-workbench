"""统一错误码。

目标：前端能按 `code` 分支处理，而不是靠比对中文文案。

约定：
- HTTP 响应体至少包含 `code`；同时保留 `detail` 作为人类可读中文消息（前端直接显示）。
- 已有的结构化错误（如模型切换占用）保持原样 body，不再多包一层，由全局处理器补齐 `code`。
- 没有显式指定 `code` 的 338 处 `HTTPException` 也能拿到稳定码，靠的是状态码默认映射。

新增错误时优先：

    raise APIError(429, "每分钟最多 20 条", "rate_limited", retry_after=60)

`extra` 里的键会平铺进响应体（`retry_after` 等），供前端做倒计时。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# 状态码 -> 默认错误码。改动这里等于改所有未显式指定 code 的接口契约。
DEFAULT_CODE_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    501: "not_implemented",
    502: "upstream_error",
    503: "service_unavailable",
}

# 业务里需要前端特殊处理的码，集中列出来避免拼写漂移。
INVALID_CREDENTIALS = "invalid_credentials"
ACCOUNT_LOCKED = "account_locked"
ACCOUNT_DISABLED = "account_disabled"
REGISTER_CLOSED = "register_closed"
RATE_LIMITED = "rate_limited"
QUOTA_EXCEEDED = "quota_exceeded"
MODEL_BUSY = "model_busy"
MODEL_NOT_ALLOWED = "model_not_allowed"
INVALID_API_KEY = "invalid_api_key"
CONFIRM_REQUIRED = "confirm_required"
NOT_LOCAL = "not_local"


class APIError(HTTPException):
    """带错误码的 HTTPException。

    - `message` 仍走 `detail`，保证旧前端照常显示中文。
    - `code` 供前端分支与日志统计。
    - `extra` 平铺进响应体，供前端结构化处理（如 `retry_after`、`items`）。
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        code: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, message, headers=headers)
        self.code = code or DEFAULT_CODE_BY_STATUS.get(status_code, "error")
        self.extra = dict(extra or {})


def error(
    status_code: int,
    message: str,
    code: str | None = None,
    *,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> APIError:
    """构造错误对象，便于 `raise error(...)` 写法。"""
    return APIError(status_code, message, code, extra=extra, headers=headers)


def error_body(exc: Exception, status_code: int) -> dict[str, Any]:
    """把异常转成响应体。全局处理器与测试共用，避免两套规则。"""
    detail = getattr(exc, "detail", None)
    code = getattr(exc, "code", None)
    extra = getattr(exc, "extra", None) or {}

    if isinstance(detail, dict):
        # 已经结构化的错误（如模型占用）保持 `detail` 原对象不变：老前端读
        # `data.detail.message` / `data.detail.code` 的写法继续有效，这里只在
        # 顶层补一个同样的 `code`，方便按码分支和统计。
        body: dict[str, Any] = {"detail": dict(detail)}
        body["code"] = code or detail.get("code") or DEFAULT_CODE_BY_STATUS.get(status_code, "error")
        for key, value in extra.items():
            body.setdefault(key, value)
        return body

    body: dict[str, Any] = {"detail": detail}
    body["code"] = code or DEFAULT_CODE_BY_STATUS.get(status_code, "error")
    for key, value in extra.items():
        body.setdefault(key, value)
    return body
