"""模型下载状态回归：列表与进度接口必须如实反映下载中 / 中断。

背景：下载任务只在进程内（llama._dl_tasks），进程重启后 downloads 表会留下
status='running' 的僵尸记录，界面如果只看文件大小，就会一直显示「下载」按钮，
点了也没有任何变化。
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from backend.config import DB_PATH


@pytest.fixture
def empty_models_dir(tmp_path, monkeypatch):
    """把模型目录指到空目录，避免真实模型文件让「已下载」判定干扰断言。"""
    from backend import config as cfgmod
    from backend.routers import models as models_router

    real = dict(cfgmod.load_config())
    real["models_dir"] = str(tmp_path)
    monkeypatch.setattr(models_router, "load_config", lambda: dict(real))
    return tmp_path


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _insert_download(key: str, status: str, size: int, total: int) -> int:
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(
            "INSERT INTO downloads(model_key,url,status,bytes,total,started_at) "
            "VALUES(?,?,?,?,?,?)",
            (key, "test://fixture", status, size, total, time.time()))
        con.commit()
        return int(cur.lastrowid)
    finally:
        con.close()


def _drop(ids: list[int]) -> None:
    con = sqlite3.connect(DB_PATH)
    try:
        for row_id in ids:
            con.execute("DELETE FROM downloads WHERE id=?", (row_id,))
        con.commit()
    finally:
        con.close()


def _model(client, token: str, key: str) -> dict:
    r = client.get("/api/models", headers=auth(token))
    assert r.status_code == 200, r.text
    for item in r.json()["items"]:
        if item["key"] == key:
            return item
    raise AssertionError(f"清单里没有 {key}")


def test_stale_running_record_reports_interrupted(client, admin_token, empty_models_dir):
    key = "qwen3-8b"
    row_id = _insert_download(key, "running", 381943808, 5027782720)
    try:
        item = _model(client, admin_token, key)
        dl = item["download"]
        assert dl["state"] == "interrupted", dl
        assert dl["total"] >= 0
        assert item["pct"] >= 0

        p = client.get(f"/api/models/{key}/progress", headers=auth(admin_token))
        assert p.status_code == 200, p.text
        assert p.json()["status"] == "interrupted", p.text
    finally:
        _drop([row_id])


def test_live_task_reports_running(client, admin_token, monkeypatch, empty_models_dir):
    from backend.services import llama

    key = "qwen3-8b"
    row_id = _insert_download(key, "running", 381943808, 5027782720)
    monkeypatch.setattr(llama, "download_active", lambda k: True)
    try:
        assert _model(client, admin_token, key)["download"]["state"] == "running"
        p = client.get(f"/api/models/{key}/progress", headers=auth(admin_token))
        assert p.json()["status"] == "running", p.text
    finally:
        _drop([row_id])


def test_failed_download_is_visible(client, admin_token, empty_models_dir):
    key = "qwen3-8b"
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.execute(
            "INSERT INTO downloads(model_key,url,status,bytes,total,error,started_at,finished_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (key, "test://fixture", "error", 100, 200, "HTTP 403", time.time(), time.time()))
        con.commit()
        row_id = int(cur.lastrowid)
    finally:
        con.close()
    try:
        item = _model(client, admin_token, key)
        assert item["download"]["state"] == "error", item["download"]
        assert "403" in item["download"]["error"]
    finally:
        _drop([row_id])
