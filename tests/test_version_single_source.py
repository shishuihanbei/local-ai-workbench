"""版本号单一来源：所有对外暴露的版本必须与 backend.version.VERSION 一致。

背景：之前 `main.py`、`/api/health`、前端资源 query、备份清单、导库元数据各自
写死版本（0.8.1 / 0.8.2.6 / 0.7.73），线上跑的是哪版无法判断。
"""
from __future__ import annotations

from backend import version as version_mod


def test_version_constant_shape():
    assert version_mod.VERSION.count(".") == 3, "版本号用 主.次.补丁.构建 四段"
    assert all(part.isdigit() for part in version_mod.VERSION.split("."))


def test_health_reports_single_version(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["version"] == version_mod.VERSION
    assert r.headers["X-API-Version"] == version_mod.VERSION


def test_meta_reports_single_version(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == version_mod.VERSION
    assert body["name"]


def test_backup_manifest_uses_single_version():
    from backend.services import backup

    assert backup.APP_VERSION == version_mod.VERSION


def test_openapi_version_matches(client):
    spec = client.get("/api/openapi.json").json()
    assert spec["info"]["version"] == version_mod.VERSION
