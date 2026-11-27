"""内网穿透：cloudflared 临时通道 / 令牌固定域名。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import BASE_DIR, CREATE_NO_WINDOW, DATA_DIR, IS_WINDOWS, load_config
from . import platform_store

LOG = DATA_DIR / "logs" / "tunnel.log"
URL_RE = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")
CLOUDFLARED_NAME = "cloudflared.exe" if IS_WINDOWS else "cloudflared"


def cloudflared_dir(cfg: dict[str, Any] | None = None) -> Path:
    """和四个引擎一样落在 platforms 下，整包搬走时只动工作台一个目录。"""
    return platform_store.target(cfg or load_config(), "cloudflared")


def cloudflared_dest(cfg: dict[str, Any] | None = None) -> Path:
    return cloudflared_dir(cfg) / CLOUDFLARED_NAME


def _legacy_cloudflared_paths() -> list[Path]:
    """旧版本把 cloudflared 放在程序目录旁边（D:\\AI\\cloudflared），升级时收回来。"""
    return [BASE_DIR.parent / "cloudflared" / CLOUDFLARED_NAME,
            BASE_DIR.parent / "cloudflared" / "cloudflared"]


def ensure_cloudflared_layout(cfg: dict[str, Any] | None = None) -> Path | None:
    """把旧版本下载在工作台外面的 cloudflared 搬进 platforms/cloudflared。

    不覆盖已经在新位置的文件；旧目录空了才删，绝不碰其它文件。
    """
    cfg = cfg or load_config()
    dest = cloudflared_dest(cfg)
    if dest.is_file():
        return dest
    for old in _legacy_cloudflared_paths():
        if not old.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(old), str(dest))
        except Exception:
            try:
                shutil.copy2(old, dest)
                old.unlink(missing_ok=True)
            except Exception:
                return dest if dest.is_file() else None
        try:
            old.parent.rmdir()          # 只在已经空了的时候成功
        except Exception:
            pass
        return dest
    return None


def find_cloudflared() -> Path | None:
    dest = cloudflared_dest()
    if dest.is_file():
        return dest
    ensure_cloudflared_layout()
    if dest.is_file():
        return dest
    for cand in (cloudflared_dir() / "cloudflared",
                 Path("/usr/local/bin/cloudflared"), Path("/usr/bin/cloudflared")):
        if cand.exists():
            return cand
    exe = shutil.which("cloudflared")
    return Path(exe) if exe else None


class Tunnel:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.url: str = ""
        self.mode: str = ""
        self.target: str = ""
        self.started_at: float = 0.0
        self.error: str = ""
        self.ready: bool = False
        self.log_pos: int = 0

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def resolve_target(self) -> tuple[str, int]:
        cfg = load_config()
        target = cfg.get("tunnel_target") or "panel"
        port = 0
        if target == "api":
            port = int(cfg.get("upstream_port") or 8080)
            return f"http://127.0.0.1:{port}", port
        if target == "frontend":
            if cfg.get("serve_frontend", True):
                port = int(cfg.get("port") or 9100)
                return f"http://127.0.0.1:{port}", port
            front = str(cfg.get("frontend_url") or "").strip()
            if front:
                try:
                    parsed = urlsplit(front)
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                except Exception:
                    port = 0
                if port:
                    return f"http://127.0.0.1:{port}", port
            target = "panel"
        port = int(cfg.get("port") or 9100)
        return f"http://127.0.0.1:{port}", port

    def _failed_hint(self) -> str:
        """从本次日志里提炼可读原因，避免前端只显示“未开启”。"""
        seg = self._segment()
        if "status 429" in seg or "quick tunnel provisioning failed" in seg:
            return ("Cloudflare 免费临时隧道申请被限流（HTTP 429）。当前网络出口近期申请过多，"
                    "请稍后再试，或改用“固定域名 + 隧道 Token”。")
        plain = re.sub(r"\x1b\[[0-9;]*m", "", seg)
        if "critical failures" in plain:
            return ("Cloudflare 连通性预检未通过：当前网络可能拦了 7844/UDP 或 TCP，"
                    "请换网络/关闭代理后再试，或改用固定域名 Token。")
        lines = [x.strip(" |") for x in plain.splitlines() if x.strip()]
        for line in reversed(lines[-12:]):
            low = line.lower()
            if " err " in low or "failed" in low or "error" in low:
                return line[-300:]
        if "start " in seg and not URL_RE.findall(seg):
            return "穿透进程已退出，但没有拿到公网地址。可展开连接日志查看详细原因。"
        return ""

    def start(self, mode: str = "quick", token: str = "") -> tuple[bool, str]:
        if self.running():
            return True, "穿透已在运行"
        exe = find_cloudflared()
        if not exe:
            return False, "未找到 cloudflared，请先下载（设置页提供一键下载）"
        if mode == "token":
            token = token or str(load_config().get("tunnel_token") or "")
            if not token:
                return False, "缺少隧道令牌"
            cmd = [str(exe), "tunnel", "--no-autoupdate", "run", "--token", token]
            target, port = "token", 0
        else:
            url, port = self.resolve_target()
            cmd = [str(exe), "tunnel", "--no-autoupdate", "--url", url]
            target = url
        LOG.parent.mkdir(parents=True, exist_ok=True)
        self.log_pos = LOG.stat().st_size if LOG.exists() else 0
        self.ready = False
        out = open(LOG, "ab", buffering=0)
        out.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start {mode} ===\n".encode())
        try:
            self.proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            self.error = str(e)
            return False, f"启动失败：{e}"
        self.mode, self.target, self.url = mode, target, ""
        self.started_at = time.time()
        self.error = ""

        # Cloudflare 的限流/预检失败通常 1–3 秒内就退出，先等一下把真实原因返回给前端。
        for _ in range(8):
            time.sleep(0.3)
            if not self.running():
                self.error = self._failed_hint() or "穿透进程启动后立即退出，请查看连接日志。"
                return False, self.error

        def _watch() -> None:
            for _ in range(60):
                time.sleep(1)
                if not self.running():
                    if not self.error:
                        self.error = self._failed_hint()
                    return
                found = self.scan_url()
                if found:
                    self.url = found
                    return
            if self.running() and not self.url and not self.error:
                self.error = "60 秒内未拿到公网地址，请展开连接日志检查网络。"

        threading.Thread(target=_watch, daemon=True).start()
        return True, "穿透已启动，正在获取公网地址"

    def _segment(self) -> str:
        """只读取本次启动之后的日志，避免把上一次的旧地址当成当前地址。"""
        if not LOG.exists():
            return ""
        try:
            return LOG.read_text("utf-8", "replace")[self.log_pos:]
        except Exception:
            return ""

    def scan_url(self) -> str:
        text = self._segment()
        urls = URL_RE.findall(text)
        return urls[-1] if urls else ""

    def stop(self) -> None:
        if not self.proc:
            self.error = ""
            self.url = ""
            self.mode = ""
            self.ready = False
            return
        try:
            if IS_WINDOWS:
                killer = shutil.which("taskkill") or str(
                    Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe")
                subprocess.run([killer, "/PID", str(self.proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
            else:
                self.proc.terminate()
                try:
                    self.proc.wait(10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        self.proc = None
        self.url = ""
        self.mode = ""
        self.ready = False
        self.error = ""
        self.started_at = 0.0

    def status(self) -> dict[str, Any]:
        cfg = load_config()
        if self.running():
            seg = self._segment()
            if "Registered tunnel connection" in seg:
                self.ready = True
            if not self.url and self.mode == "token":
                domain = str(cfg.get("tunnel_domain") or "").strip()
                if domain:
                    self.url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
            if not self.url:
                urls = URL_RE.findall(seg)
                if urls:
                    self.url = urls[-1]
        elif self.started_at and not self.error:
            self.error = self._failed_hint()
        target, port = self.resolve_target()
        target_mode = cfg.get("tunnel_target") or "panel"
        if target_mode not in ("panel", "api", "frontend"):
            target_mode = "panel"
        return {
            "running": self.running(),
            "ready": self.ready,
            "url": self.url,
            "mode": self.mode,
            "target": self.target or target,
            "target_mode": target_mode,
            "port": port,
            "frontend_url": cfg.get("frontend_url") or "",
            "tunnel_domain": cfg.get("tunnel_domain") or "",
            "uptime": round(time.time() - self.started_at, 1) if self.started_at else 0,
            "error": self.error,
            "binary": str(find_cloudflared() or ""),
        }


tunnel = Tunnel()


async def download_cloudflared() -> dict[str, Any]:
    dest = cloudflared_dest()
    if IS_WINDOWS:
        url = ("https://gh-proxy.com/https://github.com/cloudflare/cloudflared/"
               "releases/latest/download/cloudflared-windows-amd64.exe")
    else:
        url = ("https://gh-proxy.com/https://github.com/cloudflare/cloudflared/"
               "releases/latest/download/cloudflared-linux-amd64")
    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=None, follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            if r.status_code != 200:
                return {"ok": False, "msg": f"下载失败 HTTP {r.status_code}"}
            tmp = dest.with_name(dest.name + ".part")
            with open(tmp, "wb") as f:
                async for chunk in r.aiter_bytes(1024 * 512):
                    f.write(chunk)
    tmp.replace(dest)
    if not IS_WINDOWS:
        os.chmod(dest, 0o755)
    return {"ok": True, "msg": f"已下载到 {dest}"}
