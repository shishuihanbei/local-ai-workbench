"""一键部署要能取消：下载停在分片、安装子进程被结束、状态显示已取消。"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.services import installer, platform_deploy


class _SlowServer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    payload = b"x" * (4 * 1024 * 1024)

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        for i in range(0, len(self.payload), 256 * 1024):
            self.wfile.write(self.payload[i:i + 256 * 1024])
            self.wfile.flush()
            time.sleep(0.05)
        self.close_connection = True

    def log_message(self, *a):
        pass


def test_download_cancel_keeps_part(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _SlowServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        dest = tmp_path / "pkg.zip"
        calls = {"n": 0}

        def should_cancel():
            calls["n"] += 1
            return calls["n"] > 2

        with pytest.raises(installer.DownloadCancelled):
            asyncio.run(installer._download(f"http://127.0.0.1:{srv.server_address[1]}/x", dest,
                                            should_cancel=should_cancel))
        part = dest.with_name(dest.name + ".part")
        assert part.exists() and part.stat().st_size > 0
        assert not dest.exists(), "取消不该把半截文件改名成正式包"
    finally:
        srv.shutdown()


def test_run_cancel_kills_process():
    platform_deploy.STATE.clear()
    platform_deploy._state("t")
    key = "t"
    platform_deploy.STATE[key].update({"running": True, "cancel": False})

    code = "import time; time.sleep(30)"
    out: dict = {}

    def worker():
        try:
            platform_deploy._run(key, [sys.executable, "-c", code], idle_label="假安装")
        except Exception as exc:  # noqa: BLE001
            out["exc"] = exc

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    time.sleep(1.0)
    r = platform_deploy.request_cancel(key)
    assert r["ok"] is True
    th.join(timeout=10)
    assert not th.is_alive(), "取消后子进程应该被杀掉"
    assert isinstance(out.get("exc"), platform_deploy.DeployCancelled)


def test_deploy_marks_cancelled(monkeypatch):
    platform_deploy.STATE.clear()

    async def slow(key, endpoint="", force=False):
        for _ in range(40):
            if platform_deploy._state(key).get("cancel"):
                raise platform_deploy.DeployCancelled("部署已取消")
            await asyncio.sleep(0.1)
        return True, "完成", False

    monkeypatch.setattr(platform_deploy, "_deploy_ollama", slow)

    async def go():
        task = asyncio.create_task(platform_deploy.deploy("ollama"))
        await asyncio.sleep(0.3)
        res = platform_deploy.request_cancel("ollama")
        assert res["ok"] is True
        out = await task
        return out

    out = asyncio.run(go())
    assert out["ok"] is False and out.get("cancelled") is True
    st = platform_deploy.get_state("ollama")
    assert st["running"] is False and st["step"] == "已取消"
    assert st["cancelled"] is True
    assert "保留" in st["msg"]


def test_cancel_when_idle_reports_noop():
    platform_deploy.STATE.clear()
    r = platform_deploy.request_cancel("lmstudio")
    assert r["ok"] is False and "没有在部署" in r["msg"]
