"""桌面入口：一个像软件一样的图标，双击进后台，右键可选前台。

设计取舍：
- 桌面上只放 **一个** 图标，双击默认进「管理控制台」（后台）；右键菜单里
  另有「打开前台」「打开后台」两项（Windows 用自建文件类型 + 注册表动词实现）。
- 图标也是「启动器」：双击时如果服务没在跑，会先静默拉起再打开浏览器
  （Windows 走 ``open.ps1``，Linux/macOS 走 ``open.sh``）。
- 打开的地址可选：本机 127.0.0.1、局域网 IP、或自定义/外网地址，存在
  ``config.json`` 的 ``shortcut_mode`` / ``shortcut_lan_ip`` / ``shortcut_custom_url``，
  启动器每次读取，改完不用重建图标。
- Windows 用 ``.wbapp``（注册到 HKCU 的自定义类型，带图标和右键动词）；
  Linux 用 ``.desktop``（Actions 提供「打开前台 / 打开后台」）；macOS 用 ``.webloc``。
- 容器 / 无桌面服务器：不写文件，只返回可收藏的地址。

图标在 ``data/branding/workbench.ico``（顺带一份 png），按品牌主色生成，
没有 Pillow 时自动跳过图标，不影响入口本身。
"""
from __future__ import annotations

import ipaddress
import os
import plistlib
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from ..config import BASE_DIR, DATA_DIR, load_config

MARKER = DATA_DIR / ".desktop_shortcuts"
LEGACY_SUFFIXES = (".url", ".lnk", ".desktop", ".webloc")
APP_EXT = ".wbapp"
PROGID = "AIWorkbench.App"
MODES = ("local", "lan", "custom")


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


# ------------------------------------------------------------------ 地址选择
def _mode() -> str:
    mode = str(load_config().get("shortcut_mode") or "local").strip().lower()
    return mode if mode in MODES else "local"


def _lan_candidates() -> list[dict]:
    """本机所有可用于局域网的 IPv4，附带网卡名。"""
    found: dict[str, str] = {}
    try:
        import psutil  # type: ignore

        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                ip = str(getattr(a, "address", "") or "")
                if a.family == socket.AF_INET and ip and not ip.startswith(("127.", "169.254.")):
                    found.setdefault(ip, name)
    except Exception:  # noqa: BLE001 psutil 不是硬依赖
        pass
    if not found:
        try:
            from .netinfo import lan_ip

            ip = lan_ip()
            if ip:
                found[ip] = ""
        except Exception:  # noqa: BLE001
            pass
    return [{"ip": ip, "iface": name} for ip, name in sorted(found.items())]


def _lan_ip() -> str:
    cfg = load_config()
    chosen = str(cfg.get("shortcut_lan_ip") or "").strip()
    if chosen:
        return chosen
    try:
        from .netinfo import lan_ip

        return lan_ip()
    except Exception:  # noqa: BLE001
        return ""


def _base_url() -> str:
    port = _port()
    mode = _mode()
    if mode == "lan":
        ip = _lan_ip()
        if ip and not ip.startswith("127."):
            return f"http://{ip}:{port}"
    if mode == "custom":
        raw = str(load_config().get("shortcut_custom_url") or "").strip().rstrip("/")
        if raw.startswith(("http://", "https://")):
            return raw
    return f"http://127.0.0.1:{port}"


def _urls() -> dict[str, str]:
    base = _base_url()
    return {"front": f"{base}/", "console": f"{base}/console/"}


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
        return f"{app}{APP_EXT}"
    if _platform() == "macos":
        return f"{app}.webloc"
    return f"{app}.desktop"


def _target_path() -> Path:
    return _desktop_dir() / _file_name()


def _legacy_names() -> list[str]:
    """旧版本留下的图标（两个图标版本、.lnk 版本）创建/删除时顺手清掉。"""
    app = _app_name()
    names = [f"{app}{suffix}" for suffix in LEGACY_SUFFIXES]
    names += [f"{app}-后台{suffix}" for suffix in LEGACY_SUFFIXES]
    names += [f"{app}-后台管理{suffix}" for suffix in LEGACY_SUFFIXES]
    return names


# ------------------------------------------------------------------ 图标
def _icon_paths() -> tuple[Path, Path]:
    return DATA_DIR / "branding" / "workbench.ico", DATA_DIR / "branding" / "workbench.png"


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


