"""系统信息、日志、设置、审计、备份。"""
from __future__ import annotations

import json
import platform
import shutil
import socket
import sys
import time
from urllib.parse import urlsplit

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from ..errors import NOT_LOCAL, APIError
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..config import BASE_DIR, DATA_DIR, LOG_DIR, load_config, model_file_path, save_config
from ..db import audit, fetch_all, fetch_one
from .. import ollama_tags
from ..security import admin_user, any_user_or_none, current_user, user_from_any_token
from ..services import (autostart, backup, hardware, installer, llama, netinfo, platform_deploy,
                        platform_models, platform_store, platforms, retention, shortcuts, storage, websearch)

router = APIRouter(prefix="/api/system", tags=["system"])


async def _admin_from_request(request: Request, token: str | None = None) -> dict:
    user = await user_from_any_token(token) if token else None
    auth = request.headers.get("authorization", "")
    if not user and auth.lower().startswith("bearer "):
        user = await user_from_any_token(auth.split(" ", 1)[1].strip())
    if not user:
        user = await any_user_or_none(request)
    if not user:
        raise HTTPException(401, "未登录或令牌已失效")
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user
START_TS = time.time()

SETTING_KEYS = [
    "upstream_base", "upstream_key", "upstream_port", "ctx", "threads", "gpu_layers",
    "system_prompt", "tts_voice", "session_hours", "models_dir", "llama_dir", "llama_bin",
    "tunnel_target", "tunnel_token", "tunnel_domain", "github_proxy", "kb_enabled", "kb_top_k",
    "library_enabled", "library_max_chars", "library_max_docs",
    "frontend_url", "allow_register",
    "org_name", "org_short_name", "org_domain", "org_industry", "org_size",
    "org_contact_name", "org_contact_email",
    "watermark_enabled", "watermark_text",
]


class SettingsBody(BaseModel):
    pass


class LocalDeployBody(BaseModel):
    enabled: bool
    platforms: list[str] | None = None
    endpoints: dict[str, str] | None = None
    github_proxy: str | None = None


class OllamaPullBody(BaseModel):
    tag: str = ""


class LocalPlatformsBody(BaseModel):
    platforms: list[str] | None = None
    endpoints: dict[str, str] | None = None
    github_proxy: str | None = None


class WebsearchBody(BaseModel):
    enabled: bool | None = None
    max_sources: int | None = None
    max_pages: int | None = None


class WebsearchTestBody(BaseModel):
    query: str = ""
    max_sources: int | None = None
    max_pages: int | None = None


class FileRetentionBody(BaseModel):
    days: int


def _local_ips() -> list[str]:
    ips = []
    try:
        for name, addrs in psutil.net_if_addrs().items():
            if any(k in name for k in ("Loopback", "蓝牙", "Bluetooth", "vEthernet", "VMware", "Virtual")):
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                    ips.append(f"{a.address} ({name})")
    except Exception:
        pass
    return ips


@router.get("/info")
async def info(user: dict = Depends(current_user)):
    cfg = load_config()
    disk = shutil.disk_usage(str(DATA_DIR))
    mem = psutil.virtual_memory()
    cpu_percent = psutil.cpu_percent(interval=0.3)
    status = await llama.server.status()
    from ..services.tunnel import tunnel
    return {
        "app": {
            "version": "0.7.88",
            "uptime": round(time.time() - START_TS, 1),
            "panel_port": cfg["port"],
            "python": sys.version.split()[0],
            "platform": f"{platform.system()} {platform.release()}",
            "ips": _local_ips(),
            "data_dir": str(DATA_DIR),
        },
        "host": {
            "cpu_percent": cpu_percent,
            "cpu_count": psutil.cpu_count(),
            "mem_total": mem.total,
            "mem_used": mem.used,
            "mem_percent": mem.percent,
            "disk_total": disk.total,
            "disk_free": disk.free,
            "disk_percent": round(disk.used * 100 / disk.total, 1),
            "boot_time": psutil.boot_time(),
        },
        "model": status,
        "tunnel": tunnel.status(),
        "config": {k: cfg.get(k) for k in SETTING_KEYS},
    }


@router.get("/stats")
async def stats(user: dict = Depends(current_user)):
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.2)
    return {"cpu": cpu, "mem": mem.percent, "mem_used": mem.used, "mem_total": mem.total}


