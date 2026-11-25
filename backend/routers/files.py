"""聊天附件上传与预览、生成文件下载。"""
from __future__ import annotations

from pathlib import Path
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import EXPORT_DIR, UPLOAD_DIR
from ..db import audit, fetch_all, fetch_one
from ..security import current_user
from ..services import attachments, docgen, library, retention

router = APIRouter(prefix="/api/chat/files", tags=["chat-files"])
exports_router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("")
async def upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "文件是空的")
    try:
        row = await attachments.save(user["id"], file.filename or "未命名", file.content_type or "", raw)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"文件处理失败：{e}")
    full = await attachments.get(user["id"], row["id"])
    try:
        imported = await library.import_chat_upload(
            user["id"], row.get("name") or "未命名", str((full or {}).get("text_content") or ""))
    except Exception as e:
        imported = {"status": "skip", "reason": f"加入资料库失败：{e}"}
    row["library"] = imported
    if imported.get("status") == "added":
        try:
            await audit(user, "library.chat_import", row.get("name"), f"id={imported['doc_id']}")
        except Exception:
            pass
    return row


@router.get("/{file_id}")
async def download(file_id: int, user: dict = Depends(current_user)):
    row = await attachments.get(user["id"], file_id)
    if not row:
        raise HTTPException(404, "文件不存在")
    path = UPLOAD_DIR / str(row["stored_name"])
    if not path.exists():
        raise HTTPException(404, "文件已清理")
    return FileResponse(path, filename=row["name"], media_type=row.get("mime") or None)


@router.delete("/{file_id}")
async def remove(file_id: int, user: dict = Depends(current_user)):
    if not await attachments.delete(user["id"], file_id):
        raise HTTPException(404, "文件不存在")
    return {"ok": True}


@exports_router.get("/generated/{file_id}")
async def download_generated(file_id: int, user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT id,user_id,name,stored_name,mime,size,expires_at,deleted_at FROM generated_files "
        "WHERE id=? AND user_id=?", (file_id, user["id"]))
    if not row:
        raise HTTPException(404, "文件不存在")
    status = retention.expiry_fields(row.get("expires_at"), row.get("deleted_at") or 0)
    if status["cleaned"]:
        raise HTTPException(
            410, f"文件 {status['deleted_text'] or '已'} 自动清理，请重新生成")
    if status["expired"]:
        raise HTTPException(
            410, f"文件已于 {status['expires_text'] or '到期时间'} 到期，请重新生成")
    stored = Path(str(row["stored_name"] or "")).name
    path = EXPORT_DIR / stored
    if not stored or not path.exists():
        raise HTTPException(404, "文件已清理，请重新生成")
    return FileResponse(path, filename=row["name"], media_type=row.get("mime") or None)


@exports_router.get("/generated")
async def list_generated(user: dict = Depends(current_user), limit: int = 50):
    now = time.time()
    rows = await fetch_all(
        "SELECT id,name,kind,size,created_at,expires_at,deleted_at,conversation_id "
        "FROM generated_files WHERE user_id=? AND deleted_at=0 "
        "AND (expires_at=0 OR expires_at>?) ORDER BY id DESC LIMIT ?",
        (user["id"], now, max(1, min(limit, 200))))
    items = [docgen.decorate_row(dict(r), now) for r in (rows or [])]
    days = retention.retention_days()
    return {
        "items": items,
        "days": days,
        "warn_days": retention.WARN_DAYS,
        "expiring_soon": sum(1 for item in items if item.get("expiring_soon")),
    }

