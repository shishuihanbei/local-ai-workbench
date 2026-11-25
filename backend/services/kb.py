"""知识库：文本切块 + SQLite FTS5 检索（无 fts5 时退回 LIKE）。"""
from __future__ import annotations

import re
import time
from typing import Any

from ..db import connect, execute, fetch_all, fetch_one

CHUNK = 420
_TAG_SPLIT = re.compile(r"[,，;；、#\n]+")


def clean_folder(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:80]


def clean_tags(value: str | list[str] | None) -> str:
    if isinstance(value, list):
        raw = ",".join(str(x) for x in value)
    else:
        raw = str(value or "")
    out: list[str] = []
    seen: set[str] = set()
    for item in _TAG_SPLIT.split(raw):
        tag = re.sub(r"\s+", " ", item).strip(" #")[:24]
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= 12:
            break
    return ",".join(out)


def tags_of(value: str | None) -> list[str]:
    return [x for x in str(value or "").split(",") if x]

# 中文问题里的口语停用词。去掉它们后，剩下的词更适合做检索；
# 不引入分词库，用双字片段兼顾“退款流程”“多久到账”这类连续中文。
_ZH_STOP = (
    "请问", "帮我", "麻烦", "一下", "怎么", "如何", "什么", "为什么", "哪里", "哪个",
    "多少", "几天", "多久", "可以", "能否", "是否", "需要", "应该", "以及", "然后",
    "还有", "这个", "那个", "我们", "你们", "他们", "现在", "具体", "相关",
    "的", "了", "吗", "呢", "啊", "呀", "吧", "和", "与", "及", "或", "要", "有",
    "是", "在", "我", "你", "他", "它", "会", "能", "就", "都", "也", "很", "请",
)


def _query_terms(query: str) -> list[str]:
    """把自然语言问题拆成 FTS 能命中的词，避免整句中文被当成一个 token。"""
    terms: list[str] = []
    for seg in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fa5]+", query or ""):
        if re.fullmatch(r"[A-Za-z0-9_]+", seg):
            if len(seg) >= 2:
                terms.append(seg.lower())
            continue
        cleaned = seg
        for w in _ZH_STOP:
            cleaned = cleaned.replace(w, "")
        if len(cleaned) < 2:
            continue
        terms.append(cleaned)
        # 连续中文再加双字片段，命中率明显高于整段短语。
        if len(cleaned) > 2:
            terms.extend(cleaned[i:i + 2] for i in range(len(cleaned) - 1))
    out: list[str] = []
    for t in terms:
        t = t.strip()
        if len(t) >= 2 and t not in out:
            out.append(t)
    return out[:12]


def split_text(text: str, size: int = CHUNK) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n{2,}", text) if b.strip()]
    chunks, buf = [], ""
    for b in blocks:
        if len(b) > size * 2:
            for i in range(0, len(b), size):
                piece = b[i:i + size]
                if buf:
                    chunks.append(buf)
                    buf = ""
                chunks.append(piece)
            continue
        if len(buf) + len(b) + 1 <= size:
            buf = f"{buf}\n{b}" if buf else b
        else:
            if buf:
                chunks.append(buf)
            buf = b
    if buf:
        chunks.append(buf)
    return chunks


