"""模型管理：清单、下载、加载、上传、删除。"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import load_config, model_file_path, save_config
from ..db import (MODEL_CATALOG_EXTRAS, MODEL_SEED, audit, execute, executemany,
                  fetch_all, fetch_one, model_url)
from ..security import admin_user, current_user
from ..services import access, hardware, llama

router = APIRouter(prefix="/api/models", tags=["models"])

MAX_MODEL_BYTES = int(os.getenv("WORKBENCH_MAX_MODEL_UPLOAD_GB") or 8) * 1024 ** 3
MIN_DISK_FREE = 512 * 1024 ** 2

CATEGORY_LABELS = {
    "text": "文字 / 对话",
    "code": "代码 / 编程",
    "vision": "多模态 / 视觉",
    "ocr": "OCR / 文档",
    "image": "绘画 / 图像",
    "video": "视频生成",
    "audio": "语音 / 音频",
    "embedding": "向量 / 检索",
    "rerank": "重排序",
}


class LoadBody(BaseModel):
    key: str


class AddBody(BaseModel):
    key: str
    label: str
    family: str = "自定义"
    note: str = ""
    filename: str
    repo: str = ""
    total_bytes: int = 0
    fit: str = "unknown"


@router.get("")
async def catalog(user: dict = Depends(current_user)):
    cfg = load_config()
    local_enabled = bool(cfg.get("local_enabled", True))
    rows = await fetch_all("SELECT * FROM models ORDER BY sort, key")
    status = await llama.server.status()
    prof = hardware.profile()
    items = []
    for r in rows:
        installable = bool(r.get("installable", 1))
        category = r.get("category") or "text"
        engine = r.get("engine") or "llama.cpp"
        if installable:
            path = model_file_path(cfg, r["filename"])
            part = path.with_suffix(path.suffix + ".part")
            exists = path.exists()
            size = path.stat().st_size if exists else (part.stat().st_size if part.exists() else 0)
            expected = int(r["total_bytes"] or 0)
            complete = bool(exists and (not expected or size + 1024 >= expected))
            partial = bool(part.exists() or (exists and not complete))
            advice = hardware.advise(expected or size, prof, int(cfg.get("ctx", 8192)))
        else:
            size, expected, complete, partial = 0, 0, False, False
            advice = {"level": "unknown", "label": "未接入",
                      "text": f"需要 {engine} 独立引擎，当前只做清单收录，不能一键下载或加载"}
        items.append({
            **r,
            "installable": installable,
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "engine": engine,
            "homepage": r.get("homepage") or "",
            "downloaded": complete,
            "partial": partial,
            "bytes": size,
            "pct": round(size * 100 / expected, 1) if expected else (100 if complete else 0),
            "available": local_enabled,
            "loaded": bool(installable and local_enabled and status["model"] in (r["key"], r.get("alias") or "")),
            "owned_by": "local",
            "download_url": model_url(r["repo"] or "", r["filename"]) if installable else "",
            "advice": advice,
        })
    for pool in await fetch_all("SELECT name,note FROM cluster_pools WHERE enabled=1 ORDER BY id"):
        pool_name = str(pool.get("name") or "").strip()
        if not pool_name or any(m["key"] == pool_name for m in items):
            continue
        items.append({
            "key": pool_name,
            "alias": "", "label": f"算力池 · {pool_name}", "family": "多机算力池",
            "note": pool.get("note") or "多台机器上的同一个模型，按当前并发自动分配",
            "filename": "", "total_bytes": 0, "repo": "", "fit": "unknown", "sort": 900,
            "category": "text", "category_label": CATEGORY_LABELS["text"],
            "engine": "cluster", "installable": False, "homepage": "",
            "downloaded": True, "partial": False, "bytes": 0, "pct": 100,
            "available": True, "loaded": True, "owned_by": "cluster", "download_url": "",
            "advice": {"level": "good", "label": "算力池",
                       "text": "由控制台「算力」页统一调度；单次请求仍在一台机器上运行"},
        })
    return {
        "items": await access.filter_catalog(items, user), "server": status,
        "models_dir": cfg["models_dir"], "local_enabled": local_enabled,
        "hardware": {
            "cpu": prof["cpu"], "cores": prof["cores"],
            "ram_total_gb": prof["ram_total_gb"], "ram_free_gb": prof["ram_free_gb"],
            "gpus": prof["gpus"], "llama_installed": prof["llama"]["installed"],
        },
    }


@router.post("/refresh")
async def refresh_catalog(user: dict = Depends(admin_user)):
    """补回内置清单缺失项，并发现模型目录里尚未登记的新 GGUF；已有模型不覆盖。"""
    rows = await fetch_all("SELECT key,filename FROM models")
    existing = {r["key"] for r in rows}
    existing_files = {Path(r["filename"]).name.lower() for r in rows if r.get("filename")}
    missing = []
    for m in [*MODEL_SEED, *MODEL_CATALOG_EXTRAS]:
        if m["key"] in existing:
            continue
        existing.add(m["key"])
        missing.append((
            m["key"], m.get("alias", ""), m["label"], m["family"], m["note"],
            m.get("filename", ""), int(m.get("total_bytes", 0)), m.get("repo", ""),
            m.get("fit", "unknown"), int(m.get("sort", 0)),
            m.get("category", "text"), m.get("engine", "llama.cpp"),
            m.get("homepage", ""), int(m.get("installable", 1)),
        ))

    discovered = 0
    cfg = load_config()
    models_dir = Path(cfg["models_dir"])
    if models_dir.is_dir():
        for path in sorted(models_dir.glob("*.gguf")):
            name = path.name
            if name.lower() in existing_files:
                continue
            key = path.stem.lower()[:40]
            if key in existing:
                continue
            existing.add(key)
            existing_files.add(name.lower())
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            missing.append((key, "", path.stem, "本地文件", "从模型目录自动发现", name,
                            size, "", "unknown", 99, "text", "llama.cpp", "", 1))
            discovered += 1

    if missing:
        await executemany(
            "INSERT OR IGNORE INTO models(key,alias,label,family,note,filename,total_bytes,repo,fit,sort,"
            "category,engine,homepage,installable) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            missing,
        )
    total = (await fetch_one("SELECT COUNT(*) c FROM models"))["c"]
    detail = f"补充 {len(missing)} 个，目录发现 {discovered} 个"
    await audit(user, "model.catalog.refresh", detail=detail)
    msg = f"已补充 {len(missing)} 个缺失模型" if missing else "模型清单已是最新"
    if discovered:
        msg += f"，其中 {discovered} 个来自模型目录"
    return {"ok": True, "added": len(missing), "discovered": discovered,
            "total": total, "msg": msg}


@router.post("/{key}/download")
async def download(key: str, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM models WHERE key=?", (key,))
    if not row:
        raise HTTPException(404, "模型不存在")
    if not int(row.get("installable", 1)):
        raise HTTPException(400, f"该模型需要独立引擎（{row.get('engine') or '未接入'}），当前不能通过 llama.cpp 一键下载")
    res = await llama.download_model(key)
    if not res.get("ok"):
        raise HTTPException(400, res.get("msg", "下载失败"))
    await audit(user, "model.download", key)
    return res


@router.get("/{key}/progress")
async def progress(key: str, user: dict = Depends(current_user)):
    return await llama.download_progress(key)


@router.post("/select")
async def select(body: LoadBody, user: dict = Depends(current_user)):
    """用户选择模型时按需切换到该模型；只允许本人可用且已下载完整的模型。"""
    if not await access.can_use(user, body.key):
        raise HTTPException(403, "该模型未对当前用户开放")
    row = await fetch_one("SELECT * FROM models WHERE key=?", (body.key,))
    if not row:
        raise HTTPException(404, "模型不存在")
    if not int(row.get("installable", 1)):
        raise HTTPException(400, "该模型需要独立引擎，不能在当前工作台切换")
    cfg = load_config()
    path = model_file_path(cfg, row["filename"])
    expected = int(row["total_bytes"] or 0)
    if not path.exists():
        raise HTTPException(400, "模型尚未下载")
    if expected and path.stat().st_size + 1024 < expected:
        raise HTTPException(400, "模型尚未下载完整")
    status = await llama.server.status()
    if status.get("healthy") and status.get("model") in (body.key, row.get("alias") or ""):
        return {"ok": True, "msg": "模型已加载", "status": status}
    ok, msg = await llama.server.start(body.key)
    await audit(user, "model.select" if ok else "model.select.fail", body.key, msg,
                "ok" if ok else "fail")
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "msg": msg, "status": await llama.server.status()}


@router.post("/load")
async def load(body: LoadBody, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM models WHERE key=?", (body.key,))
    if not row:
        raise HTTPException(404, "模型不存在")
    if not int(row.get("installable", 1)):
        raise HTTPException(400, f"该模型需要独立引擎（{row.get('engine') or '未接入'}），当前不能由 llama.cpp 加载")
    ok, msg = await llama.server.start(body.key)
    await audit(user, "model.load" if ok else "model.load.fail", body.key, msg, "ok" if ok else "fail")
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "msg": msg, "status": await llama.server.status()}


@router.post("/unload")
async def unload(user: dict = Depends(admin_user)):
    await llama.server.stop()
    cfg = load_config()
    cfg["local_enabled"] = False
    save_config(cfg)
    await audit(user, "model.unload", detail="关闭本地部署并停止模型服务")
    return {"ok": True}


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(admin_user)):
    name = Path(file.filename or "").name
    if not name.lower().endswith(".gguf"):
        raise HTTPException(400, "只支持 .gguf 文件")
    if file.size and file.size > MAX_MODEL_BYTES:
        raise HTTPException(413, f"模型文件超过上限 {MAX_MODEL_BYTES // 1024 ** 3}GB")
    cfg = load_config()
    dest = model_file_path(cfg, name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dest.parent).free
    if free < MIN_DISK_FREE:
        raise HTTPException(507, "磁盘剩余空间不足 512MB，无法上传")
    tmp = dest.with_name(dest.name + ".part")
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := await file.read(1024 * 512):
                size += len(chunk)
                if size > MAX_MODEL_BYTES:
                    raise HTTPException(413, f"模型文件超过上限 {MAX_MODEL_BYTES // 1024 ** 3}GB")
                out.write(chunk)
        if shutil.disk_usage(dest.parent).free < MIN_DISK_FREE:
            raise HTTPException(507, "磁盘剩余空间不足 512MB")
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    key = Path(name).stem.lower()[:40]
    exists = await fetch_one("SELECT key FROM models WHERE key=?", (key,))
    if not exists:
        await execute(
            "INSERT INTO models(key,label,family,note,filename,total_bytes,repo,fit,sort) VALUES(?,?,?,?,?,?,?,?,?)",
            (key, Path(name).stem, "上传", "本地上传的模型", name,
             size, "", "unknown", 99))
    await audit(user, "model.upload", name, f"{size} bytes")
    return {"ok": True, "key": key, "bytes": size}


@router.delete("/{key}")
async def delete_model(key: str, remove_file: bool = False, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT * FROM models WHERE key=?", (key,))
    if not row:
        raise HTTPException(404, "模型不存在")
    if remove_file:
        path = model_file_path(load_config(), row["filename"])
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            raise HTTPException(400, f"删除文件失败：{e}")
    await execute("DELETE FROM models WHERE key=?", (key,))
    await audit(user, "model.delete", key, f"remove_file={remove_file}")
    return {"ok": True}


@router.patch("/{key}")
async def edit_model(key: str, body: AddBody, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT key FROM models WHERE key=?", (key,))
    if not row:
        raise HTTPException(404, "模型不存在")
    await execute(
        "UPDATE models SET label=?,family=?,note=?,filename=?,repo=?,total_bytes=?,fit=? WHERE key=?",
        (body.label, body.family, body.note, body.filename, body.repo, body.total_bytes, body.fit, key))
    return {"ok": True}