LOG_FILES = {
    "llama": LOG_DIR / "llama.log",
    "tunnel": LOG_DIR / "tunnel.log",
    "app": LOG_DIR / "app.log",
}


@router.get("/logs")
async def logs(file: str = Query("llama"), tail: int = 200, user: dict = Depends(admin_user)):
    p = LOG_FILES.get(file)
    if not p:
        raise HTTPException(404, "未知日志")
    if not p.exists():
        return {"lines": [], "file": file}
    text = p.read_bytes()[-300_000:].decode("utf-8", "replace")
    return {"lines": text.splitlines()[-min(tail, 1000):], "file": file}


@router.get("/settings")
async def get_settings(request: Request, user: dict = Depends(admin_user)):
    cfg = load_config()
    data = {k: cfg.get(k) for k in SETTING_KEYS}
    origin = netinfo.origin(request)
    configured = str(cfg.get("frontend_url") or "").strip()
    auto = bool(cfg.get("serve_frontend", False) and origin)
    if auto:
        # 本机打开控制台时，前端按钮默认走局域网（跟随桌面图标地址偏好）；
        # 已经通过局域网/域名访问的，就沿用当前访问地址。
        host = (urlsplit(origin).hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1", ""):
            base = shortcuts.base_url().rstrip("/") or origin
        else:
            base = origin
        data["frontend_url"] = f"{base}/"
    data["frontend_url_auto"] = auto
    data["frontend_url_configured"] = configured
    data["request_origin"] = origin
    data["client_ip"] = netinfo.client_ip(request)
    return data


@router.get("/local-access")
async def local_access(request: Request, user: dict = Depends(current_user)):
    """当前浏览器是否运行在工作台这台电脑上（决定“打开文件夹”类按钮可用）。

    注意：本机通过局域网地址访问也算本机——只认 127.0.0.1 会误判。
    """
    return {
        "local": netinfo.is_local_request(request),
        "client_ip": netinfo.client_ip(request),
        "origin": netinfo.origin(request),
    }


@router.put("/settings")
async def put_settings(body: dict, user: dict = Depends(admin_user)):
    cfg = load_config()
    changed = []
    for k, v in (body or {}).items():
        if k not in SETTING_KEYS:
            continue
        if k == "frontend_url" and v:
            v = str(v).strip()
            if not v.startswith(("http://", "https://")):
                raise HTTPException(400, "frontend_url 只支持 http/https 地址")
        default = cfg.get(k)
        if isinstance(default, bool):
            v = bool(v)
        elif isinstance(default, int) and v not in (None, ""):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} 需要整数")
        cfg[k] = v
        changed.append(k)
    save_config(cfg)
    await audit(user, "settings.update", detail=",".join(changed))
    return {"ok": True, "changed": changed}


@router.get("/storage")
async def storage_status(user: dict = Depends(admin_user)):
    """模型目录、部署平台目录，以及默认位置。"""
    return storage.status()


