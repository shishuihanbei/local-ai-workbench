"""资料库接口：总库由管理员维护，个人库由用户维护；聊天中可反复选用。"""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..config import load_config, save_config
from ..db import audit, execute, fetch_one
from ..security import admin_user, current_user
from ..services import kb, library
from .kb import _read_upload

admin_router = APIRouter(prefix="/api/library", tags=["library"])
my_router = APIRouter(prefix="/api/my/library", tags=["my-library"])

MAX_PERSONAL_DOCS = library.MAX_PERSONAL_DOCS


class MyLibrarySettings(BaseModel):
    personal_enabled: bool | None = None
    use_global: bool | None = None
    use_personal: bool | None = None


class LibrarySettings(BaseModel):
    enabled: bool
    max_docs: int | None = None
    max_chars: int | None = None


class OrganizeDoc(BaseModel):
    title: str | None = None
    folder: str | None = None
    tags: str | None = None


def _backup_payload(docs: list[dict]) -> dict:
    return {
        "format": "workbench-library-backup",
        "format_version": 1,
        "exported_at": time.time(),
        "count": len(docs),
        "docs": docs,
    }


async def _ensure_personal_room(user_id: int) -> None:
    total = await fetch_one(
        "SELECT COUNT(*) c FROM kb_docs WHERE module='library' AND scope='personal' AND user_id=?",
        (user_id,))
    if int((total or {}).get("c", 0)) >= MAX_PERSONAL_DOCS:
        raise HTTPException(400, f"个人资料库最多 {MAX_PERSONAL_DOCS} 篇，请先删掉不用的")


# ------------------------------------------------------------------ 总库 / 管理
@admin_router.get("")
async def overview(scope: str = "all", user_id: int | None = None, q: str = "",
                   folder: str = "", tag: str = "", user: dict = Depends(admin_user)):
    cfg = load_config()
    data = await kb.stats(scope, user_id, q, module="library", folder=folder, tag=tag)
    totals = await kb.totals("library")
    facets = await kb.facets(scope, user_id, module="library")
    return {**data, **totals, **facets, "enabled": bool(cfg.get("library_enabled")),
            "max_docs": int(cfg.get("library_max_docs") or 10),
            "max_chars": int(cfg.get("library_max_chars") or 12000)}


@admin_router.post("/text")
async def add_text(title: str = Form(...), content: str = Form(...),
                   folder: str = Form(""), tags: str = Form(""),
                   user: dict = Depends(admin_user)):
    try:
        res = await kb.add_document(user["id"], title, "manual", content,
                                    scope="global", module="library",
                                    folder=folder, tags=tags)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "library.add", title, f"{res['chunks']} 段")
    return res


@admin_router.post("/upload")
async def upload(file: UploadFile = File(...), folder: str = Form(""), tags: str = Form(""),
                 user: dict = Depends(admin_user)):
    name, text = await _read_upload(file)
    res = await kb.add_document(user["id"], name, name, text,
                                scope="global", module="library",
                                folder=folder, tags=tags)
    await audit(user, "library.upload", name, f"{res['chunks']} 段")
    return res


@admin_router.patch("/{doc_id}")
async def organize(doc_id: int, body: OrganizeDoc, user: dict = Depends(admin_user)):
    row = await fetch_one("SELECT id,title FROM kb_docs WHERE id=? AND module='library'", (doc_id,))
    if not row:
        raise HTTPException(404, "资料不存在")
    await kb.update_metadata(doc_id, title=body.title, folder=body.folder, tags=body.tags)
    await audit(user, "library.organize", row["title"],
                f"id={doc_id},folder={body.folder or ''},tags={body.tags or ''}")
    return await kb.get_document(doc_id, module="library")


@admin_router.get("/doc/{doc_id}")
async def document_detail(doc_id: int, user: dict = Depends(admin_user)):
    doc = await kb.get_document(doc_id, module="library")
    if not doc:
        raise HTTPException(404, "资料不存在")
    return doc


@admin_router.delete("/{doc_id}")
async def delete(doc_id: int, user: dict = Depends(admin_user)):
    row = await fetch_one(
        "SELECT title,scope,user_id FROM kb_docs WHERE id=? AND module='library'", (doc_id,))
    if not row:
        raise HTTPException(404, "资料不存在")
    await kb.delete_document(doc_id)
    await audit(user, "library.delete", row["title"],
                f"scope={row['scope']} user={row['user_id']}")
    return {"ok": True}