# ------------------------------------------------------------------ 写入：Windows
def _ps_exe() -> str:
    root = os.environ.get("SystemRoot") or "C:/Windows"
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _launcher_ps1() -> Path:
    return BASE_DIR / "open.ps1"


def _windows_command(mode: str) -> str:
    opener = _launcher_ps1()
    return (f'"{_ps_exe()}" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
            f'-File "{opener}" -Mode {mode}')


def _write_windows_app(path: Path, url: str) -> bool:
    """写一个自定义类型文件 + HKCU 注册表，做出「双击进后台、右键选前后台」的图标。"""
    opener = _launcher_ps1()
    if not opener.exists():
        return False
    icon = _ensure_icon()
    try:
        path.write_text(
            "AI Workbench desktop launcher\n"
            "File type: AIWorkbench.App (HKCU\\Software\\Classes)\n"
            "Double-click opens the admin console; right-click for front / console.\n",
            "utf-8",
        )
        import winreg

        classes = r"Software\Classes"
        prog = f"{classes}\\{PROGID}"
        ext = f"{classes}\\{APP_EXT}"

        def set_value(key_path: str, name: str, value: str) -> None:
            key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
            try:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            finally:
                key.Close()

        set_value(ext, "", PROGID)
        set_value(prog, "", "AI 工作台")
        set_value(prog, "FriendlyTypeName", "AI 工作台入口")
        set_value(prog + r"\DefaultIcon", "", f'"{icon}",0' if icon else f'"{_ps_exe()}",0')
        set_value(prog + r"\shell", "", "console")
        set_value(prog + r"\shell\console", "", "打开后台")
        set_value(prog + r"\shell\console", "Icon", f'"{icon}",0' if icon else f'"{_ps_exe()}",0')
        set_value(prog + r"\shell\console\command", "", _windows_command("console"))
        set_value(prog + r"\shell\front", "", "打开前台")
        set_value(prog + r"\shell\front", "Icon", f'"{icon}",0' if icon else f'"{_ps_exe()}",0')
        set_value(prog + r"\shell\front\command", "", _windows_command("front"))
        return path.exists()
    except Exception:  # noqa: BLE001 注册表被策略禁用时退回 .url
        return False


def _remove_key_tree(root, path: str) -> None:
    import winreg

    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return
    subs: list[str] = []
    try:
        while True:
            try:
                subs.append(winreg.EnumKey(key, len(subs)))
            except OSError:
                break
    finally:
        key.Close()
    for sub in subs:
        _remove_key_tree(root, f"{path}\\{sub}")
    try:
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def _remove_windows_app() -> None:
    try:
        import winreg

        _remove_key_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}")
        _remove_key_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{APP_EXT}")
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 写入：Linux / macOS
def _write_url(path: Path, url: str) -> None:
    path.write_text(f"[InternetShortcut]\r\nURL={url}\r\n", "utf-8", newline="")


def _write_webloc(path: Path, url: str) -> None:
    with open(path, "wb") as fh:
        plistlib.dump({"URL": url}, fh)


def _write_desktop_entry(path: Path, url: str, root: Path) -> None:
    opener = root / "open.sh"
    icon, _ = _icon_paths()
    if opener.exists():
        try:
            opener.chmod(0o755)
        except Exception:  # noqa: BLE001
            pass
        default_exec = f'Exec="{opener}" console'
        front_exec = f'Exec="{opener}" front'
        console_exec = f'Exec="{opener}" console'
        actions = ("Actions=Front;Console;\n"
                   "[Desktop Action Front]\nName=打开前台\n" + front_exec + "\n"
                   "[Desktop Action Console]\nName=打开后台\n" + console_exec + "\n")
    else:
        default_exec = f'Exec=xdg-open "{url}"'
        actions = ""
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={_app_name()}\n"
        "Comment=打开本地 AI 工作台（默认进管理控制台）\n"
        f"{default_exec}\n"
        f"Icon={icon if icon.exists() else 'web-browser'}\n"
        "Terminal=false\n"
        "Categories=Network;Utility;\n"
        + actions,
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


# ------------------------------------------------------------------ 对外
def _items(urls: dict[str, str]) -> list[dict]:
    if _platform() in ("docker",) or not _supported():
        return [{"key": "app", "name": "工作台", "url": urls["front"], "path": "", "exists": False}]
    target = _target_path()
    if not target.exists() and _platform() == "windows":
        # 注册表被策略禁用时的 .url 兜底
        alt = _desktop_dir() / f"{_app_name()}.url"
        if alt.exists():
            target = alt
    return [{"key": "app", "name": "工作台", "url": urls["console"], "path": str(target),
             "exists": target.exists()}]