@router.put("/storage")
async def storage_update(body: dict, user: dict = Depends(admin_user)):
    """保存自定义模型目录 / 部署平台目录；只改路径，不自动搬文件。"""
    try:
        result = await run_in_threadpool(
            storage.set_paths,
            (body or {}).get("models_dir"),
            (body or {}).get("platforms_dir"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit(user, "settings.storage", detail=json.dumps(
        {"models_dir": result.get("models_dir"), "platforms_dir": result.get("platforms_dir")},
        ensure_ascii=False))
    return result


@router.get("/audit")
async def audit_list(page: int = 1, size: int = 30, action: str = "", user: dict = Depends(admin_user)):
    where, params = "", []
    if action:
        where = "WHERE action LIKE ?"
        params.append(f"%{action}%")
    total = await fetch_one(f"SELECT COUNT(*) c FROM audit_logs {where}", params)
    rows = await fetch_all(
        f"SELECT * FROM audit_logs {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
        params + [size, (page - 1) * size])
    return {"items": rows, "total": (total or {}).get("c", 0), "page": page, "size": size}


@router.get("/backup")
async def backup_download(request: Request, token: str | None = None):
    user = await _admin_from_request(request, token)
    try:
        path = await run_in_threadpool(backup.create_backup)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit(user, "system.backup", path.name)
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.get("/backups")
async def backup_list(request: Request, user: dict = Depends(admin_user)):
    return {
        "items": await run_in_threadpool(backup.list_backups),
        "backup_dir": str(backup.BACKUP_DIR),
        "migration_dir": str(backup.MIGRATION_DIR),
    }


@router.get("/file-retention")
async def file_retention(user: dict = Depends(admin_user)):
    """生成文档保留周期与磁盘占用，供备份页展示。"""
    return await retention.stats()


@router.put("/file-retention")
async def set_file_retention(body: FileRetentionBody, user: dict = Depends(admin_user)):
    days = retention.clamp_days(body.days)
    if not retention.MIN_DAYS <= body.days <= retention.MAX_DAYS:
        raise HTTPException(
            400, f"保留天数需在 {retention.MIN_DAYS}–{retention.MAX_DAYS} 天之间")
    cfg = load_config()
    cfg["generated_file_retention_days"] = days
    save_config(cfg)
    result = await retention.apply_days(days)
    await audit(user, "files.retention.update", detail=f"{days}天，清理{result['removed']}个")
    return {"ok": True, "result": result, **await retention.stats(days)}


@router.post("/file-retention/cleanup")
async def cleanup_file_retention(user: dict = Depends(admin_user)):
    result = await retention.cleanup_once()
    await audit(user, "files.retention.cleanup", detail=f"清理{result['removed']}个")
    return {"ok": True, "result": result, **await retention.stats()}


@router.get("/migration")
@router.post("/migration")
async def migration_download(request: Request, token: str | None = None, save: bool = False):
    # GET 兼容旧版控制台缓存；新版控制台统一用 POST。
    user = await _admin_from_request(request, token)
    try:
        path = await run_in_threadpool(backup.create_migration_package)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit(user, "system.migration", path.name)
    if save:
        return {
            "ok": True,
            "kind": "migration",
            "name": path.name,
            "path": str(path),
            "directory": str(path.parent),
            "size": path.stat().st_size,
            "download_url": f"/api/system/backups/{path.name}",
        }
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/open-migration-folder")
async def open_migration_folder(request: Request, token: str | None = None):
    await _admin_from_request(request, token)
    if not netinfo.is_local_request(request):
        raise APIError(403, "只能在运行工作台的电脑上打开这个文件夹（本机用局域网地址访问也可以）", NOT_LOCAL)
    try:
        path = await run_in_threadpool(backup.open_migration_folder)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "path": path}


@router.get("/shares")
async def share_list(request: Request, user: dict = Depends(admin_user)):
    return {
        "items": await run_in_threadpool(backup.list_shares),
        "share_dir": str(backup.SHARE_DIR),
    }


@router.get("/share")
@router.post("/share")
async def share_download(request: Request, token: str | None = None, save: bool = False):
    user = await _admin_from_request(request, token)
    try:
        path = await run_in_threadpool(backup.create_share_package)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    await audit(user, "system.share", path.name)
    if save:
        return {
            "ok": True,
            "kind": "share",
            "name": path.name,
            "path": str(path),
            "directory": str(path.parent),
            "size": path.stat().st_size,
            "download_url": f"/api/system/shares/{path.name}",
            "includes_data": False,
        }
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/open-share-folder")
async def open_share_folder(request: Request, token: str | None = None):
    await _admin_from_request(request, token)
    if not netinfo.is_local_request(request):
        raise APIError(403, "只能在运行工作台的电脑上打开这个文件夹（本机用局域网地址访问也可以）", NOT_LOCAL)
    try:
        path = await run_in_threadpool(backup.open_share_folder)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "path": path}


@router.get("/shares/{name}")
async def share_file(name: str, request: Request, user: dict = Depends(admin_user)):
    try:
        path = backup.share_path(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.delete("/shares/{name}")
async def share_delete(name: str, request: Request, user: dict = Depends(admin_user)):
    try:
        backup.delete_share(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc)) from exc
    await audit(user, "system.share.delete", name)
    return {"ok": True}