async def add_document(user_id: int, title: str, source: str, text: str,
                       scope: str = "global", module: str = "kb",
                       folder: str = "", tags: str = "") -> dict[str, Any]:
    chunks = split_text(text)
    if not chunks:
        raise ValueError("内容为空")
    scope = "personal" if scope == "personal" else "global"
    module = "library" if module == "library" else "kb"
    folder = clean_folder(folder) if module == "library" else ""
    tags = clean_tags(tags) if module == "library" else ""
    doc_id = await execute(
        "INSERT INTO kb_docs(user_id,scope,module,title,source,chars,created_at,folder,tags) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (user_id, scope, module, title[:200], source[:400], len(text), time.time(), folder, tags))
    db = await connect()
    try:
        try:
            await db.executemany(
                "INSERT INTO kb_fts(doc_id,title,content) VALUES(?,?,?)",
                [(doc_id, title, c) for c in chunks])
        except Exception:
            pass
        await db.commit()
    finally:
        await db.close()
    return {"id": doc_id, "title": title, "chunks": len(chunks), "chars": len(text),
            "scope": scope, "module": module, "folder": folder, "tags": tags}


def _rank_rows(rows: list[dict[str, Any]], terms: list[str], top_k: int) -> list[dict[str, Any]]:
    """按关键词覆盖度排序；同样覆盖度再参考 FTS bm25。"""
    ranked = []
    for row in rows:
        title = str(row.get("title") or "")
        content = str(row.get("content") or "")
        coverage = 0.0
        for term in terms:
            weight = 2.0 if len(term) >= 4 else 1.0
            if term in title:
                coverage += weight * 3
            elif term in content:
                coverage += weight
        ranked.append((coverage, float(row.get("score") or 0), row))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    unique, seen = [], set()
    for _, _, row in ranked:
        doc_id = row["doc_id"]
        if doc_id in seen:
            continue
        seen.add(doc_id)
        unique.append({
            "doc_id": doc_id,
            "title": row["title"],
            "snippet": row.get("snippet") or str(row.get("content") or "")[:160],
            "scope": row.get("scope") or "global",
            "user_id": row.get("user_id"),
            "username": row.get("username") or "",
            "folder": row.get("folder") or "",
            "tags": row.get("tags") or "",
        })
        if len(unique) >= top_k:
            break
    return unique


def _scope_filter(user_id: int | None, include_global: bool,
                  include_personal: bool) -> tuple[str, tuple]:
    """生成按库范围过滤的 SQL 片段。

    管理员查公共库时 user_id 传 None；用户查自己的库必须带 user_id，
    过滤放在服务端，不能只靠前端隐藏。
    """
    if user_id is None:
        if include_global and include_personal:
            return "", ()
        if include_personal:
            return " AND d.scope='personal'", ()
        return " AND d.scope='global'", ()
    parts: list[str] = []
    params: list[Any] = []
    if include_global:
        parts.append("d.scope='global'")
    if include_personal:
        parts.append("(d.scope='personal' AND d.user_id=?)")
        params.append(user_id)
    if not parts:
        return None, ()
    return " AND (" + " OR ".join(parts) + ")", tuple(params)


async def search(query: str, top_k: int = 3, user_id: int | None = None,
                 include_global: bool = True, include_personal: bool = False,
                 module: str = "kb") -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    terms = _query_terms(query)
    if not terms:
        return []
    module = "library" if module == "library" else "kb"
    scope_sql, scope_params = _scope_filter(user_id, include_global, include_personal)
    if scope_sql is None:
        return []
    scope_sql = " AND d.module=? " + scope_sql
    scope_params = (module, *scope_params)
    fts_query = " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
    try:
        rows = await fetch_all(
            "SELECT kb_fts.doc_id, kb_fts.title, kb_fts.content, "
            "snippet(kb_fts, 2, '', '', '…', 40) AS snippet, bm25(kb_fts) AS score, "
            "d.scope, d.user_id, d.folder, d.tags, u.username "
            "FROM kb_fts JOIN kb_docs d ON d.id=kb_fts.doc_id "
            "LEFT JOIN users u ON u.id=d.user_id "
            "WHERE kb_fts MATCH ?" + scope_sql + " ORDER BY score LIMIT ?",
            (fts_query, *scope_params, max(top_k * 5, 10)))
        if rows:
            ranked = _rank_rows(rows, terms, top_k)
            if ranked:
                return ranked
    except Exception:
        pass

    # 中文连续文本常被 FTS 当成整段 token，MATCH 可能一个都命中不了；
    # 逐词 LIKE 取候选后统一算覆盖度，保证“退款几天到账”能找到同时含退款和到账的文档。
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[Any, str]] = set()
    limit = max(top_k * 10, 20)
    for term in terms:
        try:
            rows = await fetch_all(
                "SELECT kb_fts.doc_id, kb_fts.title, kb_fts.content, "
                "substr(kb_fts.content,1,160) AS snippet, d.scope, d.user_id, d.folder, d.tags, u.username "
                "FROM kb_fts JOIN kb_docs d ON d.id=kb_fts.doc_id "
                "LEFT JOIN users u ON u.id=d.user_id "
                "WHERE (kb_fts.content LIKE ? OR kb_fts.title LIKE ? "
                "OR d.folder LIKE ? OR d.tags LIKE ?)" + scope_sql +
                " ORDER BY kb_fts.doc_id DESC LIMIT ?",
                ("%" + term + "%", "%" + term + "%", "%" + term + "%", "%" + term + "%",
                 *scope_params, limit))
        except Exception:
            continue
        for row in rows:
            key = (row.get("doc_id"), str(row.get("content") or ""))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(row)
    if not candidates:
        return []
    return _rank_rows(candidates, terms, top_k)



