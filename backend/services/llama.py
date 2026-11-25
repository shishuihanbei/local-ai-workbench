"""llama.cpp 服务进程管理与模型下载。"""
from __future__ import annotations

import asyncio
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import CREATE_NO_WINDOW, IS_WINDOWS, LOG_DIR, load_config, llama_executable, model_file_path
from ..db import execute, fetch_one

LLAMA_LOG = LOG_DIR / "llama.log"
_dl_tasks: dict[str, asyncio.Task] = {}


class LlamaServer:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.model_key: str = ""
        self.started_at: float = 0.0
        self.error: str = ""
        self._out = None

    # ------------------------------------------------------------ 状态
    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    async def status(self) -> dict[str, Any]:
        cfg = load_config()
        port = int(cfg.get("upstream_port") or 8080)
        healthy = False
        served: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=2.5) as c:
                r = await c.get(f"http://127.0.0.1:{port}/v1/models",
                                headers={"Authorization": f"Bearer {cfg['upstream_key']}"})
                healthy = r.status_code == 200
                if healthy:
                    served = [m.get("id", "") for m in r.json().get("data", [])]
        except Exception:
            healthy = False
        own = self.running()
        # 兼容外部（旧面板/手工）启动的 llama-server
        external = bool(healthy and not own)
        model_name = self.model_key
        if external and served:
            model_name = served[0]
        return {
            "running": own or healthy,
            "external": external,
            "pid": self.proc.pid if own else None,
            "model": model_name,
            "uptime": round(time.time() - self.started_at, 1) if self.started_at else 0,
            "healthy": healthy,
            "served": served,
            "port": port,
            "error": self.error,
        }

    # ------------------------------------------------------------ 启停
    async def stop(self) -> None:
        if not self.proc:
            return
        proc = self.proc
        try:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            else:
                proc.send_signal(signal.SIGTERM)
                for _ in range(20):
                    if proc.poll() is not None:
                        break
                    await asyncio.sleep(0.3)
                if proc.poll() is None:
                    proc.kill()
        except Exception:
            pass
        self.proc = None
        self.model_key = ""
        self.started_at = 0.0

    async def start(self, key: str) -> tuple[bool, str]:
        cfg = load_config()
        row = await fetch_one("SELECT * FROM models WHERE key=?", (key,))
        if not row:
            return False, "未知模型"
        path = model_file_path(cfg, row["filename"])
        expected = int(row["total_bytes"] or 0)
        if not path.exists():
            return False, "模型文件不存在，请先下载"
        size = path.stat().st_size
        if expected and size + 1024 < expected:
            return False, f"模型未下载完整（{size/2**30:.2f}/{expected/2**30:.2f} GB）"
        exe = llama_executable(cfg)
        if not exe:
            return False, "未找到 llama-server 可执行文件，请在设置里配置 llama 目录"

        if not self.running():
            try:
                async with httpx.AsyncClient(timeout=2) as c:
                    r = await c.get(f"http://127.0.0.1:{int(cfg.get('upstream_port') or 8080)}/v1/models",
                                    headers={"Authorization": f"Bearer {cfg.get('upstream_key')}"})
                    if r.status_code == 200:
                        return False, "该端口已被另一个 llama-server 占用（可能是旧面板），请先停止它再加载"
            except Exception:
                pass

        await self.stop()
        port = int(cfg.get("upstream_port") or 8080)
        cmd = [
            str(exe), "-m", str(path),
            "--host", "127.0.0.1", "--port", str(port),
            "-c", str(cfg.get("ctx") or 8192),
            "-t", str(cfg.get("threads") or 6),
            "-ngl", str(cfg.get("gpu_layers") or 0),
            "--api-key", str(cfg.get("upstream_key") or ""),
        ]
        LLAMA_LOG.parent.mkdir(parents=True, exist_ok=True)
        self._out = open(LLAMA_LOG, "ab", buffering=0)
        self._out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start {key} ===\n".encode())
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(exe.parent), stdout=self._out, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            self.error = str(e)
            return False, f"启动失败：{e}"

        self.model_key = key
        self.started_at = time.time()
        self.error = ""
        cfg["model"] = key
        cfg["local_enabled"] = True
        from ..config import save_config
        save_config(cfg)
        await execute(
            "INSERT INTO audit_logs(ts,username,action,target,detail,status) VALUES(?,?,?,?,?,?)",
            (time.time(), "system", "model.load", key, f"pid={self.proc.pid}", "ok"))

        # 等待端口就绪（最多 90 秒）
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False, "进程已退出，请查看 llama 日志"
            try:
                async with httpx.AsyncClient(timeout=2) as c:
                    r = await c.get(f"http://127.0.0.1:{port}/health")
                    if r.status_code == 200:
                        return True, f"已加载 {row['label']}"
            except Exception:
                pass
            await asyncio.sleep(1.5)
        return True, "模型仍在加载，稍后自动可用"

    async def restore(self) -> tuple[bool, str]:
        """启动时恢复上次使用的本地模型（不阻塞服务就绪）。"""
        cfg = load_config()
        key = str(cfg.get("model") or "").strip()
        if not key or not bool(cfg.get("local_enabled", True)):
            return False, ""
        row = await fetch_one("SELECT * FROM models WHERE key=?", (key,))
        if not row or not int(row.get("installable", 1)):
            return False, "上次使用的模型不在可加载清单中"
        path = model_file_path(cfg, row["filename"])
        if not path.exists():
            return False, "上次使用的模型文件不存在"
        expected = int(row["total_bytes"] or 0)
        if expected and path.stat().st_size + 1024 < expected:
            return False, "上次使用的模型未下载完整"
        status = await self.status()
        if status.get("healthy") and status.get("model") in (key, row.get("alias") or ""):
            return True, "模型服务已在运行"
        if status.get("healthy"):
            return False, "端口已被另一个模型服务占用，未自动切换"
        return await self.start(key)

    async def switch_to_model_name(self, name: str) -> tuple[bool, str]:
        """外部请求带来模型名（OpenAI 兼容调用），必要时切换。"""
        if not name:
            return True, ""
        row = await fetch_one("SELECT key FROM models WHERE key=? OR label=? OR filename LIKE ?",
                              (name, name, f"%{name}%"))
        if not row:
            return True, ""
        if self.model_key == row["key"]:
            return True, ""
        return await self.start(row["key"])