@router.get("/backups/{name}")
async def backup_file(name: str, request: Request, user: dict = Depends(admin_user)):
    try:
        path = backup.backup_path(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.delete("/backups/{name}")
async def delete_backup_file(name: str, request: Request, user: dict = Depends(admin_user)):
    try:
        backup.delete_backup(name)
    except backup.BackupError as exc:
        raise HTTPException(404, str(exc)) from exc
    await audit(user, "system.backup.delete", name)
    return {"ok": True}


@router.post("/restore")
async def restore_backup(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(admin_user),
):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "只支持备份 zip 文件")
    tmp = DATA_DIR / f"restore-upload-{int(time.time() * 1000)}.zip"
    total = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > backup.MAX_RESTORE_BYTES:
                    raise HTTPException(413, "备份文件超过 1GB")
                out.write(chunk)
        result = await run_in_threadpool(backup.restore_backup, tmp)
    except backup.BackupError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)
    await audit(user, "system.restore", file.filename or "", str(result.get("safety_backup") or ""))
    return result


@router.post("/restart-hint")
async def restart_hint(user: dict = Depends(admin_user)):
    """前端提示用：某些设置需要重启服务生效。"""
    return {"ok": True, "msg": "部分设置（端口、目录）需要重启服务后生效"}


@router.get("/autostart")
async def get_autostart(user: dict = Depends(admin_user)):
    """开机自启状态：是否已开启、用哪种机制、具体文件路径。"""
    return autostart.status()


@router.post("/autostart")
async def post_autostart(user: dict = Depends(admin_user)):
    """一键开启开机自启（Windows 启动项 / systemd / launchd / crontab）。"""
    res = await run_in_threadpool(autostart.enable)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or "开启失败")
    await audit(user, "system.autostart.on", res.get("mechanism", ""), res.get("path", ""))
    return res


@router.delete("/autostart")
async def delete_autostart(user: dict = Depends(admin_user)):
    """关闭开机自启，只删注册项，不影响当前运行的服务。"""
    res = await run_in_threadpool(autostart.disable)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or "关闭失败")
    await audit(user, "system.autostart.off", res.get("mechanism", ""), res.get("path", ""))
    return res


@router.get("/shortcuts")
async def get_shortcuts(user: dict = Depends(admin_user)):
    """桌面图标状态：是否已放好、双击进哪个地址、可选的前后台地址。"""
    return shortcuts.status()


@router.post("/shortcuts")
async def post_shortcuts(user: dict = Depends(admin_user)):
    """在桌面放一个应用图标：双击进后台，右键可选打开前台 / 打开后台。"""
    res = await run_in_threadpool(shortcuts.create)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or "创建桌面图标失败")
    await audit(user, "system.shortcuts.create", res.get("desktop", ""), res.get("urls", {}).get("console", ""))
    return res


@router.put("/shortcuts/settings")
async def put_shortcuts_settings(payload: dict, user: dict = Depends(admin_user)):
    """保存图标打开哪个地址：本机 / 局域网 IP / 自定义外网地址。下次双击生效。"""
    mode = str(payload.get("mode") or "local")
    lan_ip = str(payload.get("lan_ip") or "")
    custom_url = str(payload.get("custom_url") or "")
    try:
        res = await run_in_threadpool(lambda: shortcuts.save_settings(mode, lan_ip, custom_url))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await audit(user, "system.shortcuts.settings", mode, res.get("urls", {}).get("console", ""))
    return res


@router.delete("/shortcuts")
async def delete_shortcuts(user: dict = Depends(admin_user)):
    """删除桌面上的工作台图标（不影响服务运行）。"""
    res = await run_in_threadpool(shortcuts.remove)
    if not res.get("ok"):
        raise HTTPException(400, res.get("message") or "删除桌面图标失败")
    await audit(user, "system.shortcuts.remove", res.get("desktop", ""), "")
    return res


# ------------------------------------------------------------------ 部署检测 / 一键安装
@router.get("/hardware")
async def hardware_profile(user: dict = Depends(admin_user)):
    """本机配置：CPU、内存、磁盘、GPU、llama.cpp 状态、模型目录。"""
    prof = hardware.profile()
    prof["install"] = installer.status()
    return prof


@router.get("/install-status")
async def install_status(user: dict = Depends(admin_user)):
    return installer.status()