async def stats(scope: str = "global", user_id: int | None = None, q: str = "",
                module: str = "kb", folder: str = "", tag: str = "") -> dict[str, Any]:
    scope = scope if scope in ("global", "personal", "all") else "global"
    module = "library" if module == "library" else "kb"
    where: list[str] = ["d.module=?"]
    params: list[Any] = [module]
    if scope != "all":
        where.append("d.scope=?")
        params.append(scope)
    if user_id is not None:
        where.append("d.user_id=?")
        params.append(user_id)
    folder = clean_folder(folder) if module == "library" else ""
    if folder:
        where.append("d.folder=?")
        params.append(folder)
    tag = clean_tags(tag) if module == "library" else ""
    if tag:
        where.append("(','||d.tags||',') LIKE ?")
        params.append(f"%,{tag},%")
    q = (q or "").strip()
    if q:
        where.append("(d.title LIKE ? OR d.source LIKE ? OR d.folder LIKE ? "
                     "OR d.tags LIKE ? OR u.username LIKE ?)")
        params.extend(["%" + q + "%"] * 5)
    sql = ("SELECT d.id,d.user_id,d.scope,d.module,d.title,d.source,d.chars,d.created_at,"
           "d.uses,d.last_used_at,d.folder,d.tags,u.username "
           "FROM kb_docs d LEFT JOIN users u ON u.id=d.user_id ")
    sql += "WHERE " + " AND ".join(where) + " "
    limit = 500 if scope == "all" else 300
    sql += "ORDER BY d.id DESC LIMIT ?"
    docs = await fetch_all(sql, (*params, limit))

    count_sql = ("SELECT COUNT(*) c, COALESCE(SUM(d.chars),0) s, "
                 "COALESCE(SUM(d.uses),0) used FROM kb_docs d "
                 "LEFT JOIN users u ON u.id=d.user_id ")
    count_sql += "WHERE " + " AND ".join(where) + " "
    total = await fetch_one(count_sql, tuple(params))
    return {"docs": docs, "count": (total or {}).get("c", 0),
            "chars": (total or {}).get("s", 0), "uses": (total or {}).get("used", 0),
            "scope": scope, "module": module}


async def totals(module: str = "kb") -> dict[str, int]:
    module = "library" if module == "library" else "kb"
    rows = await fetch_all(
        "SELECT scope, COUNT(*) c, COALESCE(SUM(chars),0) s, COALESCE(SUM(uses),0) used "
        "FROM kb_docs WHERE module=? GROUP BY scope", (module,))
    global_row = next((r for r in rows if r["scope"] == "global"), {})
    personal_row = next((r for r in rows if r["scope"] == "personal"), {})
    users = await fetch_one(
        "SELECT COUNT(DISTINCT user_id) c FROM kb_docs "
        "WHERE module=? AND scope='personal' AND user_id IS NOT NULL", (module,))
    return {
        "all_count": int(global_row.get("c", 0)) + int(personal_row.get("c", 0)),
        "all_chars": int(global_row.get("s", 0)) + int(personal_row.get("s", 0)),
        "global_count": int(global_row.get("c", 0)),
        "global_chars": int(global_row.get("s", 0)),
        "personal_count": int(personal_row.get("c", 0)),
        "personal_chars": int(personal_row.get("s", 0)),
        "personal_users": int((users or {}).get("c", 0)),
        "uses": int(global_row.get("used", 0)) + int(personal_row.get("used", 0)),
    }



async def get_document(doc_id: int, module: str = "kb") -> dict[str, Any] | None:
    """管理员查看单篇文档正文；个人文档同时返回归属账号。"""
    module = "library" if module == "library" else "kb"
    row = await fetch_one(
        "SELECT d.id,d.user_id,d.scope,d.module,d.title,d.source,d.chars,d.created_at,"
        "d.uses,d.last_used_at,d.folder,d.tags,u.username "
        "FROM kb_docs d LEFT JOIN users u ON u.id=d.user_id "
        "WHERE d.id=? AND d.module=?", (doc_id, module))
    if not row:
        return None
    parts = await fetch_all(
        "SELECT content FROM kb_fts WHERE doc_id=? ORDER BY rowid", (doc_id,))
    doc = dict(row)
    doc["content"] = "".join(str(p.get("content") or "") for p in parts)
    return doc


async def mark_used(doc_ids: list[int]) -> None:
    ids = [int(x) for x in doc_ids if str(x).isdigit()]
    if not ids:
        return
    now = time.time()
    placeholders = ",".join("?" for _ in ids)
    await execute(
        f"UPDATE kb_docs SET uses=uses+1,last_used_at=? WHERE id IN ({placeholders})",
        (now, *ids))


