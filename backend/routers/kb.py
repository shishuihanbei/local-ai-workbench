"""知识库接口：管理员公共库 + 用户个人库。"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import load_config, save_config
from ..db import audit, execute, fetch_one
from ..security import admin_user, current_user
from ..services import attachments, kb

router = APIRouter(prefix="/api/kb", tags=["kb"])
my_router = APIRouter(prefix="/api/my/kb", tags=["my-kb"])

TEXT_SUFFIX = ("txt", "md", "markdown", "csv", "json", "log", "py", "html", "htm")
DOC_SUFFIX = ("pdf", "docx", "xlsx", "xlsm", "xls", "pptx")
IMAGE_SUFFIX = tuple(sorted(attachments.IMAGE_EXTS))
ALLOWED_SUFFIX = TEXT_SUFFIX + DOC_SUFFIX + IMAGE_SUFFIX
MAX_PERSONAL_DOCS = 200


class MyKbSettings(BaseModel):
    personal_enabled: bool | None = None
    use_public: bool | None = None
    use_personal: bool | None = None


def _kb_backup_payload() -> dict:
    return {
        "format": "workbench-kb-backup",
        "format_version": 1,
        "exported_at": time.time(),
        "count": 0,
        "docs": [],
    }


async def _read_upload(file: UploadFile) -> tuple[str, str]:
    name = file.filename or "未命名"
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(400, f"暂不支持 .{suffix}，请转成 docx/pdf/xlsx/图片等常见格式后再传")
    raw = await file.read()
    if len(raw) > attachments.MAX_BYTES:
        raise HTTPException(400, "文件过大（上限 20MB）")
    if suffix in DOC_SUFFIX or suffix in IMAGE_SUFFIX:
        text = await asyncio.to_thread(attachments.extract_text, name, suffix, raw)
    else:
        text = None
        for enc in ("utf-8", "gb18030", "utf-16"):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            raise HTTPException(400, "无法识别文件编码")
    if not (text or "").strip():
        raise HTTPException(400, "未能提取正文：图片需有清晰文字；扫描版 PDF 请确认文字层或改用图片上传")
    return name, text


async def _ensure_personal_room(user_id: int) -> None:
    total = await fetch_one(
        "SELECT COUNT(*) c FROM kb_docs WHERE module='kb' AND scope='personal' AND user_id=?", (user_id,))
    if int((total or {}).get("c", 0)) >= MAX_PERSONAL_DOCS:
        raise HTTPException(400, f"个人知识库最多 {MAX_PERSONAL_DOCS} 篇，请先删掉不用的")


# ------------------------------------------------------------------ 公共库（仅管理员）
@router.get("")
async def overview(scope: str = "all", user_id: int | None = None, q: str = "",
                   user: dict = Depends(admin_user)):
    cfg = load_config()
    data = await kb.stats(scope, user_id, q)
    totals = await kb.totals()
    return {**data, **totals, "enabled": bool(cfg.get("kb_enabled")),
            "top_k": cfg.get("kb_top_k", 3)}


@router.post("/text")
async def add_text(title: str = Form(...), content: str = Form(...),
                   user: dict = Depends(admin_user)):
    try:
        res = await kb.add_document(user["id"], title, "manual", content, scope="global")
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "kb.add", title, f"{res['chunks']} 段")
    return res


@router.post("/upload")
async def upload(file: UploadFile = File(...), user: dict = Depends(admin_user)):
    name, text = await _read_upload(file)
    res = await kb.add_document(user["id"], name, name, text, scope="global")
    await audit(user, "kb.upload", name, f"{res['chunks']} 段")
    return res


@router.get("/doc/{doc_id}")
async def document_detail(doc_id: int, user: dict = Depends(admin_user)):
    doc = await kb.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return doc


@router.delete("/{doc_id}")
async def delete(doc_id: int, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT title,scope,user_id FROM kb_docs WHERE id=?", (doc_id,))
    if not row:
        raise HTTPException(404, "文档不存在")
    await kb.delete_document(doc_id)
    await audit(user, "kb.delete", row["title"],
                f"scope={row['scope']} user={row['user_id']}")
    return {"ok": True}


@router.get("/export")
async def export_backup(user: dict = Depends(admin_user)):
    docs = await kb.export_documents("all")
    payload = _kb_backup_payload()
    payload["count"] = len(docs)
    payload["docs"] = docs
    payload["scope"] = "all"
    filename = time.strftime("workbench-kb-%Y%m%d-%H%M%S.json")
    await audit(user, "kb.backup", detail=f"{len(docs)} 篇（公共+个人）")
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
async def restore_backup(file: UploadFile = File(...), user: dict = Depends(admin_user)):
    name = file.filename or "kb-backup.json"
    if not name.lower().endswith(".json"):
        raise HTTPException(400, "只支持知识库 JSON 备份文件")
    raw = await file.read()
    if len(raw) > 16 * 1024 * 1024:
        raise HTTPException(400, "备份文件过大（上限 16MB）")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(400, "备份文件不是合法的 UTF-8 JSON")
    if not isinstance(payload, dict) or payload.get("format") != "workbench-kb-backup":
        raise HTTPException(400, "不是本工作台导出的知识库备份")
    docs = payload.get("docs")
    if not isinstance(docs, list) or not docs:
        raise HTTPException(400, "备份里没有文档")
    if len(docs) > 500:
        raise HTTPException(400, "单次最多恢复 500 篇文档")

    added = skipped = failed = 0
    errors: list[str] = []
    for item in docs:
        if not isinstance(item, dict):
            failed += 1
            continue
        title = str(item.get("title") or "").strip()[:200]
        content = str(item.get("content") or "").strip()
        source = str(item.get("source") or "restore")[:400]
        scope = item.get("scope") if item.get("scope") in ("global", "personal") else "global"
        if not title or not content:
            failed += 1
            continue
        owner_id = user["id"]
        if scope == "personal":
            raw_uid = item.get("user_id")
            username = str(item.get("username") or "").strip()
            target = None
            if raw_uid is not None:
                target = await fetch_one("SELECT id FROM users WHERE id=?", (int(raw_uid),))
            if not target and username:
                target = await fetch_one("SELECT id FROM users WHERE username=?", (username,))
            if not target:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{title}: 原账号不存在，未恢复个人文档")
                continue
            owner_id = int(target["id"])
        dup_sql = "SELECT id FROM kb_docs WHERE module='kb' AND title=? AND scope=?"
        dup_params: tuple = (title, scope)
        if scope == "personal":
            dup_sql += " AND user_id=?"
            dup_params += (owner_id,)
        if await fetch_one(dup_sql, dup_params):
            skipped += 1
            continue
        try:
            await kb.add_document(owner_id, title, source, content, scope=scope)
            added += 1
        except Exception as e:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{title}: {e}")
    await audit(user, "kb.restore", name, f"新增 {added} / 跳过 {skipped} / 失败 {failed}")
    return {"ok": True, "added": added, "skipped": skipped, "failed": failed, "errors": errors}


@router.get("/search")
async def search(q: str, user: dict = Depends(admin_user)):
    top_k = int(load_config().get("kb_top_k") or 3)
    return {"items": await kb.search(q, top_k, include_global=True, include_personal=True)}


@router.post("/settings")
async def settings(enabled: bool, top_k: int = 3, user: dict = Depends(admin_user)):
    cfg = load_config()
    cfg["kb_enabled"] = enabled
    cfg["kb_top_k"] = max(1, min(top_k, 10))
    save_config(cfg)
    await audit(user, "kb.settings", detail=f"enabled={enabled}, top_k={top_k}")
    return {"ok": True}


# ------------------------------------------------------------------ 个人库
def _my_kb_state(row: dict, cfg: dict) -> dict:
    return {
        "public_enabled": bool(cfg.get("kb_enabled")),
        "personal_enabled": bool(int(row.get("kb_personal_enabled") or 0)),
        "use_public": bool(int(row.get("kb_use_public") or 0)),
        "use_personal": bool(int(row.get("kb_use_personal") or 0)),
    }


async def _read_my_kb_state(user_id: int, cfg: dict) -> dict:
    row = await fetch_one(
        "SELECT kb_personal_enabled,kb_use_public,kb_use_personal "
        "FROM users WHERE id=?", (user_id,)) or {}
    return _my_kb_state(row, cfg)


@my_router.get("")
async def my_overview(user: dict = Depends(current_user)):
    cfg = load_config()
    data = await kb.stats("personal", user["id"])
    return {**data, **await _read_my_kb_state(user["id"], cfg),
            "enabled": bool(cfg.get("kb_enabled")),
            "max_docs": MAX_PERSONAL_DOCS,
            "top_k": int(cfg.get("kb_top_k") or 3)}


@my_router.post("/settings")
async def my_settings(body: MyKbSettings, user: dict = Depends(current_user)):
    sets: list[str] = []
    params: list[int] = []
    current = await _read_my_kb_state(user["id"], load_config())
    personal_enabled = body.personal_enabled
    if personal_enabled is not None:
        sets.append("kb_personal_enabled=?")
        params.append(1 if personal_enabled else 0)
    use_public = body.use_public
    if use_public is not None:
        sets.append("kb_use_public=?")
        params.append(1 if use_public else 0)
    use_personal = body.use_personal
    if use_personal is None and personal_enabled is True and not current["use_personal"]:
        use_personal = True
    if use_personal is not None:
        sets.append("kb_use_personal=?")
        params.append(1 if use_personal else 0)
    if sets:
        params.append(user["id"])
        await execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", tuple(params))
    state = await _read_my_kb_state(user["id"], load_config())
    await audit(user, "kb.my.settings",
                detail=f"personal={int(state['personal_enabled'])},"
                       f"public={int(state['use_public'])},"
                       f"mine={int(state['use_personal'])}")
    return {"ok": True, **state}


@my_router.post("/text")
async def my_add_text(title: str = Form(...), content: str = Form(...),
                      user: dict = Depends(current_user)):
    await _ensure_personal_room(user["id"])
    try:
        res = await kb.add_document(user["id"], title, "manual", content, scope="personal")
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "kb.my.add", title, f"{res['chunks']} 段")
    return res


@my_router.post("/upload")
async def my_upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    await _ensure_personal_room(user["id"])
    name, text = await _read_upload(file)
    res = await kb.add_document(user["id"], name, name, text, scope="personal")
    await audit(user, "kb.my.upload", name, f"{res['chunks']} 段")
    return res


@my_router.get("/search")
async def my_search(q: str, user: dict = Depends(current_user)):
    top_k = int(load_config().get("kb_top_k") or 3)
    return {"items": await kb.search(q, top_k, user_id=user["id"],
                                     include_global=False, include_personal=True)}


@my_router.patch("/{doc_id}")
async def my_rename(doc_id: int, title: str = Form(...),
                    user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT id,title FROM kb_docs WHERE id=? AND scope='personal' AND user_id=?",
        (doc_id, user["id"]))
    if not row:
        raise HTTPException(404, "个人文档不存在")
    clean = title.strip()[:200]
    if not clean:
        raise HTTPException(400, "标题不能为空")
    await kb.rename_document(doc_id, clean)
    await audit(user, "kb.my.rename", row["title"], clean)
    return {"ok": True, "id": doc_id, "title": clean}


@my_router.delete("/{doc_id}")
async def my_delete(doc_id: int, user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT title FROM kb_docs WHERE id=? AND scope='personal' AND user_id=?",
        (doc_id, user["id"]))
    if not row:
        raise HTTPException(404, "个人文档不存在")
    await kb.delete_document(doc_id)
    await audit(user, "kb.my.delete", row["title"])
    return {"ok": True}


@my_router.get("/export")
async def my_export(user: dict = Depends(current_user)):
    docs = await kb.export_documents("personal", user["id"])
    payload = _kb_backup_payload()
    payload["count"] = len(docs)
    payload["docs"] = docs
    payload["scope"] = "personal"
    filename = time.strftime("my-kb-%Y%m%d-%H%M%S.json")
    await audit(user, "kb.my.backup", detail=f"{len(docs)} 篇")
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