def _supported() -> bool:
    plat = _platform()
    if plat == "docker":
        return False
    if plat == "linux":
        return _linux_has_desktop()
    return True


def _verbs() -> list[dict]:
    return [{"key": "front", "label": "打开前台"}, {"key": "console", "label": "打开后台"}]


def status() -> dict:
    plat = _platform()
    urls = _urls()
    lan_ips = _lan_candidates()
    st = {
        "platform": plat,
        "supported": _supported(),
        "desktop": str(_desktop_dir()),
        "urls": urls,
        "mode": _mode(),
        "lan_ip": _lan_ip(),
        "lan_ips": lan_ips,
        "custom_url": str(load_config().get("shortcut_custom_url") or ""),
        "lan_url": _lan_url(),
        "verbs": _verbs(),
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
        st["message"] = "桌面上已有工作台图标：双击进后台；右键可选「打开前台 / 打开后台」。"
    else:
        st["message"] = "还没有桌面图标，点一下按钮放一个：双击进后台，右键可切前台。"
    return st


def save_settings(mode: str, lan_ip: str = "", custom_url: str = "") -> dict:
    """保存「打开哪个地址」的偏好；不用重建图标，启动器每次读取。"""
    if mode not in MODES:
        raise ValueError("地址类型只能是 local / lan / custom")
    lan_ip = str(lan_ip or "").strip()
    if lan_ip:
        try:
            ipaddress.ip_address(lan_ip)
        except ValueError as exc:
            raise ValueError(f"局域网地址不合法：{lan_ip}") from exc
    custom_url = str(custom_url or "").strip().rstrip("/")
    if custom_url and not custom_url.startswith(("http://", "https://")):
        raise ValueError("自定义地址要以 http:// 或 https:// 开头")
    if mode == "custom" and not custom_url:
        raise ValueError("选了自定义地址，需要填一个 http(s) 地址")
    from ..config import save_config

    cfg = load_config()
    cfg["shortcut_mode"] = mode
    cfg["shortcut_lan_ip"] = lan_ip
    cfg["shortcut_custom_url"] = custom_url
    save_config(cfg)
    return status()


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
            _remove_windows_app()
            if not _write_windows_app(target, urls["console"]):
                target = _desktop_dir() / f"{_app_name()}.url"
                _write_url(target, urls["console"])
        elif plat == "macos":
            _write_webloc(target, urls["console"])
        else:
            _write_desktop_entry(target, urls["console"], root)
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
    fresh["message"] = ("已创建桌面图标：双击进后台，右键可选「打开前台 / 打开后台」。"
                        if fresh["ok"] else "已写入，但没在桌面找到文件，请检查桌面目录权限。")
    fresh["items"][0]["path"] = str(target)
    return fresh


def remove() -> dict:
    st = status()
    if not st["supported"]:
        return {**st, "ok": False}
    if _platform() == "windows":
        _remove_windows_app()
    for name in _legacy_names() + [_file_name()]:
        p = _desktop_dir() / name
        try:
            if p.exists():
                p.unlink()
        except Exception as exc:  # noqa: BLE001
            return {**st, "ok": False, "message": f"删除 {name} 失败：{exc}"}
    fresh = status()
    fresh["ok"] = not fresh["items"][0]["exists"]
    fresh["message"] = "已删除桌面图标。" if fresh["ok"] else "图标仍存在，请检查桌面目录权限。"
    return fresh


def ensure_once() -> dict | None:
    """正式安装首次启动自动放一次；测试/多开实例（数据目录被改写）不动桌面。"""
    try:
        cfg = load_config()
        if not cfg.get("desktop_shortcuts", True):
            return None
        if DATA_DIR != BASE_DIR / "data":
            return None
        if MARKER.exists():
            # 旧版本用 .lnk / .url，换成新的单图标类型；只迁移一次
            if _platform() == "windows" and not _target_path().exists():
                res = create()
                MARKER.write_text(res.get("message") or "ok", "utf-8")
                return res
            return None
        res = create()
        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text(res.get("message") or ("ok" if res.get("ok") else "skip"), "utf-8")
        return res
    except Exception:  # noqa: BLE001
        return None
