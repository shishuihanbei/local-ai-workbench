"""开机自启：一键把当前这份程序注册成登录/开机自动启动。

只做「当前用户、当前目录、当前端口」这一件事，不碰系统级服务配置以外的内容：
- Windows：写入当前用户的「启动」文件夹，生成一个隐藏窗口的 .cmd 启动器；
- Linux：优先写 systemd 单元（root 走系统级，普通用户走用户级并尝试 enable-linger）；
  没有 systemd 时退回 crontab @reboot；
- macOS：写 ~/Library/LaunchAgents 下的 LaunchAgent；
- 容器内不提供，提示用 restart: unless-stopped。

所有路径都取自 BASE_DIR 与配置，端口只接受整数，不接受外部传入的命令。
"""
from __future__ import annotations

import getpass
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import BASE_DIR, CREATE_NO_WINDOW, DATA_DIR, load_config

WIN_STARTUP_FILE = "LocalAI-Workbench.cmd"
SYSTEMD_NAME = "local-ai-workbench.service"
LAUNCHD_LABEL = "com.local-ai-workbench"
CRON_MARK = "# local-ai-workbench autostart"


# ------------------------------------------------------------------ 基础信息
def _port() -> int:
    raw = os.getenv("WORKBENCH_PORT") or load_config().get("port") or 9100
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 9100


def _host() -> str:
    return str(load_config().get("host") or "0.0.0.0")


def _in_docker() -> bool:
    return Path("/.dockerenv").exists() or str(os.getenv("WORKBENCH_IN_DOCKER") or "").lower() in ("1", "true", "yes")


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _platform() -> str:
    if _in_docker():
        return "docker"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


# ------------------------------------------------------------------ Windows
def _win_startup_dir() -> Path:
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _win_launcher(root: Path, port: int) -> str:
    ps1 = root / "start.ps1"
    if ps1.exists():
        command = (f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                   f'-File "{ps1}" -NoBrowser -Port {port}')
    else:
        pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
        command = f'"{pythonw}" "{root / "run.py"}" --host 0.0.0.0 --port {port}'
    return (
        "@echo off\r\n"
        'set "PYTHONUTF8=1"\r\n'
        'set "WORKBENCH_SERVE_FRONTEND=1"\r\n'
        f'start "" {command}\r\n'
        "exit\r\n"
    )


def _win_path() -> Path:
    return _win_startup_dir() / WIN_STARTUP_FILE


# ------------------------------------------------------------------ Linux
def _linux_has_systemd() -> bool:
    return bool(shutil.which("systemctl")) and Path("/run/systemd/system").exists()


