"""安装包下载：断了能续传、下回来不是 zip 要能说清楚并丢掉坏缓存。"""
from __future__ import annotations

import asyncio
import io
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from backend.services import installer, platform_deploy


def _make_zip(size_kb: int = 512) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("lib/ollama/ollama.exe", b"MZ" + b"0" * (size_kb * 1024))
        z.writestr("lib/ollama/README.txt", "便携版")
    return buf.getvalue()


class _RangeServer(BaseHTTPRequestHandler):
    """支持 Range 的小服务器，用来验证续传。"""

    protocol_version = "HTTP/1.1"
    payload = b""
    fail_first = 0  # 前 N 个请求直接断连，模拟网络抖动
    ignore_range = False  # 模拟忽略 Range、却仍回 200 + 剩余字节的 CDN

    def do_GET(self):  # noqa: N802
        cls = type(self)
        if cls.fail_first > 0:
            cls.fail_first -= 1
            self.close_connection = True
            return
        data = cls.payload
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng.split("=")[1].split("-")[0])
            body = data[start:]
            self.send_response(200 if cls.ignore_range else 206)
            if not cls.ignore_range:
                self.send_header("Content-Range", f"bytes {start}-{len(data)-1}/{len(data)}")
        else:
            body = data
            self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _RangeServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_download_writes_part_then_renames(server, tmp_path):
    _RangeServer.payload = _make_zip()
    _RangeServer.fail_first = 0
    dest = tmp_path / "ollama-windows-amd64.zip"
    asyncio.run(installer._download(server + "/pkg.zip", dest))
    assert dest.is_file() and dest.stat().st_size == len(_RangeServer.payload)
    assert not (tmp_path / "ollama-windows-amd64.zip.part").exists()
    assert installer.looks_like_zip(dest)


def test_download_resumes_from_existing_part(server, tmp_path):
    payload = _make_zip()
    _RangeServer.payload = payload
    _RangeServer.fail_first = 1
    dest = tmp_path / "pkg.zip"
    part = tmp_path / "pkg.zip.part"
    # 先放半截文件，模拟上次下到一半断了
    part.write_bytes(payload[: len(payload) // 2])
    asyncio.run(installer._download(server + "/pkg.zip", dest))
    assert dest.stat().st_size == len(payload)
    assert not part.exists()
    # 续传成功后内容必须完整
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None


def test_download_restarts_when_server_ignores_range(server, tmp_path):
    """CDN 忽略 Range 却回 200 + 剩余字节时，不能把后半段当成整个文件。"""
    payload = _make_zip()
    _RangeServer.payload = payload
    _RangeServer.fail_first = 0
    _RangeServer.ignore_range = True
    try:
        dest = tmp_path / "lmstudio.zip"
        part = tmp_path / "lmstudio.zip.part"
        part.write_bytes(payload[: len(payload) // 2])
        asyncio.run(installer._download(server + "/pkg.zip", dest))
    finally:
        _RangeServer.ignore_range = False
    assert dest.stat().st_size == len(payload)
    assert not part.exists()
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None


def test_head_hint_describes_html_page(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_text("<!DOCTYPE html><html><body>Whoa there!</body></html>", encoding="utf-8")
    assert "不是压缩包" in installer.head_hint(bad)
    assert not installer.looks_like_zip(bad)


def test_looks_like_archive_accepts_zip_and_tgz(tmp_path):
    z = tmp_path / "a.zip"
    z.write_bytes(_make_zip(1))
    assert installer.looks_like_archive(z)
    g = tmp_path / "b.tgz"
    g.write_bytes(b"\x1f\x8b\x08\x00" + b"0" * 32)
    assert installer.looks_like_archive(g)
    assert not installer.looks_like_zip(g)
    h = tmp_path / "c.tgz"
    h.write_text("<html>bad</html>", encoding="utf-8")
    assert not installer.looks_like_archive(h)


def test_check_archive_rejects_html(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_text("<html>error</html>", encoding="utf-8")
    with pytest.raises(RuntimeError) as err:
        installer._check_archive(bad)
    assert "不是 zip" in str(err.value)


def test_extract_archive_rejects_html_and_deletes_cache(tmp_path):
    bad = tmp_path / "ollama-windows-amd64.zip"
    bad.write_text("<html>rate limited</html>", encoding="utf-8")
    target = tmp_path / "platforms" / "ollama"
    with pytest.raises(RuntimeError) as err:
        platform_deploy._extract_archive(bad, target)
    assert "不是 zip" in str(err.value)
    assert not bad.exists(), "坏缓存要删掉，别让下次继续用"


def test_extract_archive_accepts_zip(tmp_path):
    arc = tmp_path / "pkg.zip"
    arc.write_bytes(_make_zip())
    target = tmp_path / "platforms" / "x"
    platform_deploy._extract_archive(arc, target)
    assert (target / "lib" / "ollama" / "ollama.exe").is_file()