@router.get("/engine-home")
async def engine_home(user: dict = Depends(admin_user)):
    """所有下载/安装产物落在哪：给控制台“文件都在哪”面板用的目录清单。"""
    cfg = load_config()
    rows = await run_in_threadpool(platform_store.summary, cfg)
    bat = BASE_DIR / "uninstall.bat"
    ps1 = BASE_DIR / "uninstall.ps1"
    return {"ok": True, "root": str(BASE_DIR), "dirs": rows,
            "platforms_dir": str(platform_store.platforms_root(cfg)),
            "limits": {
                "downloads": str(platform_store.downloads(cfg)),
                "tmp": str(platform_store.tmp_root(cfg)),
                "cache": str(platform_store.cache_root()),
            },
            "uninstall": {"bat": str(bat), "ps1": str(ps1),
                          "exists": bat.exists() or ps1.exists()}}


@router.post("/install-llama")
async def install_llama(force: bool = False, user: dict = Depends(admin_user)):
    """后台自动下载并安装 llama.cpp（Windows/Linux 预编译包）。"""
    import asyncio
    if installer.STATE.get("running"):
        return {"ok": False, "msg": "安装已在进行中"}
    if hardware.llama_info()["installed"] and not force:
        return {"ok": False, "msg": "本机已安装 llama.cpp；如需覆盖重装请使用 force=true"}
    asyncio.create_task(installer.install_llama())
    await audit(user, "system.install_llama", "start")
    return {"ok": True, "msg": "已开始安装，可轮询进度"}


@router.get("/install-progress")
async def install_progress(user: dict = Depends(admin_user)):
    return installer.STATE


def _clean_github_proxy(value: str | None) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()[:300]
    if raw.lower() in ("off", "direct", "none", "auto", ""):
        return raw.lower() if raw else "auto"
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw.rstrip("/") + "/"


async def _platform_items(cfg: dict, selected: list[str], srv: dict, scan: bool = False) -> list[dict]:
    items = await platforms.status(cfg, selected, srv, probe_all=scan)
    return platform_deploy.enrich(items)


async def _pick_local_model(cfg: dict) -> dict | None:
    """优先当前配置模型，否则取第一个下载完整的本地模型。"""
    rows = await fetch_all("SELECT * FROM models ORDER BY sort,key")
    preferred = str(cfg.get("model") or "")
    if preferred:
        rows = [r for r in rows if preferred in (r["key"], r.get("alias"), r.get("label"))] + \
               [r for r in rows if preferred not in (r["key"], r.get("alias"), r.get("label"))]
    for row in rows:
        path = model_file_path(cfg, row["filename"])
        expected = int(row["total_bytes"] or 0)
        if not path.exists():
            continue
        if expected and path.stat().st_size + 1024 < expected:
            continue
        return row
    return None


def _adopt_deployed_platforms(cfg: dict, items: list[dict]) -> list[str]:
    """把已经装好/在跑的平台自动加进“启用的平台”，别让开关只认一个引擎。

    只补一次：记在 platform_auto_added 里，用户之后手动取消勾选会被尊重，
    不会每次刷新又被塞回去；重装/新装另一个平台时会再补新增的那个。
    """
    autoed = {str(x) for x in (cfg.get("platform_auto_added") or []) if str(x)}
    fresh = [i["key"] for i in items
             if i["key"] not in ("llama.cpp", "custom")
             and (i.get("installed") or i.get("healthy"))
             and i["key"] not in autoed]
    selected = platforms.normalize_selected(cfg.get("deploy_platforms"))
    if not fresh:
        return selected
    merged = selected + [k for k in fresh if k not in selected]
    cfg["deploy_platforms"] = merged
    cfg["platform_auto_added"] = sorted(autoed | set(fresh))
    save_config(cfg)
    platform_models.invalidate()
    return merged


