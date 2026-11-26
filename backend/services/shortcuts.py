"""桌面快捷方式：把工作台的前台页面和后台控制台写成桌面图标。

目的：装好之后不用记 IP 和端口，双击桌面图标就能进前台或后台。

- Windows：桌面生成 ``.url`` 互联网快捷方式（双击用默认浏览器打开）；
- Linux：桌面生成 ``.desktop`` 启动器（xdg-open），同时放进应用菜单；
- macOS：桌面生成 ``.webloc``；
- 容器/NAS 容器内：没有桌面，只返回可直接收藏的访问地址。

前端地址优先取配置里的 ``frontend_url``，没配就用 ``http://127.0.0.1:<port>/``；
后台控制台固定为 ``http://127.0.0.1:<port>/console/``。
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import BASE_DIR, DATA_DIR, load_config

MARKER = DATA_DIR / ".desktop_shortcuts"


# ------------------------------------------------------------------ 基础信息
def _port() -> int:
    raw = os.getenv("WORKBENCH_PORT") or load_config().get("port") or 9100
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 9100


def _in_docker() -> bool:
    return Path("/.dockerenv").exists() or str(os.getenv("WORKBENCH_IN_DOCKER") or "").lower() in ("1", "true", "yes")


def _platform() -> str:
    if _in_docker():
        return "docker"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _linux_has_desktop() -> bool:
    """Linux 上判断有没有图形桌面：没有桌面就只给地址，不往服务器里塞图标。"""
    if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
        return True
    return (Path.home() / "Desktop").exists()


def _app_name() -> str:
    name = str(load_config().get("org_short_name") or "AI 工作台").strip()
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "")
    return name or "AI 工作台"


def _urls() -> dict[str, str]:
    port = _port()
    front = str(load_config().get("frontend_url") or "").strip()
    if not front:
        front = f"http://127.0.0.1:{port}/"
    return {"front": front, "console": f"http://127.0.0.1:{port}/console/"}


def _lan_url() -> str:
    try:
        from .netinfo import lan_ip

        ip = lan_ip()
    except Exception:  # noqa: BLE001
        ip = ""
    return f"http://{ip}:{_port()}/console/" if ip and not ip.startswith("127.") else ""


# ------------------------------------------------------------------ 各平台桌面目录与文件名
def _desktop_dir() -> Path:
    plat = _platform()
    if plat == "windows":
        home = Path(os.getenv("USERPROFILE") or Path.home())
        for cand in (home / "Desktop", home / "OneDrive" / "Desktop", home / "OneDrive" / "桌面"):
            if cand.exists():
                return cand
        return home / "Desktop"
    return Path.home() / "Desktop"


def _file_name(kind: str) -> str:
    app = _app_name()
    suffix = "后台" if kind == "console" else ""
    if _platform() == "windows":
        return f"{app}{'-' + suffix if suffix else ''}.url"
    if _platform() == "macos":
        return f"{app}{'-' + suffix if suffix else ''}.webloc"
    return f"{app}{'-' + suffix if suffix else ''}.desktop"


def _target_path(kind: str) -> Path:
    return _desktop_dir() / _file_name(kind)


# ------------------------------------------------------------------ 写入
def _write_windows(path: Path, url: str, title: str) -> None:
    path.write_text(f"[InternetShortcut]\r\nURL={url}\r\n", "utf-8", newline="")


def _write_linux(path: Path, url: str, title: str, comment: str) -> None:
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={title}\n"
        f"Comment={comment}\n"
        f'Exec=xdg-open "{url}"\n'
        "Icon=web-browser\n"
        "Terminal=false\n"
        "Categories=Network;Utility;\n",
        "utf-8",
    )
    try:
        path.chmod(0o755)
    except Exception:  # noqa: BLE001
        pass


def _write_macos(path: Path, url: str, title: str) -> None:
    with open(path, "wb") as fh:
        plistlib.dump({"URL": url}, fh)


def _maybe_trust_linux(path: Path) -> None:
    """GNOME 需要 metadata::trusted 才允许双击，能设就设，设不了无所谓。"""
    gio = shutil.which("gio")
    if not gio:
        return
    try:
        subprocess.run([gio, "set", str(path), "metadata::trusted", "true"],
                       capture_output=True, timeout=8)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 对外
def status() -> dict:
    plat = _platform()
    urls = _urls()
    supported = plat != "docker" and (plat != "linux" or _linux_has_desktop())
    st = {
        "platform": plat,
        "supported": supported,
        "desktop": str(_desktop_dir()),
        "urls": urls,
        "lan_url": _lan_url(),
        "items": [],
        "message": "",
    }
    if plat == "docker":
        st["message"] = ("容器里没有桌面，快捷方式请在宿主机浏览器里收藏下面两个地址，"
                         "或在 NAS 桌面用“添加网页书签”。")
        st["items"] = [
            {"key": "front", "name": "前台", "url": urls["front"], "path": "", "exists": False},
            {"key": "console", "name": "后台", "url": urls["console"], "path": "", "exists": False},
        ]
        return st
    if not supported:
        st["message"] = "这台机器没有图形桌面（纯服务器），直接在浏览器里收藏下面两个地址即可。"
        st["items"] = [
            {"key": "front", "name": "前台", "url": urls["front"], "path": "", "exists": False},
            {"key": "console", "name": "后台", "url": urls["console"], "path": "", "exists": False},
        ]
        return st
    for key, name in (("front", "前台"), ("console", "后台")):
        target = _target_path(key)
        st["items"].append({"key": key, "name": name, "url": urls[key],
                            "path": str(target), "exists": target.exists()})
    exists = [x["exists"] for x in st["items"]]
    if all(exists):
        st["message"] = "桌面上已有前台和后台快捷方式，双击即可打开。"
    elif any(exists):
        st["message"] = "只找到其中一个快捷方式，点“创建桌面快捷方式”会补齐。"
    else:
        st["message"] = "还没有桌面快捷方式，点一下按钮就会放到桌面，以后不用记 IP。"
    return st


def create() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    urls = st["urls"]
    desktop = _desktop_dir()
    app = _app_name()
    try:
        desktop.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {**st, "ok": False, "message": f"桌面目录不可写：{exc}"}
    plat = st["platform"]
    for key, title, comment in (
        ("front", app, "打开本地 AI 工作台前台页面"),
        ("console", f"{app}（后台）", "打开本地 AI 工作台后台管理控制台"),
    ):
        target = _target_path(key)
        try:
            if plat == "windows":
                _write_windows(target, urls[key], title)
            elif plat == "macos":
                _write_macos(target, urls[key], title)
            else:
                _write_linux(target, urls[key], title, comment)
                _maybe_trust_linux(target)
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"写入 {target.name} 失败：{exc}"}
    if plat == "linux":
        menu = Path.home() / ".local" / "share" / "applications"
        try:
            menu.mkdir(parents=True, exist_ok=True)
            for key, title, comment in (
                ("front", app, "打开本地 AI 工作台前台页面"),
                ("console", f"{app}（后台）", "打开本地 AI 工作台后台管理控制台"),
            ):
                src = _target_path(key)
                if src.exists():
                    shutil.copyfile(src, menu / src.name)
                    (menu / src.name).chmod(0o755)
        except Exception:  # noqa: BLE001 应用菜单写失败不影响桌面图标
            pass
    fresh = status()
    fresh["ok"] = all(x["exists"] for x in fresh["items"])
    fresh["message"] = ("已创建桌面快捷方式：前台和后台各一个，双击就能打开，不用再记 IP。"
                        if fresh["ok"] else "已写入，但没在桌面找到文件，请检查桌面目录权限。")
    return fresh


def remove() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    removed = []
    for key in ("front", "console"):
        target = _target_path(key)
        try:
            if target.exists():
                target.unlink()
                removed.append(target.name)
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"删除 {target.name} 失败：{exc}"}
    fresh = status()
    fresh["ok"] = not any(x["exists"] for x in fresh["items"])
    fresh["message"] = ("已删除桌面快捷方式。" if fresh["ok"]
                        else "部分快捷方式仍存在，请检查桌面目录权限。")
    return fresh


def ensure_once() -> dict | None:
    """首次启动自动放一次桌面快捷方式；已经放过的实例不再重复打扰。

    只给「正式安装」放：数据目录被 WORKBENCH_DATA 指到别处时（测试实例、
    多开实例）不去覆盖桌面上的图标，避免把用户真正的快捷方式改到临时端口。
    """
    try:
        cfg = load_config()
        if not cfg.get("desktop_shortcuts", True):
            return None
        if MARKER.exists():
            return None
        if DATA_DIR != BASE_DIR / "data":
            return None
        res = create()
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(res.get("message") or ("ok" if res.get("ok") else "skip"), "utf-8")
        return res
    except Exception:  # noqa: BLE001
        return None
