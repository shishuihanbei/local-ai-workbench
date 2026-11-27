"""pytest 公共夹具：测试使用独立临时数据目录，不碰线上 workbench.db。"""
from __future__ import annotations

import os
import tempfile

import pytest

_TEST_DATA = tempfile.mkdtemp(prefix="workbench-pytest-")
os.environ["WORKBENCH_DATA"] = _TEST_DATA
os.environ["WORKBENCH_SECRET"] = "pytest-secret-key-do-not-use-in-production"
# 平台安装目录与模型目录也必须是临时目录，否则「卸载」类用例会删到真实安装
os.environ["WORKBENCH_PLATFORMS"] = os.path.join(_TEST_DATA, "platforms")
os.environ["WORKBENCH_MODELS"] = os.path.join(_TEST_DATA, "models")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_token(client):
    r = client.post("/api/auth/setup", json={
        "username": "admin",
        "password": "Pytest-pass-2026",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}