@router.get("/local-deploy")
async def local_deploy_status(scan: bool = Query(False), user: dict = Depends(admin_user)):
    """本地部署总开关、平台选择与各平台实际状态；会顺带发现已装/在跑的平台。

    以前只探测勾选的平台：装了 LM Studio 没勾选就显示“未选中，不检测”，
    开关里也只列 Ollama。现在每次打开部署页都扫一遍全部平台，
    并把新发现的已装平台自动并入启用列表。
    """
    cfg = load_config()
    selected = platforms.normalize_selected(cfg.get("deploy_platforms"))
    srv = await llama.server.status()
    items = await _platform_items(cfg, selected, srv, True)
    selected = _adopt_deployed_platforms(cfg, items)
    for item in items:
        item["selected"] = item["key"] in selected
    return {
        "enabled": bool(cfg.get("local_enabled", True)),
        "installed": hardware.llama_info()["installed"],
        "model": srv.get("model") or cfg.get("model") or "",
        "server": srv,
        "selected": selected,
        "platforms": items,
        "endpoints": platforms.endpoints(cfg),
        "github_proxy": cfg.get("github_proxy") or "auto",
    }


@router.put("/local-platforms")
async def save_local_platforms(body: LocalPlatformsBody, user: dict = Depends(admin_user)):
    """只保存平台选择和外部平台地址，不改变本地部署开关。"""
    cfg = load_config()
    selected = platforms.normalize_selected(
        body.platforms if body.platforms is not None else cfg.get("deploy_platforms"))
    cfg["deploy_platforms"] = selected
    if body.endpoints is not None:
        cfg["platform_endpoints"] = platforms.clean_endpoints(body.endpoints, cfg)
    platform_models.invalidate()
    proxy = _clean_github_proxy(body.github_proxy)
    if proxy is not None:
        cfg["github_proxy"] = proxy
    save_config(cfg)
    srv = await llama.server.status()
    items = await _platform_items(cfg, selected, srv)
    await audit(user, "system.local.platforms", detail=",".join(selected))
    return {"ok": True, "enabled": bool(cfg.get("local_enabled", True)),
            "selected": selected, "platforms": items,
            "endpoints": platforms.endpoints(cfg), "github_proxy": cfg.get("github_proxy") or "auto",
            "server": srv}


@router.post("/local-platforms/{key}/cancel")
async def cancel_platform(key: str, user: dict = Depends(admin_user)):
    """取消正在进行的部署：下载停下保留 .part，安装子进程直接结束。"""
    if key not in platforms.PLATFORMS:
        raise HTTPException(404, "未知平台")
    result = platform_deploy.request_cancel(key)
    await audit(user, "system.platform.cancel", key, detail=result.get("msg", ""))
    return result


@router.post("/local-platforms/{key}/start")
async def start_platform(key: str, endpoint: str = Query(""), user: dict = Depends(admin_user)):
    """已安装平台的一键启动：不重新安装、不下载，只拉起服务。"""
    import asyncio
    if key not in platforms.PLATFORMS:
        raise HTTPException(404, "未知平台")
    if platform_deploy.is_running(key):
        return {"ok": False, "msg": "这个平台正在启动，请稍等", "state": platform_deploy.get_state(key)}
    if not platform_deploy.detect(key).get("installed"):
        return {"ok": False, "msg": "还没有安装，请先点“一键部署”", "state": platform_deploy.get_state(key)}
    platform_models.invalidate()
    asyncio.create_task(platform_deploy.start(key, endpoint=(endpoint or "").strip()[:300]))
    await audit(user, "system.platform.start", key)
    return {"ok": True, "msg": "已开始启动", "key": key}


@router.post("/local-platforms/{key}/stop")
async def stop_platform(key: str, user: dict = Depends(admin_user)):
    """停掉工作台自己拉起的服务；系统托盘里启动的不动。"""
    if key not in platforms.PLATFORMS:
        raise HTTPException(404, "未知平台")
    result = await platform_deploy.stop(key)
    await audit(user, "system.platform.stop", key, detail=str(result.get("msg", ""))[:300])
    return result


@router.post("/local-platforms/{key}/deploy")
async def deploy_platform(key: str, force: bool = Query(False), endpoint: str = Query(""),
                          user: dict = Depends(admin_user)):
    """单个平台一键部署：已安装就跳过下载，仍会尝试启动/连接。"""
    import asyncio
    if key not in platforms.PLATFORMS:
        raise HTTPException(404, "未知平台")
    if platform_deploy.is_running(key):
        return {"ok": False, "msg": "这个平台正在部署，请稍等", "state": platform_deploy.get_state(key)}
    endpoint = (endpoint or "").strip()[:300]
    platform_models.invalidate()
    asyncio.create_task(platform_deploy.deploy(key, force=force, endpoint=endpoint))
    await audit(user, "system.platform.deploy", key, detail=f"force={bool(force)}")
    return {"ok": True, "msg": "已开始部署", "key": key,
            "skipped": True if (platform_deploy.detect(key).get("installed") and not force) else False}


