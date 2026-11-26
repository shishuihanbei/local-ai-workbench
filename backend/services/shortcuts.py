"""桌面快捷方式：一个应用图标，双击就进工作台。

设计取舍：
- 只放 **一个** 图标，指向前台主界面；后台控制台从前台侧栏的「管理控制台」
  入口进（管理员可见），不再单独摆第二个图标。
- Windows 用真正的 ``.lnk`` + 自绘应用图标，看起来像软件而不是网页书签；
  双击时如果服务没在跑，会先静默拉起再打开浏览器（``open.ps1``）。
- Linux 用 ``.desktop`` + 同一个图标，Exec 指向 ``open.sh``（同样先确保服务在跑）。
- macOS 用 ``.webloc``（launchd 已负责登录后常驻，双击直接开页面）。
- 容器 / 无桌面服务器：不写文件，只返回可收藏的地址。

图标在 ``data/branding/workbench.ico``（顺带一份 png），按品牌主色生成，
没有 Pillow 时自动跳过图标，不影响快捷方式本身。
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from ..config import BASE_DIR, CREATE_NO_WINDOW, DATA_DIR, load_config

MARKER = DATA_DIR / ".desktop_shortcuts"
LEGACY_SUFFIXES = (".url", ".desktop", ".webloc")


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


def _desktop_dir() -> Path:
    if _platform() == "windows":
        home = Path(os.getenv("USERPROFILE") or Path.home())
        for cand in (home / "Desktop", home / "OneDrive" / "Desktop", home / "OneDrive" / "桌面"):
            if cand.exists():
                return cand
        return home / "Desktop"
    return Path.home() / "Desktop"


def _file_name() -> str:
    app = _app_name()
    if _platform() == "windows":
        return f"{app}.lnk"
    if _platform() == "macos":
        return f"{app}.webloc"
    return f"{app}.desktop"


def _target_path() -> Path:
    return _desktop_dir() / _file_name()


def _legacy_names() -> list[str]:
    """旧版本留下的第二个图标（后台），创建/删除时顺手清掉。"""
    app = _app_name()
    return [f"{app}-后台{suffix}" for suffix in LEGACY_SUFFIXES] + [f"{app}-后台管理{suffix}" for suffix in LEGACY_SUFFIXES]


# ------------------------------------------------------------------ 图标
def _icon_paths() -> tuple[Path, Path]:
    base = DATA_DIR / "branding"
    return base / "workbench.ico", base / "workbench.png"


def _ensure_icon() -> str:
    """按品牌主色画一枚 256×256 应用图标，返回 .ico 路径；失败返回空。"""
    ico, png = _icon_paths()
    try:
        if ico.exists() and ico.stat().st_size > 1000 and png.exists():
            return str(ico)
        from PIL import Image, ImageDraw, ImageFont

        color = str(load_config().get("brand_primary") or "#4f6ef7").lstrip("#")
        if len(color) != 6:
            color = "4f6ef7"
        rgb = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
        light = tuple(min(255, int(v + (255 - v) * 0.42)) for v in rgb)

        size = 256
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        for y in range(size):
            t = y / (size - 1)
            gd.line([(0, y), (size, y)],
                    fill=(int(rgb[0] + (light[0] - rgb[0]) * t),
                          int(rgb[1] + (light[1] - rgb[1]) * t),
                          int(rgb[2] + (light[2] - rgb[2]) * t), 255))
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([8, 8, size - 8, size - 8], radius=52, fill=255)
        img.paste(grad, (0, 0), mask)

        draw = ImageDraw.Draw(img)
        font = None
        for cand in ("msyhbd.ttc", "msyh.ttc", "arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
            for root in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype"), Path("/System/Library/Fonts")):
                p = root / cand
                if p.exists():
                    try:
                        font = ImageFont.truetype(str(p), 104)
                        break
                    except Exception:  # noqa: BLE001
                       font = None
            if font:
                break
        text = "AI"
        if font is not None:
            bbox = draw.textbbox((0, 0), text, font=font)
            draw.text(((size - (bbox[2] - bbox[0])) / 2 - bbox[0],
                       (size - (bbox[3] - bbox[1])) / 2 - bbox[1] - 8),
                      text, font=font, fill=(255, 255, 255, 255))
        draw.rounded_rectangle([84, 196, 172, 206], radius=5, fill=(255, 255, 255, 190))

        base = ico.parent
        base.mkdir(parents=True, exist_ok=True)
        img.save(png, "PNG")
        img.save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return str(ico)
    except Exception:  # noqa: BLE001 没有 Pillow / 字体时图标可缺省
        return ""


# ------------------------------------------------------------------ 写入
def _write_url(path: Path, url: str) -> None:
    path.write_text(f"[InternetShortcut]\r\nURL={url}\r\n", "utf-8", newline="")


def _write_webloc(path: Path, url: str) -> None:
    with open(path, "wb") as fh:
        plistlib.dump({"URL": url}, fh)


def _write_desktop_entry(path: Path, url: str, root: Path) -> None:
    opener = root / "open.sh"
    icon, _ = _icon_paths()
    exec_line = f'Exec="{opener}"' if opener.exists() else f'Exec=xdg-open "{url}"'
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_app_name()}\n"
        "Comment=打开本地 AI 工作台\n"
        f"{exec_line}\n"
        f"Icon={icon if icon.exists() else 'web-browser'}\n"
        "Terminal=false\n"
        "Categories=Network;Utility;\n",
        "utf-8",
    )
    try:
        path.chmod(0o755)
    except Exception:  # noqa: BLE001
        pass


def _maybe_trust_linux(path: Path) -> None:
    gio = shutil.which("gio")
    if not gio:
        return
    try:
        subprocess.run([gio, "set", str(path), "metadata::trusted", "true"],
                       capture_output=True, timeout=8)
    except Exception:  # noqa: BLE001
        pass


def _write_windows_lnk(path: Path, url: str, root: Path) -> bool:
    """用 WScript.Shell 建 .lnk；失败则由调用方退回 .url。"""
    opener = root / "open.ps1"
    if not opener.exists():
        return False
    icon = _ensure_icon()
    parts = [
        "$ErrorActionPreference='Stop';",
        "$ws = New-Object -ComObject WScript.Shell;",
        f'$s = $ws.CreateShortcut("{path}");',
        '$s.TargetPath = "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe";',
        f'$s.Arguments = \'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{opener}"\';',
        f'$s.WorkingDirectory = "{root}";',
        f'$s.Description = "{_app_name()}";',
    ]
    if icon:
        parts.append(f'$s.IconLocation = "{icon},0";')
    parts.append("$s.Save()")
    ps = "".join(parts)
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True, timeout=25,
                           creationflags=CREATE_NO_WINDOW)
        return p.returncode == 0 and path.exists()
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ 对外
def _items(urls: dict[str, str]) -> list[dict]:
    if _platform() in ("docker",) or not _supported():
        return [{"key": "app", "name": "工作台", "url": urls["front"], "path": "", "exists": False}]
    target = _target_path()
    if not target.exists() and _platform() == "windows":
        alt = _desktop_dir() / f"{_app_name()}.url"
        if alt.exists():
            target = alt
    return [{"key": "app", "name": "工作台", "url": urls["front"], "path": str(target),
             "exists": target.exists()}]


def _supported() -> bool:
    plat = _platform()
    if plat == "docker":
        return False
    if plat == "linux":
        return _linux_has_desktop()
    return True


def status() -> dict:
    plat = _platform()
    urls = _urls()
    st = {
        "platform": plat,
        "supported": _supported(),
        "desktop": str(_desktop_dir()),
        "urls": urls,
        "lan_url": _lan_url(),
        "items": _items(urls),
        "message": "",
    }
    if plat == "docker":
        st["message"] = ("容器里没有桌面，图标请在宿主机自己建；也可以直接收藏下面两个地址，"
                         "或把控制台入口加到 NAS 桌面书签。")
        return st
    if not st["supported"]:
        st["message"] = "这台机器没有图形桌面（纯服务器），直接在浏览器里收藏前台和后台地址即可。"
        return st
    if st["items"][0]["exists"]:
        st["message"] = "桌面上已有工作台图标，双击直接进前台；后台从侧栏「管理控制台」进。"
    else:
        st["message"] = "还没有桌面图标，点一下按钮放一个；双击进前台，后台在侧栏「管理控制台」。"
    return st


def create() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    urls = st["urls"]
    root = BASE_DIR
    target = _target_path()
    try:
        _desktop_dir().mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {**st, "ok": False, "message": f"桌面目录不可写：{exc}"}
    for legacy in _legacy_names():
        p = _desktop_dir() / legacy
        if p.exists() and p.name != target.name:
            try:
                p.unlink()
            except Exception:  # noqa: BLE001
                pass
    plat = st["platform"]
    try:
        if plat == "windows":
            if _write_windows_lnk(target, urls["front"], root):
                old_url = _desktop_dir() / f"{_app_name()}.url"
                if old_url.exists():
                    try:
                        old_url.unlink()
                    except Exception:  # noqa: BLE001
                        pass
            else:
                target = _desktop_dir() / f"{_app_name()}.url"
                _write_url(target, urls["front"])
        elif plat == "macos":
            _write_webloc(target, urls["front"])
        else:
            _write_desktop_entry(target, urls["front"], root)
            _maybe_trust_linux(target)
            menu = Path.home() / ".local" / "share" / "applications"
            try:
                menu.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(target, menu / target.name)
                (menu / target.name).chmod(0o755)
            except Exception:  # noqa: BLE001 应用菜单失败不影响桌面图标
                pass
    except Exception as exc:  # noqa: BLE001
        return {**st, "ok": False, "message": f"写入桌面图标失败：{exc}"}
    fresh = status()
    fresh["ok"] = bool(fresh["items"][0]["exists"])
    fresh["message"] = ("已创建桌面图标，双击进前台，后台从侧栏「管理控制台」进。"
                        if fresh["ok"] else "已写入，但没在桌面找到文件，请检查桌面目录权限。")
    fresh["items"][0]["path"] = str(target)
    return fresh


def remove() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    removed = []
    for name in _legacy_names() + [_file_name()]:
        p = _desktop_dir() / name
        try:
            if p.exists():
                p.unlink()
                removed.append(name)
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"删除 {name} 失败：{exc}"}
    fresh = status()
    fresh["ok"] = not fresh["items"][0]["exists"]
    fresh["message"] = ("已删除桌面图标。" if fresh["ok"] else "图标仍存在，请检查桌面目录权限。")
    return fresh


def ensure_once() -> dict | None:
    """正式安装首次启动自动放一次；测试/多开实例（数据目录被改写）不动桌面。"""
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