server = LlamaServer()


# ---------------------------------------------------------------- 下载
async def download_model(key: str, url: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    row = await fetch_one("SELECT * FROM models WHERE key=?", (key,))
    if not row:
        return {"ok": False, "msg": "未知模型"}
    from ..db import model_url
    url = url or model_url(row["repo"] or "", row["filename"])
    target = model_file_path(cfg, row["filename"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if key in _dl_tasks and not _dl_tasks[key].done():
        return {"ok": False, "msg": "该模型正在下载中"}

    download_id = await execute(
        "INSERT INTO downloads(model_key,url,status,bytes,total,started_at) VALUES(?,?,?,?,?,?)",
        (key, url, "running", 0, row["total_bytes"], time.time()))

    async def _run() -> None:
        part = target.with_suffix(target.suffix + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c:
                async with c.stream("GET", url, headers=headers) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    total = int(r.headers.get("content-length") or 0) + (have if r.status_code == 206 else 0)
                    if r.status_code == 200:
                        have = 0
                    with open(part, "ab") as f:
                        last = 0.0
                        async for chunk in r.aiter_bytes(1024 * 256):
                            f.write(chunk)
                            have += len(chunk)
                            if time.time() - last > 1.2:
                                last = time.time()
                                await execute("UPDATE downloads SET bytes=?, total=? WHERE id=?",
                                              (have, total, download_id))
            part.replace(target)
            await execute("UPDATE downloads SET status='done', bytes=?, total=?, finished_at=? WHERE id=?",
                          (have, have, time.time(), download_id))
        except Exception as e:
            await execute("UPDATE downloads SET status='error', error=?, finished_at=? WHERE id=?",
                          (str(e)[:300], time.time(), download_id))

    _dl_tasks[key] = asyncio.create_task(_run())
    return {"ok": True, "msg": "已加入下载队列", "id": download_id}


async def download_progress(key: str) -> dict[str, Any]:
    cfg = load_config()
    row = await fetch_one("SELECT * FROM models WHERE key=?", (key,))
    if not row:
        return {}
    path = model_file_path(cfg, row["filename"])
    part = path.with_suffix(path.suffix + ".part")
    size = path.stat().st_size if path.exists() else (part.stat().st_size if part.exists() else 0)
    expected = int(row["total_bytes"] or 0)
    last = await fetch_one("SELECT * FROM downloads WHERE model_key=? ORDER BY id DESC LIMIT 1", (key,))
    active = key in _dl_tasks and not _dl_tasks[key].done()
    return {
        "bytes": size, "total": expected,
        "pct": round(size * 100 / expected, 1) if expected else 0,
        "status": "running" if active else (last["status"] if last else ("done" if path.exists() else "none")),
        "speed": 0, "error": (last or {}).get("error") or "",
        "exists": path.exists(),
    }


def llama_log_tail(lines: int = 120) -> list[str]:
    if not LLAMA_LOG.exists():
        return []
    data = LLAMA_LOG.read_bytes()
    text = data.decode("utf-8", "replace")
    return text.splitlines()[-lines:]
