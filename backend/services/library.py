"""资料库：可反复选用的文档集合，与知识库分开存储但共用文档表。"""
from __future__ import annotations

from typing import Any

from ..config import load_config
from ..db import fetch_one
from . import kb

MODULE = "library"
MAX_PERSONAL_DOCS = 100
CHAT_UPLOAD_SOURCE = "聊天上传"
CHAT_UPLOAD_FOLDER = "聊天上传"


async def import_chat_upload(user_id: int, name: str, text: str) -> dict[str, Any]:
    """聊天附件入库：有可读正文时自动加入个人资料库，同名同字数不重复添加。"""
    raw = (text or "").strip()
    title = (name or "未命名").strip()[:200] or "未命名"
    if not raw:
        return {"status": "skip", "reason": "未能提取正文"}
    total = await fetch_one(
        "SELECT COUNT(*) c FROM kb_docs WHERE module=? AND scope='personal' AND user_id=?",
        (MODULE, user_id))
    if int((total or {}).get("c", 0)) >= MAX_PERSONAL_DOCS:
        return {"status": "skip", "reason": f"个人资料库已满（{MAX_PERSONAL_DOCS} 篇）"}
    exists = await fetch_one(
        "SELECT id FROM kb_docs WHERE module=? AND scope='personal' AND user_id=? "
        "AND title=? AND chars=?",
        (MODULE, user_id, title, len(raw)))
    if exists:
        return {"status": "exists", "doc_id": int(exists["id"]), "title": title}
    try:
        res = await kb.add_document(user_id, title, CHAT_UPLOAD_SOURCE, raw,
                                    scope="personal", module=MODULE,
                                    folder=CHAT_UPLOAD_FOLDER, tags="聊天上传")
    except ValueError as e:
        return {"status": "skip", "reason": str(e)}
    return {"status": "added", "doc_id": int(res["id"]), "title": res["title"],
            "chars": res["chars"]}


async def user_state(user_id: int, cfg: dict | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    row = await fetch_one(
        "SELECT library_personal_enabled,library_use_global,library_use_personal "
        "FROM users WHERE id=?", (user_id,)) or {}
    return {
        "global_enabled": bool(cfg.get("library_enabled")),
        "personal_enabled": bool(int(row.get("library_personal_enabled") or 0)),
        "use_global": bool(int(row.get("library_use_global") or 0)),
        "use_personal": bool(int(row.get("library_use_personal") or 0)),
        "max_docs": int(cfg.get("library_max_docs") or 10),
        "max_chars": int(cfg.get("library_max_chars") or 12000),
    }


async def picker_documents(user_id: int, cfg: dict | None = None) -> list[dict[str, Any]]:
    """只列出当前用户获准使用的总库/个人库文档，供聊天框选择。"""
    cfg = cfg or load_config()
    state = await user_state(user_id, cfg)
    docs: list[dict[str, Any]] = []
    if state["global_enabled"] and state["use_global"]:
        total = await kb.stats("global", module=MODULE)
        docs.extend(total.get("docs") or [])
    if state["personal_enabled"] and state["use_personal"]:
        mine = await kb.stats("personal", user_id, module=MODULE)
        docs.extend(mine.get("docs") or [])
    return docs[:200]


def facets_from_docs(docs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    folders: dict[str, int] = {}
    tags: dict[str, int] = {}
    for doc in docs:
        folder = str(doc.get("folder") or "")
        if folder:
            folders[folder] = folders.get(folder, 0) + 1
        for tag in kb.tags_of(doc.get("tags")):
            tags[tag] = tags.get(tag, 0) + 1
    return {
        "folders": [{"name": k, "count": v} for k, v in sorted(folders.items())],
        "tags": [{"name": k, "count": v} for k, v in sorted(tags.items())],
    }


async def selected_documents(user_id: int, doc_ids: list[int],
                             cfg: dict | None = None) -> list[dict[str, Any]]:
    """按当前开关校验用户选中的资料，越权或已关闭的来源会被忽略。"""
    ids = [int(x) for x in (doc_ids or []) if str(x).isdigit()]
    if not ids:
        return []
    cfg = cfg or load_config()
    state = await user_state(user_id, cfg)
    allowed_global = bool(state["global_enabled"] and state["use_global"])
    allowed_personal = bool(state["personal_enabled"] and state["use_personal"])
    rows = await kb.full_texts(ids[: int(state["max_docs"])])
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("module") != MODULE:
            continue
        if row.get("scope") == "global" and allowed_global:
            out.append(dict(row))
        elif (row.get("scope") == "personal" and allowed_personal
              and int(row.get("user_id") or 0) == user_id):
            out.append(dict(row))
    return out
