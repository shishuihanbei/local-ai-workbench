"""统一错误码：每条错误响应都要带稳定 `code`，前端据此分支而不是比中文。"""
from __future__ import annotations

import uuid

import pytest

from backend import errors
from backend.security import clear_login_fail


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def test_unauthorized_carries_code(client):
    r = client.get("/api/models")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "unauthorized"
    assert isinstance(body["detail"], str)


def test_not_found_carries_code(client):
    r = client.get("/api/definitely-not-here")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_validation_error_carries_code(client, admin_token):
    r = client.post("/api/auth/login", json={"username": "x"})  # 缺 password
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], list)


def test_bad_password_carries_code(client, admin_token):
    user = f"codes-{uuid.uuid4().hex[:8]}"
    client.post("/api/users", headers=auth(admin_token),
                json={"username": user, "password": "Temp-pass-2026", "role": "user"})
    r = client.post("/api/auth/login", json={"username": user, "password": "wrong-pass"})
    assert r.status_code == 401, r.text
    body = r.json()
    assert body["code"] == errors.INVALID_CREDENTIALS
    assert body["detail"] == "用户名或密码错误"
    clear_login_fail(user)


def test_remote_open_folder_carries_code(client, admin_token):
    r = client.post("/api/system/open-share-folder",
                    headers={**auth(admin_token), "x-forwarded-for": "8.8.8.8"})
    assert r.status_code == 403, r.text
    assert r.json()["code"] == errors.NOT_LOCAL


def test_structured_detail_keeps_shape(client, admin_token):
    """模型被占用时，`detail` 仍是对象，顶层补 `code`，老前端读法不破。"""
    from backend.services import model_usage

    model_usage.clear()
    model_usage.begin("1.5b", "someone")
    try:
        r = client.post("/api/models/select", headers=auth(admin_token), json={"key": "1.5b"})
        if r.status_code != 409:
            pytest.skip("当前没有配置本地模型，无法触发占用")
        body = r.json()
        assert body["code"] == errors.MODEL_BUSY
        assert body["detail"]["code"] == errors.MODEL_BUSY
        assert body["detail"]["message"]
    finally:
        model_usage.clear()


def test_openai_endpoint_keeps_error_envelope(client):
    r = client.get("/v1/models")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["message"]
    assert body["error"]["code"]


def test_error_body_mapping():
    from fastapi import HTTPException

    plain = HTTPException(403, "没有权限")
    body = errors.error_body(plain, 403)
    assert body == {"detail": "没有权限", "code": "forbidden"}

    explicit = errors.APIError(429, "太频繁", errors.RATE_LIMITED, extra={"retry_after": 60})
    body = errors.error_body(explicit, 429)
    assert body["code"] == errors.RATE_LIMITED
    assert body["retry_after"] == 60