@admin_router.get("/export")
async def export_backup(user: dict = Depends(admin_user)):
    docs = await kb.export_documents("all", module="library")
    payload = _backup_payload(docs)
    filename = time.strftime("workbench-library-%Y%m%d-%H%M%S.json")
    await audit(user, "library.backup", detail=f"{len(docs)} 篇")
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@admin_router.post("/restore")
async def restore_backup(file: UploadFile = File(...), user: dict = Depends(admin_user)):
    name = file.filename or "library-backup.json"
    if not name.lower().endswith(".json"):
        raise HTTPException(400, "只支持资料库 JSON 备份文件")
    raw = await file.read()
    if len(raw) > 16 * 1024 * 1024:
        raise HTTPException(400, "备份文件过大（上限 16MB）")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise HTTPException(400, "备份文件不是合法的 UTF-8 JSON")
    if not isinstance(payload, dict) or payload.get("format") != "workbench-library-backup":
        raise HTTPException(400, "不是本工作台导出的资料库备份")
    docs = payload.get("docs")
    if not isinstance(docs, list) or not docs:
        raise HTTPException(400, "备份里没有资料")
    if len(docs) > 500:
        raise HTTPException(400, "单次最多恢复 500 篇资料")

    added = skipped = failed = 0
    errors: list[str] = []
    for item in docs:
        if not isinstance(item, dict):
            failed += 1
            continue
        title = str(item.get("title") or "").strip()[:200]
        content = str(item.get("content") or "").strip()
        source = str(item.get("source") or "restore")[:400]
        folder = str(item.get("folder") or "")[:80]
        tags = str(item.get("tags") or "")[:400]
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
                try:
                    target = await fetch_one("SELECT id FROM users WHERE id=?", (int(raw_uid),))
                except Exception:
                    target = None
            if not target and username:
                target = await fetch_one("SELECT id FROM users WHERE username=?", (username,))
            if not target:
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{title}: 原账号不存在，未恢复个人资料")
                continue
            owner_id = int(target["id"])
        dup_sql = "SELECT id FROM kb_docs WHERE module='library' AND title=? AND scope=?"
        dup_params: tuple = (title, scope)
        if scope == "personal":
            dup_sql += " AND user_id=?"
            dup_params += (owner_id,)
        if await fetch_one(dup_sql, dup_params):
            skipped += 1
            continue
        try:
            await kb.add_document(owner_id, title, source, content,
                                  scope=scope, module="library",
                                  folder=folder, tags=tags)
            added += 1
        except Exception as e:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{title}: {e}")
    await audit(user, "library.restore", name, f"新增 {added} / 跳过 {skipped} / 失败 {failed}")
    return {"ok": True, "added": added, "skipped": skipped, "failed": failed, "errors": errors}


@admin_router.post("/settings")
async def settings(body: LibrarySettings, user: dict = Depends(admin_user)):
    cfg = load_config()
    cfg["library_enabled"] = body.enabled
    if body.max_docs is not None:
        cfg["library_max_docs"] = max(1, min(int(body.max_docs), 30))
    if body.max_chars is not None:
        cfg["library_max_chars"] = max(1000, min(int(body.max_chars), 48000))
    save_config(cfg)
    await audit(user, "library.settings",
                detail=f"enabled={body.enabled}, max_docs={cfg['library_max_docs']}, "
                       f"max_chars={cfg['library_max_chars']}")
    return {"ok": True, "enabled": bool(cfg["library_enabled"]),
            "max_docs": cfg["library_max_docs"], "max_chars": cfg["library_max_chars"]}


# ------------------------------------------------------------------ 个人库
@my_router.get("")
async def my_overview(q: str = "", folder: str = "", tag: str = "",
                      user: dict = Depends(current_user)):
    cfg = load_config()
    data = await kb.stats("personal", user["id"], q, module="library",
                          folder=folder, tag=tag)
    state = await library.user_state(user["id"], cfg)
    facets = await kb.facets("personal", user["id"], module="library")
    return {**data, **state, **facets, "max_personal_docs": MAX_PERSONAL_DOCS}


