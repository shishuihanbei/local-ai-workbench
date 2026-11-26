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
                  fetch_all, fetch_one, model_repo, model_url)
from ..security import admin_user, current_user
from ..services import (access, engine_install, engines, hardware, hf_models, llama,
                        model_usage, platform_models)

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
    force: bool = False


class SelectBody(BaseModel):
    key: str
    force: bool = False


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
    dl_rows = await fetch_all(
        "SELECT d.model_key, d.status, d.bytes, d.total, d.error, d.started_at "
        "FROM downloads d JOIN (SELECT model_key, MAX(id) AS mid FROM downloads GROUP BY model_key) x "
        "ON d.id = x.mid")
    dl_map = {r["model_key"]: r for r in dl_rows}
    status = await llama.server.status()
    prof = hardware.profile()
    engine_state = engines.status(prof)
    items = []
    for r in rows:
        installable = bool(r.get("installable", 1))
        category = r.get("category") or "text"
        engine = r.get("engine") or "llama.cpp"
        repo = model_repo(r["key"], r.get("repo") or "")
        engine_info = None
        if installable:
            path = model_file_path(cfg, r["filename"])
            part = path.with_suffix(path.suffix + ".part")
            expected = int(r["total_bytes"] or 0)
            exists = path.exists()
            part_exists = part.exists()
            # 有 .part 就说明有一轮下载在跑（或刚中断）：进度必须以 .part 为准。
            # 旧的不完整 .gguf 只是历史残留，若拿它算进度，界面会永远停在旧百分比。
            if part_exists:
                size = part.stat().st_size
                complete, partial = False, True
            elif exists:
                size = path.stat().st_size
                complete = bool(not expected or size + 1024 >= expected)
                partial = not complete
            else:
                size, complete, partial = 0, False, False
            advice = hardware.advise(expected or size, prof, int(cfg.get("ctx", 8192)))
            dl = dl_map.get(r["key"]) or {}
            if llama.download_active(r["key"]):
                dl_state = "running"
            elif dl.get("status") == "running":
                dl_state = "interrupted"      # 记录停在 running 但进程里没任务：中断过，可继续
            elif dl.get("status") == "error" and not complete:
                dl_state = "error"
            elif complete:
                dl_state = "done"
            elif partial:
                dl_state = "interrupted"
            else:
                dl_state = "none"
            dl_total = expected or int(dl.get("total") or 0)
            dl_error = str(dl.get("error") or "")
            dl_started = float(dl.get("started_at") or 0)
            pct_val = min(100, round(size * 100 / expected, 1)) if expected else (100 if complete else 0)
        else:
            engine_info = engines.describe(engine, engine_state)
            expected = 0
            if repo:
                hf = hf_models.status(r["key"])
                size = int(hf.get("bytes") or 0)
                complete = bool(hf.get("marker"))
                partial = bool(hf_models.partial(cfg, r["key"]))
                if hf.get("running"):
                    dl_state = "running"
                elif complete:
                    dl_state = "done"
                elif hf.get("error"):
                    dl_state = "error"
                elif partial:
                    dl_state = "interrupted"
                else:
                    dl_state = "none"
                dl_total = int(hf.get("total_bytes") or 0)
                dl_error = str(hf.get("error") or "")
                dl_started = float(hf.get("started_at") or 0)
                pct_val = min(100, round(float(hf.get("pct") or 0), 1))
            else:
                size, complete, partial = 0, False, False
                dl_state, dl_total, dl_error, dl_started, pct_val = "none", 0, "", 0.0, 0
            label = f"推荐 {engine_info['recommend']}" if engine_info["ready"] else "需先装引擎"
            advice = {"level": "good" if engine_info["ready"] else "warn",
                      "label": label, "text": engine_info["text"]}
        items.append({
            **r,
            "installable": installable,
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "engine": engine,
            "engine_repo": repo,
            "engine_ready": bool(engine_info and engine_info["ready"]),
            "engine_recommend": engine_info["recommend"] if engine_info else "",
            "engine_recommend_key": engine_info.get("recommend_key", "") if engine_info else "",
            "engine_package": engine_info.get("package", "") if engine_info else "",
            "engine_gpu": bool(engine_info and engine_info["gpu"]),
            "engine_text": engine_info["text"] if engine_info else "",
            "homepage": r.get("homepage") or "",
            "downloaded": complete,
            "partial": partial,
            "bytes": size,
            "pct": pct_val,
            "download": {"state": dl_state, "pct": pct_val, "bytes": size,
                         "total": dl_total, "error": dl_error,
                         "started_at": dl_started},
            "available": local_enabled,
            "loaded": bool(installable and local_enabled and status["model"] in (r["key"], r.get("alias") or "")),
            "owned_by": "local",
            "download_url": model_url(repo, r["filename"]) if installable else "",
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
    if local_enabled:
        for platform_model in await platform_models.reachable(cfg):
            if any(m["key"] == platform_model["key"] for m in items):
                continue
            items.append(platform_model)
    return {
        "items": await access.filter_catalog(items, user), "server": status,
        "models_dir": cfg["models_dir"], "local_enabled": local_enabled,
        "hardware": {
            "cpu": prof["cpu"], "cores": prof["cores"],
            "ram_total_gb": prof["ram_total_gb"], "ram_free_gb": prof["ram_free_gb"],
            "gpus": prof["gpus"], "llama_installed": prof["llama"]["installed"],
        },
        "engines": {
            "installed": engine_state["installed"],
            "gpu": engine_state["gpu"], "gpu_names": engine_state["gpu_names"],
        },
        "engine_catalog": [
            {**item, "progress": engine_install.status(item["key"])}
            for item in engines.catalog(engine_state)
        ],
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
        repo = model_repo(row["key"], row.get("repo") or "")
        if not repo:
            raise HTTPException(400, "这个模型还没有配置一键下载源，请点「查看项目」到项目页手动下载")
        engine = row.get("engine") or ""
        state = engines.status()
        if not engines.ready_for(engine, state):
            rec = engines.recommend(engine, state)
            raise HTTPException(400, f"本机还没安装 {rec['name']}，下载按钮暂不可用。{rec['text']}")
        res = hf_models.start(key, repo)
        if not res.get("ok"):
            raise HTTPException(400, res.get("msg", "下载失败"))
        await audit(user, "model.download.hf", key, repo)
        return res
    res = await llama.download_model(key)
    if not res.get("ok"):
        raise HTTPException(400, res.get("msg", "下载失败"))
    await audit(user, "model.download", key)
    return res


@router.get("/{key}/progress")
async def progress(key: str, user: dict = Depends(current_user)):
    row = await fetch_one("SELECT installable FROM models WHERE key=?", (key,))
    if row and not int(row.get("installable", 1)):
        return hf_models.status(key)
    return await llama.download_progress(key)


def _refuse_if_busy(key: str, user: dict, force: bool, status: dict) -> None:
    """别人正在用本地模型回答时拒绝切换，返回 409 让前端选等待或强制。"""
    if force:
        return
    holders = model_usage.busy(str(user.get("username") or ""))
    if not holders:
        return
    raise HTTPException(409, detail={
        "code": "model_busy",
        "message": "有会话正在用本地模型回答，切换会中断它",
        "target": key,
        "running": str(status.get("model") or ""),
        "items": holders,
    })


@router.get("/in-use")
async def in_use(user: dict = Depends(current_user)):
    """当前本地模型被谁、被几个会话占用；前端切换前用它判断要不要等待。"""
    status = await llama.server.status()
    return {
        "running": str(status.get("model") or ""),
        "healthy": bool(status.get("healthy")),
        "busy": model_usage.busy(str(user.get("username") or "")),
    }


@router.post("/select")
async def select(body: SelectBody, user: dict = Depends(current_user)):
    """用户选择模型时按需切换到该模型；只允许本人可用且已下载完整的模型。"""
    if not await access.can_use(user, body.key):
        raise HTTPException(403, "该模型未对当前用户开放")
    cfg = load_config()
    if not bool(cfg.get("local_enabled", True)):
        raise HTTPException(400, "本地部署已关闭")
    platform_model = next((m for m in await platform_models.reachable(cfg)
                           if m["key"] == body.key), None)
    if platform_model:
        return {"ok": True, "msg": f"已切换到 {platform_model['source_platform']} 模型",
                "status": {"model": body.key, "healthy": True, "running": True}}
    row = await fetch_one("SELECT * FROM models WHERE key=?", (body.key,))
    if not row:
        raise HTTPException(404, "模型不存在")
    if not int(row.get("installable", 1)):
        raise HTTPException(400, "该模型需要独立引擎，不能在当前工作台切换")
    path = model_file_path(cfg, row["filename"])
    expected = int(row["total_bytes"] or 0)
    if not path.exists():
        raise HTTPException(400, "模型尚未下载")
    if expected and path.stat().st_size + 1024 < expected:
        raise HTTPException(400, "模型尚未下载完整")
    status = await llama.server.status()
    if status.get("healthy") and status.get("model") in (body.key, row.get("alias") or ""):
        return {"ok": True, "msg": "模型已加载", "status": status}
    _refuse_if_busy(body.key, user, body.force, status)
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
    status = await llama.server.status()
    if status.get("healthy") and status.get("model") in (body.key, row.get("alias") or ""):
        return {"ok": True, "msg": "模型已加载", "status": status}
    _refuse_if_busy(body.key, user, body.force, status)
    ok, msg = await llama.server.start(body.key)
    await audit(user, "model.load" if ok else "model.load.fail", body.key, msg, "ok" if ok else "fail")
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "msg": msg, "status": await llama.server.status()}


@router.post("/unload")
async def unload(force: bool = False, user: dict = Depends(admin_user)):
    holders = model_usage.busy("")
    if holders and not force:
        raise HTTPException(409, detail={
            "code": "model_busy",
            "message": "有会话正在用本地模型回答，卸载会中断它",
            "running": holders[0]["model"],
            "items": holders,
        })
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

