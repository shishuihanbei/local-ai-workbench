"""控制台附件解析：上传记录、OCR 状态、重新解析任务。"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import UPLOAD_DIR
from ..db import audit, fetch_all, fetch_one
from ..security import admin_user
from ..services import attachments, parse_jobs

router = APIRouter(prefix="/api/admin/uploads", tags=["admin-uploads"])


class ReparseBody(BaseModel):
    ids: list[int] = []
    only_empty: bool = True
    limit: int = 50


async def _stats_async() -> dict:
    cutoff = time.time() - 86400
    row = await fetch_one(
        "SELECT COUNT(*) total,"
        "SUM(CASE WHEN TRIM(COALESCE(text_content,''))='' THEN 1 ELSE 0 END) empty,"
        "SUM(CASE WHEN TRIM(COALESCE(text_content,''))<>'' THEN 1 ELSE 0 END) parsed,"
        "SUM(CASE WHEN COALESCE(parse_error,'')<>'' AND parse_error NOT LIKE '未提取到正文%' THEN 1 ELSE 0 END) errors,"
        "SUM(CASE WHEN kind='image' THEN 1 ELSE 0 END) images,"
        "SUM(CASE WHEN kind='document' THEN 1 ELSE 0 END) documents,"
        "SUM(CASE WHEN created_at>=? THEN 1 ELSE 0 END) recent "
        "FROM uploads", (cutoff,)) or {}
    return {k: int(row.get(k) or 0) for k in
            ("total", "empty", "parsed", "errors", "images", "documents", "recent")}


@router.get("")
async def list_uploads(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                       q: str = "", status: str = "all", user: dict = Depends(admin_user)):
    where: list[str] = []
    params: list = []
    if q.strip():
        where.append("(u.name LIKE ? OR users.username LIKE ?)")
        like = f"%{q.strip()[:80]}%"
        params.extend([like, like])
    if status == "empty":
        where.append("TRIM(COALESCE(u.text_content,''))=''")
    elif status == "parsed":
        where.append("TRIM(COALESCE(u.text_content,''))<>''")
    elif status == "error":
        where.append("COALESCE(u.parse_error,'')<>'' AND u.parse_error NOT LIKE '未提取到正文%'")
    elif status == "image":
        where.append("u.kind='image'")
    elif status == "document":
        where.append("u.kind='document'")
    elif status == "text":
        where.append("u.kind='text'")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = await fetch_one(
        "SELECT COUNT(*) c FROM uploads u "
        "LEFT JOIN users ON users.id=u.user_id" + clause, tuple(params))
    total = int((total_row or {}).get("c") or 0)
    rows = await fetch_all(
        "SELECT u.id,u.user_id,u.name,u.mime,u.size,u.kind,u.created_at,u.parsed_at,"
        "u.parse_ms,u.parse_error,LENGTH(TRIM(COALESCE(u.text_content,''))) chars,"
        "SUBSTR(REPLACE(REPLACE(COALESCE(u.text_content,''),CHAR(10),' '),CHAR(13),' '),1,180) preview,"
        "users.username "
        "FROM uploads u LEFT JOIN users ON users.id=u.user_id" + clause +
        " ORDER BY u.id DESC LIMIT ? OFFSET ?",
        tuple(params + [size, (page - 1) * size]))
    items = []
    for r in rows:
        name = str(r.get("name") or "未命名")
        suffix = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
        items.append({
            "id": int(r["id"]), "user_id": int(r.get("user_id") or 0),
            "username": r.get("username") or "",
            "name": name, "suffix": suffix, "mime": r.get("mime") or "",
            "size": int(r.get("size") or 0), "kind": r.get("kind") or "file",
            "chars": int(r.get("chars") or 0), "preview": r.get("preview") or "",
            "created_at": float(r.get("created_at") or 0),
            "parsed_at": float(r.get("parsed_at") or 0),
            "parse_ms": int(r.get("parse_ms") or 0),
            "parse_error": r.get("parse_error") or "",
        })
    return {"items": items, "total": total, "page": page, "size": size,
            "stats": await _stats_async(), "engine": attachments.engine_status()}


@router.get("/engine")
async def engine(user: dict = Depends(admin_user)):
    stats = await _stats_async()
    return {**attachments.engine_status(), "stats": stats}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, user: dict = Depends(admin_user)):
    job = parse_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "解析任务不存在或服务已重启")
    return job


@router.post("/reparse")
async def reparse(body: ReparseBody, user: dict = Depends(admin_user)):
    ids = [int(x) for x in body.ids if int(x) > 0]
    if not ids:
        limit = max(1, min(int(body.limit or 50), 200))
        if body.only_empty:
            rows = await fetch_all(
                "SELECT id FROM uploads WHERE TRIM(COALESCE(text_content,''))='' "
                "ORDER BY id ASC LIMIT ?", (limit,))
        else:
            rows = await fetch_all(
                "SELECT id FROM uploads ORDER BY id DESC LIMIT ?", (limit,))
        ids = [int(r["id"]) for r in rows]
    if not ids:
        raise HTTPException(400, "没有待解析的附件")
    try:
        job = parse_jobs.start(ids)
    except parse_jobs.JobBusy as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "uploads.reparse", detail=f"附件 {len(ids)} 个，任务 {job['id']}")
    return job


@router.get("/{file_id}/text")
async def attachment_text(file_id: int, user: dict = Depends(admin_user)):
    row = await fetch_one(
        "SELECT id,name,kind,text_content,parse_error,parsed_at,parse_ms "
        "FROM uploads WHERE id=?", (file_id,))
    if not row:
        raise HTTPException(404, "附件不存在")
    text = str(row.get("text_content") or "")
    return {"id": int(row["id"]), "name": row.get("name") or "", "kind": row.get("kind") or "",
            "text": text[:attachments.MAX_TEXT], "chars": len(text),
            "parse_error": row.get("parse_error") or "",
            "parsed_at": float(row.get("parsed_at") or 0),
            "parse_ms": int(row.get("parse_ms") or 0)}


@router.get("/{file_id}/file")
async def attachment_file(file_id: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT name,stored_name FROM uploads WHERE id=?", (file_id,))
    if not row:
        raise HTTPException(404, "附件不存在")
    stored = Path(str(row.get("stored_name") or "")).name
    path = (UPLOAD_DIR / stored).resolve()
    if not path.exists() or path.parent != UPLOAD_DIR.resolve():
        raise HTTPException(404, "原文件已丢失")
    return FileResponse(path, filename=str(row.get("name") or stored))