def _linux_unit(root: Path, port: int, as_root: bool) -> str:
    user_line = "" if as_root else f"User={getpass.getuser()}\n"
    return (
        "[Unit]\n"
        "Description=Local AI Workbench\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"{user_line}"
        f"WorkingDirectory={root}\n"
        "Environment=PYTHONUTF8=1\n"
        f"Environment=WORKBENCH_DATA={DATA_DIR}\n"
        "Environment=WORKBENCH_SERVE_FRONTEND=1\n"
        f"ExecStart={root / '.venv/bin/python'} {root / 'run.py'} --host 0.0.0.0 --port {port}\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "TimeoutStopSec=20\n"
        "KillSignal=SIGINT\n\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectSystem=full\n"
        f"ReadWritePaths={DATA_DIR} {root / 'models'} {root / 'llama'}\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _linux_unit_path(as_root: bool) -> Path:
    if as_root:
        return Path("/etc/systemd/system") / SYSTEMD_NAME
    return Path.home() / ".config" / "systemd" / "user" / SYSTEMD_NAME


def _cron_has_entry() -> bool:
    code, out = _run(["crontab", "-l"])
    return CRON_MARK in out


def _cron_set(on: bool, root: Path, port: int) -> tuple[bool, str]:
    if not shutil.which("crontab"):
        return False, "系统里没有 crontab，无法设置自启"
    code, current = _run(["crontab", "-l"])
    lines = [] if code != 0 else [x for x in current.splitlines()]
    cleaned = [x for x in lines if CRON_MARK not in x and "run.py --port" not in x]
    if on:
        log = DATA_DIR / "logs" / "write.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        py = root / ".venv/bin/python"
        cmd = f"cd {root} && nohup {py} {root / 'run.py'} --host 0.0.0.0 --port {port} >> {log} 2>&1 &"
        cleaned.append(f"@reboot {cmd} {CRON_MARK}")
    payload = "\n".join(cleaned) + ("\n" if cleaned else "")
    try:
        p = subprocess.run(["crontab", "-"], input=payload, text=True, capture_output=True, timeout=20)
        return (p.returncode == 0), (p.stderr or p.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ------------------------------------------------------------------ macOS
def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def _mac_plist(root: Path, port: int) -> dict:
    logs = DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LAUNCHD_LABEL,
        "ProgramArguments": [
            str(root / ".venv/bin/python"),
            str(root / "run.py"),
            "--host", "0.0.0.0",
            "--port", str(port),
        ],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": {
            "PYTHONUTF8": "1",
            "WORKBENCH_DATA": str(DATA_DIR),
            "WORKBENCH_SERVE_FRONTEND": "1",
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(logs / "launchd.out"),
        "StandardErrorPath": str(logs / "launchd.err"),
    }


def _mac_domain() -> str:
    return f"gui/{os.getuid()}"


# ------------------------------------------------------------------ 状态
def _base_status() -> dict:
    return {"platform": _platform(), "supported": False, "enabled": False,
            "mechanism": "", "path": "", "port": _port(), "stale": False, "message": ""}


def status() -> dict:
    st = _base_status()
    plat = st["platform"]
    if plat == "docker":
        st["message"] = "容器内不需要开机自启，docker-compose 已设置 restart: unless-stopped，重启容器会自动拉起。"
        return st
    root = BASE_DIR
    if plat == "windows":
        st["mechanism"] = "startup-folder"
        target = _win_path()
        st["path"] = str(target)
        st["supported"] = True
        if target.exists():
            st["enabled"] = True
            try:
                text = target.read_text("utf-8", errors="ignore")
            except Exception:
                text = ""
            if str(root) not in text:
                st["stale"] = True
                st["message"] = "启动项指向的是旧目录，点“开启开机自启”会重新写入当前目录。"
            else:
                st["message"] = "已开启：登录 Windows 后自动在后台启动，不弹浏览器。"
        else:
            st["message"] = "未开启：点一下按钮就会写入当前用户的启动项，不需要任务计划程序。"
        return st
    if plat == "linux":
        if _linux_has_systemd():
            as_root = os.geteuid() == 0
            st["mechanism"] = "systemd" if as_root else "systemd-user"
            target = _linux_unit_path(as_root)
            st["path"] = str(target)
            st["supported"] = True
            if target.exists():
                code, out = _run(["systemctl"] + ([] if as_root else ["--user"]) + ["is-enabled", SYSTEMD_NAME])
                st["enabled"] = code == 0 and "enabled" in out
                st["message"] = ("已开启：systemd 会在开机时自动启动。" if st["enabled"]
                                 else "检测到服务文件但未启用，点按钮会重新启用。")
            else:
                st["message"] = "未开启：点一下按钮会写入 systemd 单元并启用，不需要手动敲 systemctl。"
            return st
        st["mechanism"] = "cron"
        st["supported"] = bool(shutil.which("crontab"))
        st["path"] = "crontab"
        st["enabled"] = _cron_has_entry()
        st["message"] = ("已开启：通过 crontab @reboot 启动。" if st["enabled"]
                         else "未开启：当前系统没有 systemd，点按钮会写 crontab @reboot。")
        return st
    if plat == "macos":
        st["mechanism"] = "launchd"
        target = _mac_plist_path()
        st["path"] = str(target)
        st["supported"] = shutil.which("launchctl") is not None
        if target.exists():
            code, _ = _run(["launchctl", "print", f"{_mac_domain()}/{LAUNCHD_LABEL}"])
            st["enabled"] = code == 0
            st["message"] = ("已开启：登录 macOS 后由 launchd 自动启动。" if st["enabled"]
                             else "已写入 LaunchAgent 但未加载，点按钮会重新加载。")
        else:
            st["message"] = "未开启：点一下按钮会安装 LaunchAgent，不需要手动编辑 plist。"
        return st
    st["message"] = "当前系统不支持一键开机自启。"
    return st


# ------------------------------------------------------------------ 开启 / 关闭
def enable() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    root = BASE_DIR
    port = st["port"]
    plat = st["platform"]
    if plat == "windows":
        startup = _win_startup_dir()
        try:
            startup.mkdir(parents=True, exist_ok=True)
            target = _win_path()
            target.write_text(_win_launcher(root, port), "utf-8", newline="")
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"写入启动项失败：{exc}"}
    elif plat == "linux":
        if st["mechanism"] in ("systemd", "systemd-user"):
            target = _linux_unit_path(st["mechanism"] == "systemd")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(_linux_unit(root, port, st["mechanism"] == "systemd"), "utf-8")
            except Exception as exc:  # noqa: BLE001
                return {**st, "ok": False, "message": f"写入 systemd 单元失败：{exc}"}
            scope = [] if st["mechanism"] == "systemd" else ["--user"]
            code, out = _run(["systemctl"] + scope + ["daemon-reload"])
            if code != 0:
                return {**st, "ok": False, "message": f"systemctl daemon-reload 失败：{out}"}
            code, out = _run(["systemctl"] + scope + ["enable", SYSTEMD_NAME])
            if code != 0:
                return {**st, "ok": False, "message": f"systemctl enable 失败：{out}"}
            if st["mechanism"] == "systemd-user":
                _run(["loginctl", "enable-linger", getpass.getuser()])
        else:
            ok, msg = _cron_set(True, root, port)
            if not ok:
                return {**st, "ok": False, "message": f"写 crontab 失败：{msg}"}
    elif plat == "macos":
        target = _mac_plist_path()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fh:
                plistlib.dump(_mac_plist(root, port), fh)
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"写入 LaunchAgent 失败：{exc}"}
        _run(["launchctl", "bootout", f"{_mac_domain()}/{LAUNCHD_LABEL}"])
        code, out = _run(["launchctl", "bootstrap", _mac_domain(), str(target)])
        if code != 0:
            code, out = _run(["launchctl", "load", "-w", str(target)])
        if code != 0:
            return {**st, "ok": False, "message": f"launchctl 加载失败：{out}"}
    fresh = status()
    fresh["ok"] = fresh["enabled"]
    fresh["message"] = fresh["message"] if fresh["enabled"] else "已写入配置，但状态检测未通过，请查看日志。"
    if fresh["enabled"]:
        fresh["message"] = "已开启开机自启。下次开机/登录后自动在后台启动，不用再手动设置。"
    return fresh