@my_router.post("/settings")
async def my_settings(body: MyLibrarySettings, user: dict = Depends(current_user)):
    sets: list[str] = []
    params: list[int] = []
    current = await library.user_state(user["id"], load_config())
    personal_enabled = body.personal_enabled
    if personal_enabled is not None:
        sets.append("library_personal_enabled=?")
        params.append(1 if personal_enabled else 0)
    use_global = body.use_global
    if use_global is not None:
        sets.append("library_use_global=?")
        params.append(1 if use_global else 0)
    use_personal = body.use_personal
    if use_personal is None and personal_enabled is True and not current["use_personal"]:
        use_personal = True
    if use_personal is not None:
        sets.append("library_use_personal=?")
        params.append(1 if use_personal else 0)
    if sets:
        params.append(user["id"])
        await execute("UPDATE users SET " + ",".join(sets) + " WHERE id=?", tuple(params))
    state = await library.user_state(user["id"], load_config())
    await audit(user, "library.my.settings",
                detail=f"personal={int(state['personal_enabled'])},"
                       f"global={int(state['use_global'])},"
                       f"mine={int(state['use_personal'])}")
    return {"ok": True, **state}


@my_router.get("/picker")
async def picker(user: dict = Depends(current_user)):
    cfg = load_config()
    state = await library.user_state(user["id"], cfg)
    items = await library.picker_documents(user["id"], cfg)
    return {"items": items, **state, **library.facets_from_docs(items),
            "max_personal_docs": MAX_PERSONAL_DOCS}


@my_router.post("/text")
async def my_add_text(title: str = Form(...), content: str = Form(...),
                      folder: str = Form(""), tags: str = Form(""),
                      user: dict = Depends(current_user)):
    await _ensure_personal_room(user["id"])
    try:
        res = await kb.add_document(user["id"], title, "manual", content,
                                    scope="personal", module="library",
                                    folder=folder, tags=tags)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "library.my.add", title, f"{res['chunks']} 段")
    return res


@my_router.post("/upload")
async def my_upload(file: UploadFile = File(...), folder: str = Form(""), tags: str = Form(""),
                    user: dict = Depends(current_user)):
    await _ensure_personal_room(user["id"])
    name, text = await _read_upload(file)
    res = await kb.add_document(user["id"], name, name, text,
                                scope="personal", module="library",
                                folder=folder, tags=tags)
    await audit(user, "library.my.upload", name, f"{res['chunks']} 段")
    return res


@my_router.patch("/{doc_id}")
async def my_organize(doc_id: int, body: OrganizeDoc, user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT title FROM kb_docs WHERE id=? AND module='library' "
        "AND scope='personal' AND user_id=?", (doc_id, user["id"]))
    if not row:
        raise HTTPException(404, "个人资料不存在")
    await kb.update_metadata(doc_id, title=body.title, folder=body.folder, tags=body.tags)
    await audit(user, "library.my.organize", row["title"],
                f"id={doc_id},folder={body.folder or ''},tags={body.tags or ''}")
    return await kb.get_document(doc_id, module="library")


@my_router.get("/search")
async def my_search(q: str = "", user: dict = Depends(current_user)):
    items = await kb.search(q, top_k=20, user_id=user["id"],
                            include_global=False, include_personal=True,
                            module="library")
    return {"items": items, "q": q.strip()}


@my_router.get("/doc/{doc_id}")
async def my_document(doc_id: int, user: dict = Depends(current_user)):
    doc = await kb.get_document(doc_id, module="library")
    if not doc:
        raise HTTPException(404, "资料不存在")
    state = await library.user_state(user["id"], load_config())
    if doc["scope"] == "personal":
        if int(doc["user_id"] or 0) != user["id"]:
            raise HTTPException(404, "资料不存在")
    elif not (state["global_enabled"] and state["use_global"]):
        raise HTTPException(404, "资料不存在")
    return doc


@my_router.delete("/{doc_id}")
async def my_delete(doc_id: int, user: dict = Depends(current_user)):
    row = await fetch_one(
        "SELECT title FROM kb_docs WHERE id=? AND module='library' "
        "AND scope='personal' AND user_id=?", (doc_id, user["id"]))
    if not row:
        raise HTTPException(404, "个人资料不存在")
    await kb.delete_document(doc_id)
    await audit(user, "library.my.delete", row["title"], f"id={doc_id}")
    return {"ok": True}