@router.post("/local-platforms/ollama/adopt-models")
async def adopt_ollama_models(user: dict = Depends(admin_user)):
    """把系统目录（~/.ollama/models）里的模型搬到 platforms/ollama/models。"""
    result = await platform_deploy.adopt_ollama_models()
    await audit(user, "system.platform.ollama.adopt", detail=str(result.get("msg", ""))[:300])
    platform_models.invalidate()
    return result


@router.post("/local-platforms/{key}/uninstall")
async def uninstall_platform(key: str, user: dict = Depends(admin_user)):
    """卸载工作台装进 platforms/ 的程序：停进程、关端口、删程序与下载缓存，
    保留 Ollama 的 models 目录和 data/installers 里的安装包。"""
    if key not in platforms.PLATFORMS:
        raise HTTPException(404, "未知平台")
    result = await platform_deploy.uninstall(key)
    await audit(user, "system.platform.uninstall", key, detail=str(result.get("msg", ""))[:300])
    return result


@router.post("/local-platforms/ollama/pull")
async def pull_ollama_model(body: OllamaPullBody, user: dict = Depends(admin_user)):
    """按 Ollama 的 tag 拉模型（qwen2.5:7b 这类），落到 platforms/ollama/models。"""
    try:
        tag = ollama_tags.normalize_tag(body.tag)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result = await platform_deploy.ollama_pull(tag)
    await audit(user, "system.platform.ollama.pull", tag, detail=str(result.get("msg", ""))[:300])
    return result


@router.get("/local-platforms/ollama/pull")
async def pull_ollama_status(tag: str | None = None, user: dict = Depends(admin_user)):
    return platform_deploy.pull_state(tag)


@router.get("/local-platforms/{key}/progress")
async def platform_progress(key: str, user: dict = Depends(admin_user)):
    if key not in platforms.PLATFORMS:
        raise HTTPException(404, "未知平台")
    return {"state": platform_deploy.get_state(key)}


@router.get("/network-check")
async def network_check(user: dict = Depends(admin_user)):
    """检查 GitHub 直连/加速、PyPI 镜像和官网是否可达。"""
    return await installer.network_check()


@router.get("/websearch")
async def get_websearch(user: dict = Depends(admin_user)):
    """联网检索后台配置与运行状态。"""
    return websearch.settings()


@router.put("/websearch")
async def put_websearch(body: WebsearchBody, user: dict = Depends(admin_user)):
    cfg = load_config()
    changed: list[str] = []
    if body.enabled is not None:
        cfg["websearch_enabled"] = bool(body.enabled)
        changed.append("enabled=" + ("on" if body.enabled else "off"))
    if body.max_sources is not None:
        if not 1 <= body.max_sources <= 10:
            raise HTTPException(400, "搜索结果数量需在 1–10 条之间")
        cfg["websearch_max_sources"] = int(body.max_sources)
        changed.append(f"sources={body.max_sources}")
    if body.max_pages is not None:
        if not 0 <= body.max_pages <= 4:
            raise HTTPException(400, "抓取网页数量需在 0–4 篇之间")
        cfg["websearch_max_pages"] = int(body.max_pages)
        changed.append(f"pages={body.max_pages}")
    save_config(cfg)
    websearch.clear_cache()
    await audit(user, "websearch.settings", detail=", ".join(changed) or "未变更")
    return websearch.settings()


@router.post("/websearch/test")
async def test_websearch(body: WebsearchTestBody, user: dict = Depends(admin_user)):
    """用真实检索验证当前开关和抓取设置，返回来源与耗时。"""
    q = body.query.strip()
    if len(q) < 2:
        raise HTTPException(400, "请输入至少 2 个字的检索词")
    current = websearch.settings()
    if not current["enabled"]:
        raise HTTPException(400, "联网检索当前已关闭，请先打开总开关")
    started = time.time()
    try:
        web = await websearch.research(
            q,
            limit=body.max_sources or current["max_sources"],
            pages=body.max_pages if body.max_pages is not None else current["max_pages"],
        )
    except Exception as e:
        raise HTTPException(400, f"检索失败：{str(e)[:160]}")
    cost = int((time.time() - started) * 1000)
    sources = [{"title": s.get("title") or s.get("url", ""), "url": s.get("url", ""),
                "snippet": (s.get("snippet") or "")[:240]}
               for s in (web.get("sources") or [])]
    await audit(user, "websearch.test", q, f"{len(sources)} 条 / {cost}ms",
                "ok" if sources else "fail")
    return {"ok": bool(sources), "query": web.get("query") or q, "sources": sources,
            "error": web.get("error") or "", "ms": cost}