async def full_texts(doc_ids: list[int]) -> list[dict[str, Any]]:
    ids = [int(x) for x in doc_ids if str(x).isdigit()]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = await fetch_all(
        f"SELECT d.id,d.user_id,d.scope,d.module,d.title,d.source,d.chars,d.created_at,"
        f"d.folder,d.tags,u.username "
        f"FROM kb_docs d LEFT JOIN users u ON u.id=d.user_id "
        f"WHERE d.id IN ({placeholders}) ORDER BY d.id", ids)
    out: list[dict[str, Any]] = []
    for row in rows:
        parts = await fetch_all(
            "SELECT content FROM kb_fts WHERE doc_id=? ORDER BY rowid", (row["id"],))
        item = dict(row)
        item["content"] = "".join(str(p.get("content") or "") for p in parts)
        out.append(item)
    return out


async def delete_document(doc_id: int) -> None:
    await execute("DELETE FROM kb_docs WHERE id=?", (doc_id,))
    try:
        await execute("DELETE FROM kb_fts WHERE doc_id=?", (doc_id,))
    except Exception:
        pass


async def rename_document(doc_id: int, title: str) -> None:
    await execute("UPDATE kb_docs SET title=? WHERE id=?", (title[:200], doc_id))
    try:
        await execute("UPDATE kb_fts SET title=? WHERE doc_id=?", (title[:200], doc_id))
    except Exception:
        pass


async def update_metadata(doc_id: int, title: str | None = None,
                          folder: str | None = None, tags: str | None = None) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        title = title.strip()[:200] or "未命名"
        sets.append("title=?")
        params.append(title)
    if folder is not None:
        sets.append("folder=?")
        params.append(clean_folder(folder))
    if tags is not None:
        sets.append("tags=?")
        params.append(clean_tags(tags))
    if not sets:
        return
    params.append(doc_id)
    await execute("UPDATE kb_docs SET " + ",".join(sets) + " WHERE id=?", tuple(params))
    if title is not None:
        try:
            await execute("UPDATE kb_fts SET title=? WHERE doc_id=?", (title, doc_id))
        except Exception:
            pass


async def facets(scope: str = "personal", user_id: int | None = None,
                 module: str = "library") -> dict[str, list[dict[str, Any]]]:
    """返回文件夹和标签计数，供筛选项使用。"""
    scope = scope if scope in ("global", "personal", "all") else "personal"
    module = "library" if module == "library" else "kb"
    where: list[str] = ["module=?"]
    params: list[Any] = [module]
    if scope != "all":
        where.append("scope=?")
        params.append(scope)
    if user_id is not None:
        where.append("user_id=?")
        params.append(user_id)
    base = "SELECT folder,tags FROM kb_docs WHERE " + " AND ".join(where)
    rows = await fetch_all(base, tuple(params))
    folders: dict[str, int] = {}
    tags: dict[str, int] = {}
    for row in rows:
        folder = str(row.get("folder") or "")
        if folder:
            folders[folder] = folders.get(folder, 0) + 1
        for tag in tags_of(row.get("tags")):
            tags[tag] = tags.get(tag, 0) + 1
    return {
        "folders": [{"name": k, "count": v} for k, v in sorted(folders.items())],
        "tags": [{"name": k, "count": v} for k, v in sorted(tags.items())],
    }


async def export_documents(scope: str = "global", user_id: int | None = None,
                           module: str = "kb") -> list[dict[str, Any]]:
    """导出指定范围的文档；正文由 FTS 片段按 rowid 顺序拼回。"""
    scope = scope if scope in ("global", "personal", "all") else "global"
    module = "library" if module == "library" else "kb"
    where: list[str] = ["d.module=?"]
    params: list[Any] = [module]
    if scope != "all":
        where.append("d.scope=?")
        params.append(scope)
    if user_id is not None:
        where.append("d.user_id=?")
        params.append(user_id)
    sql = ("SELECT d.id,d.user_id,d.scope,d.module,d.title,d.source,d.chars,d.created_at,"
           "d.folder,d.tags,u.username "
           "FROM kb_docs d LEFT JOIN users u ON u.id=d.user_id ")
    sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY d.id"
    docs = await fetch_all(sql, tuple(params))
    chunks = await fetch_all("SELECT rowid,doc_id,content FROM kb_fts ORDER BY rowid")
    grouped: dict[int, list[str]] = {}
    for row in chunks:
        grouped.setdefault(int(row["doc_id"]), []).append(str(row.get("content") or ""))
    out = []
    for doc in docs:
        out.append({
            "title": doc.get("title") or "未命名",
            "source": doc.get("source") or "restore",
            "chars": int(doc.get("chars") or 0),
            "created_at": doc.get("created_at") or 0,
            "scope": doc.get("scope") or "global",
            "module": doc.get("module") or module,
            "user_id": doc.get("user_id"),
            "username": doc.get("username") or "",
            "folder": doc.get("folder") or "",
            "tags": doc.get("tags") or "",
            "content": "\n\n".join(grouped.get(int(doc["id"]), [])),
        })
    return out