def disable() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    plat = st["platform"]
    if plat == "windows":
        try:
            _win_path().unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"删除启动项失败：{exc}"}
    elif plat == "linux":
        if st["mechanism"] in ("systemd", "systemd-user"):
            scope = [] if st["mechanism"] == "systemd" else ["--user"]
            _run(["systemctl"] + scope + ["disable", SYSTEMD_NAME])
            target = _linux_unit_path(st["mechanism"] == "systemd")
            try:
                target.unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                return {**st, "ok": False, "message": f"删除 systemd 单元失败（可能需要 sudo）：{exc}"}
            _run(["systemctl"] + scope + ["daemon-reload"])
        else:
            ok, msg = _cron_set(False, BASE_DIR, st["port"])
            if not ok:
                return {**st, "ok": False, "message": f"清理 crontab 失败：{msg}"}
    elif plat == "macos":
        _run(["launchctl", "bootout", f"{_mac_domain()}/{LAUNCHD_LABEL}"])
        _run(["launchctl", "unload", "-w", str(_mac_plist_path())])
        try:
            _mac_plist_path().unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"删除 LaunchAgent 失败：{exc}"}
    fresh = status()
    fresh["ok"] = not fresh["enabled"]
    fresh["message"] = "已关闭开机自启，当前运行的服务不受影响。" if fresh["ok"] else "关闭后状态仍显示已启用，请手动检查。"
    return fresh