@router.post("/websearch/cache/clear")
async def clear_websearch_cache(user: dict = Depends(admin_user)):
    websearch.clear_cache()
    await audit(user, "websearch.cache.clear")
    return {"ok": True, "cache_entries": websearch.settings()["cache_entries"]}


@router.post("/local-deploy")
async def set_local_deploy(body: LocalDeployBody, user: dict = Depends(admin_user)):
    """开启/关闭本地部署；可同时选择多个平台，不选则默认 llama.cpp。"""
    cfg = load_config()
    selected = platforms.normalize_selected(
        body.platforms if body.platforms is not None else cfg.get("deploy_platforms"))
    if body.endpoints is not None:
        cfg["platform_endpoints"] = platforms.clean_endpoints(body.endpoints, cfg)
    platform_models.invalidate()
    proxy = _clean_github_proxy(body.github_proxy)
    if proxy is not None:
        cfg["github_proxy"] = proxy
    cfg["deploy_platforms"] = selected

    if not body.enabled:
        cfg["local_enabled"] = False
        save_config(cfg)
        await llama.server.stop()
        srv = await llama.server.status()
        items = await _platform_items(cfg, selected, srv)
        warning = ""
        if srv.get("healthy") and srv.get("external"):
            warning = "外部 llama-server 仍在运行；工作台已停止使用本地模型，但未强制结束外部进程"
        await audit(user, "system.local.disable", detail=warning or "已关闭本地部署")
        return {"ok": True, "enabled": False, "started": False, "msg": warning or "本地部署已关闭",
                "server": srv, "selected": selected, "platforms": items}

    cfg["local_enabled"] = True
    save_config(cfg)
    srv = await llama.server.status()
    notes: list[str] = []

    if "llama.cpp" in selected:
        if srv.get("healthy"):
            notes.append("llama.cpp 已在运行")
        elif not hardware.llama_info()["installed"]:
            notes.append("llama.cpp 还没安装，请在平台卡点“一键部署”")
        else:
            row = await _pick_local_model(cfg)
            if not row:
                notes.append("还没有下载完整的 GGUF 模型，llama.cpp 暂未启动")
            else:
                ok, msg = await llama.server.start(row["key"])
                notes.append(msg if ok else f"llama.cpp 启动失败：{msg}")

    srv = await llama.server.status()
    items = await _platform_items(cfg, selected, srv, True)
    # 开关不只管 llama.cpp：已经装好的 Ollama / LM Studio / vLLM 也一起拉起来
    import asyncio
    starting: list[str] = []
    for p in items:
        if p["key"] in ("llama.cpp", "custom") or not p.get("selected"):
            continue
        if p.get("installed") and not p.get("healthy") and not platform_deploy.is_running(p["key"]):
            asyncio.create_task(platform_deploy.start(p["key"]))
            starting.append(p["name"])
    if starting:
        notes.append("正在启动：" + "、".join(starting) + "（进度见平台卡）")
    srv = await llama.server.status()
    healthy_external = [p["name"] for p in items
                        if p["kind"] == "external" and p["selected"] and p["healthy"]]
    if healthy_external:
        notes.append("外部平台已连接：" + "、".join(healthy_external))
    started = bool(srv.get("healthy")) or bool(healthy_external)
    if not started:
        notes.append("当前没有检测到可用的本地平台，请先启动平台服务")

    msg = "；".join(notes)
    await audit(user, "system.local.enable" if started else "system.local.enable",
                detail=f"平台 {','.join(selected)}；{msg}")
    return {"ok": True, "enabled": True, "started": started, "msg": msg,
            "server": srv, "selected": selected, "platforms": items}









