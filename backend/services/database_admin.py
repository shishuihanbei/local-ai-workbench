"""数据库中心：当前 SQLite 管理、外部数据库连接、数据浏览与外部迁移。

设计边界：
- 工作台自身仍以本地 SQLite 作为主库，避免切换失败后整个服务打不开；
- 这里负责把当前数据完整复制到 MySQL / PostgreSQL / 另一个 SQLite；
- 外部库可以在控制台里浏览、查询、增删改，不会偷偷改动主库；
- 连接密码用 AES-GCM 加密后落盘，接口只返回“已设置密码”，不回显明文。
"""
from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import ssl
import threading
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, unquote, urlparse

from ..config import DATA_DIR, DB_PATH
from . import secrets_store

CONNECTIONS_PATH = DATA_DIR / "database_connections.json"
MIGRATION_HISTORY_PATH = DATA_DIR / "database_migrations.json"
BACKUP_DIR = DATA_DIR / "database_backups"
MAX_PREVIEW = 320
MAX_ROWS = 200
_LOCK = threading.RLock()

# 工作台自身依赖的表：只允许改数据，不允许在“当前工作台数据库”里改名或删除。
CORE_TABLES = {
    "users", "sessions", "auth_identities", "api_keys", "conversations", "messages",
    "memories", "uploads", "audit_logs", "models", "providers", "routes",
    "prompt_templates", "prompt_versions", "prompt_releases", "requests", "spans",
    "cache_entries", "experiments", "downloads", "kb_docs", "settings", "schema_migrations",
    "cluster_nodes", "cluster_pools", "cluster_members",
}


class DBAdminError(RuntimeError):
    """给页面看的可读错误。"""


# ------------------------------------------------------------------ 基础工具
ENGINES: dict[str, dict[str, Any]] = {
    "sqlite": {
        "label": "SQLite",
        "default_port": 0,
        "note": "单文件数据库，适合本机和小型部署；当前工作台默认使用它。",
        "driver": "内置",
    },
    "mysql": {
        "label": "MySQL / MariaDB",
        "default_port": 3306,
        "note": "常见的网站与业务数据库，远程连接需要在服务器放行端口并授权账号。",
        "driver": "pymysql",
    },
    "postgres": {
        "label": "PostgreSQL",
        "default_port": 5432,
        "note": "功能完整的关系型数据库，适合长期运行和多人协作。",
        "driver": "psycopg",
    },
}


def engine_info() -> list[dict[str, Any]]:
    out = []
    for key, item in ENGINES.items():
        available = True
        if key == "mysql":
            try:
                import pymysql  # noqa: F401
            except Exception:
                available = False
        elif key == "postgres":
            try:
                import psycopg  # noqa: F401
            except Exception:
                available = False
        out.append({**item, "key": key, "available": available})
    return out


def _q(name: str, engine: str) -> str:
    if engine == "mysql":
        return "`" + str(name).replace("`", "``") + "`"
    return '"' + str(name).replace('"', '""') + '"'


def _param(engine: str) -> str:
    return "%s" if engine in ("mysql", "postgres") else "?"


def _ph(engine: str, n: int) -> str:
    return ",".join([_param(engine)] * n)


def _is_internal_table(name: str) -> bool:
    return (name.startswith("sqlite_") or name == "kb_fts" or name.startswith("kb_fts_")
            or name in ("kb_fts_config", "kb_fts_content", "kb_fts_data", "kb_fts_docsize", "kb_fts_idx"))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return str(value)
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return f"[BLOB {len(raw)} bytes]"
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return str(value)


def _raw_result_rows(cur: Any) -> tuple[list[str], list[list[Any]]]:
    desc = getattr(cur, "description", None) or []
    cols = [d[0] for d in desc]
    rows = cur.fetchall()
    values: list[list[Any]] = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            values.append([_json_value(row[c]) for c in cols])
        elif isinstance(row, dict):
            values.append([_json_value(row.get(c)) for c in cols])
        else:
            values.append([_json_value(v) for v in row])
    return cols, values


def _cur_rows(cur: Any) -> list[dict[str, Any]]:
    desc = getattr(cur, "description", None) or []
    cols = [d[0] for d in desc]
    rows = cur.fetchall()
    out = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            out.append({c: _json_value(row[c]) for c in cols})
        elif isinstance(row, dict):
            out.append({c: _json_value(row.get(c)) for c in cols})
        else:
            out.append({c: _json_value(v) for c, v in zip(cols, row)})
    return out


def _connect_raw(engine: str, record: dict[str, Any], database: str | None = None,
                 server: bool = False) -> Any:
    if engine == "sqlite":
        path = Path(record.get("path") or DB_PATH)
        if not path.exists() and not record.get("create"):
            raise DBAdminError(f"SQLite 文件不存在：{path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=8)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    password = secrets_store.decrypt(record.get("password") or "")
    host = str(record.get("host") or "127.0.0.1").strip()
    port = _safe_int(record.get("port"), ENGINES[engine]["default_port"])
    dbname = database if database is not None else str(record.get("database") or "").strip()
    if engine == "mysql":
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except Exception as exc:
            raise DBAdminError("缺少 MySQL 驱动 pymysql，请运行 start.bat 重新检查依赖") from exc
        kwargs: dict[str, Any] = {
            "host": host, "port": port, "user": str(record.get("username") or ""),
            "password": password, "charset": "utf8mb4", "cursorclass": DictCursor,
            "connect_timeout": 6, "read_timeout": 45, "write_timeout": 45,
            "autocommit": True, "program_name": "workbench-console",
        }
        if not server and dbname:
            kwargs["database"] = dbname
        if record.get("ssl"):
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ctx
        try:
            return pymysql.connect(**kwargs)
        except Exception as exc:
            raise DBAdminError(f"MySQL 连接失败：{exc}") from exc

    if engine == "postgres":
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:
            raise DBAdminError("缺少 PostgreSQL 驱动 psycopg，请运行 start.bat 重新检查依赖") from exc
        try:
            return psycopg.connect(
                host=host, port=port, user=str(record.get("username") or ""),
                password=password, dbname=dbname or "postgres", connect_timeout=6,
                sslmode="require" if record.get("ssl") else "prefer",
                row_factory=dict_row,
            )
        except Exception as exc:
            raise DBAdminError(f"PostgreSQL 连接失败：{exc}") from exc

    raise DBAdminError(f"不支持的数据库类型：{engine}")


@contextmanager
def _open(record: dict[str, Any], database: str | None = None,
          server: bool = False) -> Iterator[tuple[str, Any]]:
    engine = str(record.get("engine") or "sqlite")
    con = _connect_raw(engine, record, database=database, server=server)
    try:
        yield engine, con
    finally:
        try:
            con.close()
        except Exception:
            pass


def _exec(con: Any, engine: str, sql: str, params: tuple = ()) -> Any:
    if engine == "sqlite":
        return con.execute(sql, params)
    cur = con.cursor()
    cur.execute(sql, params)
    return cur


def _commit(con: Any, engine: str) -> None:
    if engine in ("sqlite", "postgres"):
        con.commit()


# ------------------------------------------------------------------ 连接配置
def _load_connections() -> list[dict[str, Any]]:
    with _LOCK:
        if not CONNECTIONS_PATH.exists():
            return []
        try:
            data = json.loads(CONNECTIONS_PATH.read_text("utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def _save_connections(rows: list[dict[str, Any]]) -> None:
    CONNECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONNECTIONS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, CONNECTIONS_PATH)


def _public_connection(row: dict[str, Any]) -> dict[str, Any]:
    engine = str(row.get("engine") or "sqlite")
    return {
        "id": row.get("id"),
        "name": row.get("name") or "",
        "engine": engine,
        "engine_label": ENGINES.get(engine, {}).get("label", engine),
        "host": row.get("host") or "",
        "port": row.get("port") or ENGINES.get(engine, {}).get("default_port", 0),
        "database": row.get("database") or "",
        "path": row.get("path") or "",
        "username": row.get("username") or "",
        "password_set": bool(row.get("password")),
        "ssl": bool(row.get("ssl")),
        "note": row.get("note") or "",
        "created_at": row.get("created_at") or 0,
        "last_test_at": row.get("last_test_at"),
    }


def list_connections() -> list[dict[str, Any]]:
    return [_public_connection(r) for r in _load_connections()]


def _connection(connection_id: str) -> dict[str, Any]:
    if not connection_id or connection_id == "local":
        return {
            "id": "local", "name": "当前工作台数据库", "engine": "sqlite",
            "path": str(DB_PATH), "database": DB_PATH.name,
        }
    for row in _load_connections():
        if row.get("id") == connection_id:
            return row
    raise DBAdminError("数据库连接不存在或已删除")


def _normalize_connection(body: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    old = old or {}
    engine = str(body.get("engine") or old.get("engine") or "sqlite").strip().lower()
    if engine == "mariadb":
        engine = "mysql"
    if engine == "postgresql":
        engine = "postgres"
    if engine not in ENGINES:
        raise DBAdminError("数据库类型只支持 SQLite、MySQL / MariaDB、PostgreSQL")
    name = str(body.get("name") or old.get("name") or "").strip()[:60]
    if not name:
        raise DBAdminError("请给连接起一个容易识别的名字")
    row: dict[str, Any] = {
        "id": old.get("id") or "db_" + uuid.uuid4().hex[:10],
        "name": name,
        "engine": engine,
        "created_at": old.get("created_at") or time.time(),
        "host": str(body.get("host") if "host" in body else old.get("host") or "127.0.0.1").strip()[:255],
        "port": _safe_int(body.get("port") if "port" in body else old.get("port"),
                          ENGINES[engine]["default_port"]),
        "database": str(body.get("database") if "database" in body else old.get("database") or "").strip()[:255],
        "username": str(body.get("username") if "username" in body else old.get("username") or "").strip()[:255],
        "note": str(body.get("note") if "note" in body else old.get("note") or "").strip()[:500],
        "ssl": bool(body.get("ssl") if "ssl" in body else old.get("ssl")),
    }
    if engine == "sqlite":
        path_text = str(body.get("path") if "path" in body else old.get("path") or "").strip()
        if not path_text:
            raise DBAdminError("SQLite 需要填写数据库文件路径")
        path = Path(os.path.expandvars(os.path.expanduser(path_text))).resolve()
        row["path"] = str(path)
        row["database"] = path.name
    else:
        row["path"] = ""
        if not row["host"]:
            raise DBAdminError("请填写数据库地址，本机可以填 127.0.0.1")
        if row["port"] <= 0 or row["port"] > 65535:
            raise DBAdminError("端口需要在 1–65535 之间")
        if not row["database"]:
            raise DBAdminError("请填写数据库名；迁移时可勾选“自动创建数据库”")
        if not row["username"]:
            raise DBAdminError("请填写数据库用户名")

    password = str(body.get("password") or "")
    if password:
        row["password"] = secrets_store.encrypt(password)
    elif old.get("password"):
        row["password"] = old["password"]
    else:
        row["password"] = ""
    row["last_test_at"] = old.get("last_test_at")
    return row


def save_connection(body: dict[str, Any], connection_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        rows = _load_connections()
        old = None
        if connection_id:
            old = next((r for r in rows if r.get("id") == connection_id), None)
            if not old:
                raise DBAdminError("连接不存在")
        row = _normalize_connection(body, old)
        if old:
            rows = [row if r.get("id") == connection_id else r for r in rows]
        else:
            rows.append(row)
        _save_connections(rows)
        return _public_connection(row)


def delete_connection(connection_id: str) -> None:
    if not connection_id or connection_id == "local":
        raise DBAdminError("当前工作台数据库不能在这里删除")
    with _LOCK:
        rows = _load_connections()
        kept = [r for r in rows if r.get("id") != connection_id]
        if len(kept) == len(rows):
            raise DBAdminError("连接不存在")
        _save_connections(kept)


def parse_connection_url(url: str) -> dict[str, Any]:
    """把 mysql://...、postgresql://...、sqlite:///... 拆成表单字段。"""
    raw = (url or "").strip()
    if not raw:
        raise DBAdminError("请先粘贴连接串")
    if raw.startswith("sqlite:///"):
        path = raw[len("sqlite:///"):]
        return {"engine": "sqlite", "path": unquote(path), "name": Path(path).stem or "SQLite"}
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").split("+")[0].lower()
    if scheme in ("mysql", "mariadb"):
        engine = "mysql"
    elif scheme in ("postgres", "postgresql"):
        engine = "postgres"
    else:
        raise DBAdminError("只识别 mysql://、mariadb://、postgresql:// 和 sqlite:/// 连接串")
    dbname = unquote((parsed.path or "").lstrip("/"))
    q = parse_qs(parsed.query or "")
    return {
        "engine": engine,
        "name": dbname or ENGINES[engine]["label"],
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or ENGINES[engine]["default_port"],
        "database": dbname,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "ssl": str(q.get("ssl", ["false"])[0]).lower() in ("1", "true", "yes", "on", "require"),
    }


def test_connection(connection_id: str) -> dict[str, Any]:
    record = _connection(connection_id)
    started = time.perf_counter()
    if record.get("engine") == "sqlite" and not Path(record.get("path") or "").exists():
        record["last_test_at"] = time.time()
        with _LOCK:
            rows = _load_connections()
            rows = [record if r.get("id") == connection_id else r for r in rows]
            _save_connections(rows)
        return {
            "ok": True, "engine": "sqlite", "info": "SQLite", "version": "尚未创建",
            "tables": 0, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "database": record.get("path") or "", "created": False,
            "message": "文件还不存在；第一次迁移或写入时会自动创建。",
        }
    with _open(record) as (engine, con):
        if engine == "sqlite":
            info = "SQLite"
            version_row = con.execute("SELECT sqlite_version()").fetchone()
            version = f"SQLite {version_row[0] if version_row else ''}"
            tables = len(_sqlite_tables(con))
        elif engine == "mysql":
            cur = con.cursor()
            cur.execute("SELECT VERSION() AS v")
            version = "MySQL " + str((cur.fetchone() or {}).get("v", ""))
            tables = len(_mysql_tables(con, record.get("database") or ""))
            info = "MySQL"
        else:
            cur = con.cursor()
            cur.execute("SELECT version(), current_database()")
            r = cur.fetchone() or {}
            version = str(r.get("version") or "PostgreSQL")
            tables = len(_pg_tables(con))
            info = "PostgreSQL"
    record["last_test_at"] = time.time()
    with _LOCK:
        rows = _load_connections()
        rows = [record if r.get("id") == connection_id else r for r in rows]
        _save_connections(rows)
    return {
        "ok": True, "engine": engine, "info": info, "version": version,
        "tables": tables, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "database": record.get("database") or record.get("path") or "",
    }


# ------------------------------------------------------------------ 元数据
def _sqlite_tables(con: Any) -> list[dict[str, Any]]:
    rows = con.execute(
        "SELECT name,type,sql FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    out = []
    virtual = [r["name"] for r in rows if "VIRTUAL TABLE" in str(r["sql"] or "").upper()]
    for r in rows:
        name = r["name"]
        if _is_internal_table(name):
            continue
        if "VIRTUAL TABLE" in str(r["sql"] or "").upper():
            continue
        if any(name == v or name.startswith(v + "_") for v in virtual):
            continue
        try:
            count = con.execute(f"SELECT COUNT(*) FROM {_q(name, 'sqlite')}").fetchone()[0]
        except Exception:
            count = 0
        out.append({"name": name, "kind": r["type"], "rows": int(count), "rows_estimated": False})
    return out


def _mysql_tables(con: Any, database: str) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        "SELECT TABLE_NAME AS name, TABLE_TYPE AS type, TABLE_ROWS AS rows "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s "
        "AND TABLE_TYPE IN ('BASE TABLE','VIEW') ORDER BY TABLE_NAME", (database,))
    rows = cur.fetchall()
    return [{
        "name": r.get("name"), "kind": "view" if r.get("type") == "VIEW" else "table",
        "rows": int(r.get("rows") or 0), "rows_estimated": True,
    } for r in rows]


def _pg_tables(con: Any) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        "SELECT c.relname AS name, CASE WHEN c.relkind='v' THEN 'view' ELSE 'table' END AS kind, "
        "GREATEST(c.reltuples, 0)::bigint AS rows "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p','v') ORDER BY c.relname")
    rows = cur.fetchall()
    return [{
        "name": r.get("name"), "kind": r.get("kind"),
        "rows": int(r.get("rows") or 0), "rows_estimated": True,
    } for r in rows]


def list_tables(connection_id: str = "local") -> list[dict[str, Any]]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        if engine == "sqlite":
            return _sqlite_tables(con)
        if engine == "mysql":
            return _mysql_tables(con, record.get("database") or "")
        return _pg_tables(con)


def _sqlite_schema(con: Any, table: str) -> dict[str, Any]:
    master = con.execute(
        "SELECT type,sql FROM sqlite_master WHERE name=? AND type IN ('table','view')",
        (table,)).fetchone()
    if not master:
        raise DBAdminError("数据表不存在")
    cols = con.execute(f"PRAGMA table_info({_q(table, 'sqlite')})").fetchall()
    columns = []
    for c in cols:
        columns.append({
            "name": c["name"], "type": c["type"] or "TEXT",
            "nullable": (not bool(c["notnull"])) and not int(c["pk"] or 0), "default": c["dflt_value"],
            "pk": int(c["pk"] or 0), "auto": bool(c["pk"] and "AUTOINCREMENT" in str(master["sql"] or "").upper()),
        })
    pk = [c["name"] for c in sorted(columns, key=lambda x: x["pk"] or 999) if c["pk"]]
    indexes = []
    for idx in con.execute(f"PRAGMA index_list({_q(table, 'sqlite')})").fetchall():
        if str(idx["origin"]) == "pk":
            continue
        cols2 = [r["name"] for r in con.execute(
            f"PRAGMA index_info({_q(idx['name'], 'sqlite')})").fetchall() if r["name"]]
        if cols2:
            indexes.append({
                "name": idx["name"], "unique": bool(idx["unique"]),
                "columns": cols2, "origin": idx["origin"],
            })
    fks = []
    for fk in con.execute(f"PRAGMA foreign_key_list({_q(table, 'sqlite')})").fetchall():
        fks.append({
            "name": f"fk_{table}_{fk['from']}_{fk['table']}",
            "from": fk["from"], "table": fk["table"], "to": fk["to"] or "id",
            "on_delete": fk["on_delete"] or "NO ACTION",
        })
    return {
        "table": table, "kind": master["type"], "columns": columns,
        "primary_key": pk, "indexes": indexes, "foreign_keys": fks,
        "create_sql": master["sql"] or "",
    }


def _mysql_schema(con: Any, database: str, table: str) -> dict[str, Any]:
    cur = con.cursor()
    cur.execute(
        "SELECT COLUMN_NAME AS name, COLUMN_TYPE AS type, IS_NULLABLE AS nullable, "
        "COLUMN_DEFAULT AS default_value, EXTRA AS extra, COLUMN_KEY AS col_key "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
        "ORDER BY ORDINAL_POSITION", (database, table))
    cols = cur.fetchall()
    if not cols:
        raise DBAdminError("数据表不存在")
    columns = [{
        "name": c["name"], "type": c["type"], "nullable": c["nullable"] == "YES",
        "default": c["default_value"], "pk": c["col_key"] == "PRI",
        "auto": "auto_increment" in str(c["extra"] or "").lower(),
    } for c in cols]
    pk = [c["name"] for c in columns if c["pk"]]
    cur.execute(f"SHOW INDEX FROM {_q(table, 'mysql')}")
    raw_idx = cur.fetchall()
    idx_map: dict[str, dict[str, Any]] = {}
    for r in raw_idx:
        if r.get("Key_name") == "PRIMARY":
            continue
        name = r.get("Key_name")
        item = idx_map.setdefault(name, {"name": name, "unique": not bool(r.get("Non_unique")),
                                         "columns": [], "origin": "c"})
        item["columns"].append((int(r.get("Seq_in_index") or 0), r.get("Column_name")))
    indexes = [{**v, "columns": [c for _, c in sorted(v["columns"])]} for v in idx_map.values()]
    cur.execute(
        "SELECT CONSTRAINT_NAME AS name, DELETE_RULE AS rule FROM information_schema.REFERENTIAL_CONSTRAINTS "
        "WHERE CONSTRAINT_SCHEMA=%s AND TABLE_NAME=%s", (database, table))
    delete_rules = {r["name"]: str(r["rule"] or "").replace("_", " ") for r in cur.fetchall()}
    cur.execute(
        "SELECT CONSTRAINT_NAME AS name, COLUMN_NAME AS `from`, REFERENCED_TABLE_NAME AS tab, "
        "REFERENCED_COLUMN_NAME AS `to` FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL "
        "ORDER BY ORDINAL_POSITION", (database, table))
    fks = []
    for r in cur.fetchall():
        fks.append({"name": r["name"], "from": r["from"], "table": r["tab"],
                    "to": r["to"], "on_delete": delete_rules.get(r["name"], "NO ACTION")})
    cur.execute(f"SHOW CREATE TABLE {_q(table, 'mysql')}")
    create_row = cur.fetchone() or {}
    create_sql = next((str(v) for k, v in create_row.items() if "create" in str(k).lower()), "")
    return {"table": table, "kind": "table", "columns": columns, "primary_key": pk,
            "indexes": indexes, "foreign_keys": fks, "create_sql": create_sql}


def _pg_schema(con: Any, table: str) -> dict[str, Any]:
    cur = con.cursor()
    cur.execute(
        "SELECT column_name AS name, data_type AS type, is_nullable AS nullable, "
        "column_default AS default_value FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
    cols = cur.fetchall()
    if not cols:
        raise DBAdminError("数据表不存在")
    cur.execute(
        "SELECT kcu.column_name AS name FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name=tc.constraint_name "
        "AND kcu.table_schema=tc.table_schema "
        "WHERE tc.table_schema='public' AND tc.table_name=%s AND tc.constraint_type='PRIMARY KEY' "
        "ORDER BY kcu.ordinal_position", (table,))
    pk = [r["name"] for r in cur.fetchall()]
    columns = [{
        "name": c["name"], "type": c["type"], "nullable": c["nullable"] == "YES",
        "default": c["default_value"], "pk": c["name"] in pk,
        "auto": "nextval" in str(c["default_value"] or "") or "identity" in str(c["type"] or "").lower(),
    } for c in cols]
    cur.execute(
        "SELECT indexname AS name, indexdef AS definition FROM pg_indexes "
        "WHERE schemaname='public' AND tablename=%s ORDER BY indexname", (table,))
    indexes = []
    for r in cur.fetchall():
        definition = str(r.get("definition") or "")
        if " UNIQUE " in definition:
            unique = True
        else:
            unique = definition.upper().startswith("CREATE UNIQUE")
        cols_match = re.search(r"\((.*?)\)", definition)
        idx_cols = [x.strip().strip('"') for x in cols_match.group(1).split(",")] if cols_match else []
        indexes.append({"name": r["name"], "unique": unique, "columns": idx_cols, "origin": "c"})
    cur.execute(
        "SELECT con.conname AS name, a.attname AS `from`, af.attname AS `to`, "
        "c2.relname AS tab, con.confdeltype AS del_type "
        "FROM pg_constraint con "
        "JOIN pg_class c1 ON c1.oid=con.conrelid "
        "JOIN pg_class c2 ON c2.oid=con.confrelid "
        "JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum=con.conkey[1] "
        "JOIN pg_attribute af ON af.attrelid=con.confrelid AND af.attnum=con.confkey[1] "
        "WHERE c1.relname=%s AND con.contype='f'", (table,))
    fks = []
    for r in cur.fetchall():
        rule = {"c": "CASCADE", "n": "SET NULL", "r": "RESTRICT"}.get(str(r.get("del_type")), "NO ACTION")
        fks.append({"name": r["name"], "from": r["from"], "table": r["tab"],
                    "to": r["to"], "on_delete": rule})
    return {"table": table, "kind": "table", "columns": columns, "primary_key": pk,
            "indexes": indexes, "foreign_keys": fks, "create_sql": ""}


def table_schema(connection_id: str, table: str) -> dict[str, Any]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        if engine == "sqlite":
            return _sqlite_schema(con, table)
        if engine == "mysql":
            return _mysql_schema(con, record.get("database") or "", table)
        return _pg_schema(con, table)


def _schema_columns(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in schema["columns"]}


def _table_exists(engine: str, con: Any, table: str, database: str = "") -> bool:
    if engine == "sqlite":
        row = con.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')",
                          (table,)).fetchone()
        return bool(row)
    if engine == "mysql":
        cur = con.cursor()
        cur.execute("SELECT 1 FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                    (database, table))
        return bool(cur.fetchone())
    cur = con.cursor()
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
                (table,))
    return bool(cur.fetchone())


def _rows_query(engine: str, schema: dict[str, Any], table: str, search: str,
                sort: str, order: str) -> tuple[str, str, list[Any]]:
    cols = schema["columns"]
    searchable = []
    for c in cols:
        typ = str(c.get("type") or "").upper()
        if "BLOB" in typ:
            continue
        if c["name"] in schema["primary_key"] and ("INT" in typ or "REAL" in typ):
            continue  # 数字主键搜起来全是命中，排除
        searchable.append(c["name"])
    searchable = searchable[:16]
    where = ""
    params: list[Any] = []
    if search.strip() and searchable:
        if engine == "sqlite":
            parts = [f"CAST({_q(c, engine)} AS TEXT) LIKE ?" for c in searchable]
        elif engine == "mysql":
            parts = [f"CAST({_q(c, engine)} AS CHAR) LIKE %s" for c in searchable]
        else:
            parts = [f"CAST({_q(c, engine)} AS TEXT) LIKE %s" for c in searchable]
        where = " WHERE (" + " OR ".join(parts) + ")"
        params = ["%" + search.strip()[:120] + "%"] * len(searchable)
    order_sql = ""
    if sort and sort in _schema_columns(schema):
        order_sql = f" ORDER BY {_q(sort, engine)} " + ("DESC" if str(order).lower() == "desc" else "ASC")
    elif schema["primary_key"]:
        order_sql = f" ORDER BY {_q(schema['primary_key'][0], engine)} DESC"
    count_sql = f"SELECT COUNT(*) AS c FROM {_q(table, engine)}{where}"
    data_sql = f"SELECT * FROM {_q(table, engine)}{where}{order_sql} LIMIT {_param(engine)} OFFSET {_param(engine)}"
    return count_sql, data_sql, params


def _key_encode(pk: dict[str, Any]) -> str:
    raw = json.dumps(pk, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _key_decode(key: str) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(str(key) + "=" * (-len(str(key)) % 4))
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except Exception as exc:
        raise DBAdminError("行标识已失效，请刷新表格后重试") from exc


def _row_pk(row: dict[str, Any], pk_cols: list[str]) -> dict[str, Any]:
    return {c: row.get(c) for c in pk_cols if c in row}


def _preview_cell(value: Any) -> Any:
    value = _json_value(value)
    if isinstance(value, str) and len(value) > MAX_PREVIEW:
        return value[:MAX_PREVIEW] + "…"
    return value


def table_rows(connection_id: str, table: str, limit: int = 50, offset: int = 0,
               search: str = "", sort: str = "", order: str = "desc") -> dict[str, Any]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        schema = (_sqlite_schema(con, table) if engine == "sqlite" else
                  _mysql_schema(con, record.get("database") or "", table) if engine == "mysql" else
                  _pg_schema(con, table))
        if schema["kind"] == "view":
            pass
        count_sql, data_sql, params = _rows_query(engine, schema, table, search, sort, order)
        count = _safe_int(_cur_rows(_exec(con, engine, count_sql, tuple(params)))[0]["c"])
        limit = max(1, min(MAX_ROWS, int(limit or 50)))
        offset = max(0, int(offset or 0))
        params2 = tuple(params) + (limit, offset)
        cur = _exec(con, engine, data_sql, params2)
        rows = _cur_rows(cur)
        pk_cols = schema["primary_key"]
        for row in rows:
            row["_key"] = _key_encode(_row_pk(row, pk_cols)) if pk_cols else ""
        for row in rows:
            for c in list(row.keys()):
                if c != "_key":
                    row[c] = _preview_cell(row[c])
        return {
            "table": table, "columns": schema["columns"], "primary_key": pk_cols,
            "rows": rows, "total": count, "limit": limit, "offset": offset,
            "editable": schema["kind"] == "table", "preview_chars": MAX_PREVIEW,
        }


def get_row(connection_id: str, table: str, key: str) -> dict[str, Any]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        schema = (_sqlite_schema(con, table) if engine == "sqlite" else
                  _mysql_schema(con, record.get("database") or "", table) if engine == "mysql" else
                  _pg_schema(con, table))
        pk = schema["primary_key"]
        if not pk:
            raise DBAdminError("此表没有主键，不能用表单编辑，请使用 SQL 控制台")
        values = _key_decode(key)
        where, params = _pk_where(engine, schema, values)
        row = _cur_rows(_exec(con, engine,
                              f"SELECT * FROM {_q(table, engine)} WHERE {where} LIMIT 1", tuple(params)))
        if not row:
            raise DBAdminError("这一行已经不存在，可能刚被其他操作删除")
        row[0]["_key"] = key
        return {"table": table, "columns": schema["columns"], "row": row[0],
                "primary_key": pk}


def _pk_where(engine: str, schema: dict[str, Any], values: dict[str, Any]) -> tuple[str, list[Any]]:
    cols = _schema_columns(schema)
    pk = schema["primary_key"]
    if not pk:
        raise DBAdminError("此表没有主键")
    if set(pk) - set(values):
        raise DBAdminError("行主键信息不完整")
    parts, params = [], []
    for c in pk:
        if c not in cols:
            raise DBAdminError(f"主键字段不存在：{c}")
        parts.append(f"{_q(c, engine)}={_param(engine)}")
        params.append(_coerce(values.get(c), cols[c]))
    return " AND ".join(parts), params


def _coerce(value: Any, col: dict[str, Any]) -> Any:
    if value is None or value == "":
        if col.get("nullable") or not col.get("pk"):
            return None
        if "TEXT" in str(col.get("type") or "").upper():
            return ""
        return None
    typ = str(col.get("type") or "").upper()
    try:
        if "INT" in typ or "BOOL" in typ:
            return int(value)
        if "REAL" in typ or "DOUBLE" in typ or "FLOAT" in typ or "NUMERIC" in typ or "DECIMAL" in typ:
            return float(value)
    except Exception as exc:
        raise DBAdminError(f"字段 {col['name']} 需要数字，当前值：{value}") from exc
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _values_for_write(schema: dict[str, Any], values: dict[str, Any],
                      skip_pk: bool = True, create_mode: bool = False) -> dict[str, Any]:
    cols = _schema_columns(schema)
    out: dict[str, Any] = {}
    for name, val in (values or {}).items():
        if name not in cols:
            raise DBAdminError(f"字段不存在：{name}")
        if name in schema["primary_key"] and skip_pk:
            # 新增时，自增主键留给数据库；文本/联合主键必须允许用户填写
            if not create_mode or cols[name].get("auto"):
                continue
        out[name] = _coerce(val, cols[name])
    return out


def create_row(connection_id: str, table: str, values: dict[str, Any]) -> dict[str, Any]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        schema = (_sqlite_schema(con, table) if engine == "sqlite" else
                  _mysql_schema(con, record.get("database") or "", table) if engine == "mysql" else
                  _pg_schema(con, table))
        if schema["kind"] == "view":
            raise DBAdminError("视图不能直接新增行")
        clean = _values_for_write(schema, values, skip_pk=True, create_mode=True)
        if clean:
            names = list(clean)
            sql = (f"INSERT INTO {_q(table, engine)} ({','.join(_q(c, engine) for c in names)}) "
                   f"VALUES ({_ph(engine, len(names))})")
            cur = _exec(con, engine, sql, tuple(clean[c] for c in names))
        else:
            cur = _exec(con, engine, f"INSERT INTO {_q(table, engine)} DEFAULT VALUES")
        _commit(con, engine)
        last_id = getattr(cur, "lastrowid", None)
        return {"ok": True, "last_id": last_id, "affected": 1}


def update_row(connection_id: str, table: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        schema = (_sqlite_schema(con, table) if engine == "sqlite" else
                  _mysql_schema(con, record.get("database") or "", table) if engine == "mysql" else
                  _pg_schema(con, table))
        if schema["kind"] == "view":
            raise DBAdminError("视图不能直接修改")
        clean = _values_for_write(schema, values, skip_pk=True)
        if not clean:
            raise DBAdminError("没有需要保存的字段")
        pk = _key_decode(key)
        where, params = _pk_where(engine, schema, pk)
        sql = (f"UPDATE {_q(table, engine)} SET "
               + ",".join(f"{_q(c, engine)}={_param(engine)}" for c in clean)
               + f" WHERE {where}")
        cur = _exec(con, engine, sql, tuple(clean.values()) + tuple(params))
        _commit(con, engine)
        return {"ok": True, "affected": int(getattr(cur, "rowcount", 1) or 0)}


def delete_row(connection_id: str, table: str, key: str) -> dict[str, Any]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        schema = (_sqlite_schema(con, table) if engine == "sqlite" else
                  _mysql_schema(con, record.get("database") or "", table) if engine == "mysql" else
                  _pg_schema(con, table))
        if schema["kind"] == "view":
            raise DBAdminError("视图不能删除行")
        pk = _key_decode(key)
        where, params = _pk_where(engine, schema, pk)
        cur = _exec(con, engine, f"DELETE FROM {_q(table, engine)} WHERE {where}", tuple(params))
        _commit(con, engine)
        return {"ok": True, "affected": int(getattr(cur, "rowcount", 1) or 0)}


# ------------------------------------------------------------------ 表管理
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_COLUMN_TYPES = {"TEXT", "VARCHAR(255)", "INTEGER", "REAL", "BOOLEAN", "DATETIME", "BLOB"}


def _admin_table_name(name: str) -> str:
    clean = str(name or "").strip()
    if not _IDENT_RE.match(clean):
        raise DBAdminError("表名只能用字母、数字和下划线，且不能以数字开头")
    return clean


def _guard_local_table(connection_id: str, table: str) -> None:
    if connection_id != "local":
        return
    if _is_internal_table(table) or table in CORE_TABLES:
        raise DBAdminError("这是工作台运行依赖的表，不能改名或删除；如需清理数据，请使用“清空数据”")


def _admin_table(connection_id: str, table: str) -> dict[str, Any]:
    for item in list_tables(connection_id):
        if item["name"] == table:
            if item.get("kind") == "view":
                raise DBAdminError("视图不能执行这个操作")
            return item
    raise DBAdminError(f"表 {table} 不存在")


def _safety_snapshot(reason: str) -> str:
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dest = BACKUP_DIR / f"auto-{reason}-{time.strftime('%Y%m%d-%H%M%S')}.db"
        _snapshot(dest)
        return str(dest)
    except Exception:
        return ""


def _ddl_column(engine: str, col: dict[str, Any]) -> str:
    name = _admin_table_name(col.get("name") or "")
    kind = str(col.get("type") or "TEXT").upper()
    if kind not in _COLUMN_TYPES:
        raise DBAdminError(f"字段 {name} 的类型不支持")
    pk = bool(col.get("primary_key"))
    auto = bool(col.get("auto")) and pk
    nullable = bool(col.get("nullable", True)) and not pk
    if auto and kind != "INTEGER":
        raise DBAdminError("自增主键必须是整数类型")
    mapped = {
        "sqlite": {"TEXT": "TEXT", "VARCHAR(255)": "VARCHAR(255)", "INTEGER": "INTEGER",
                   "REAL": "REAL", "BOOLEAN": "INTEGER", "DATETIME": "TEXT", "BLOB": "BLOB"},
        "mysql": {"TEXT": "LONGTEXT", "VARCHAR(255)": "VARCHAR(255)", "INTEGER": "BIGINT",
                  "REAL": "DOUBLE", "BOOLEAN": "TINYINT(1)", "DATETIME": "DATETIME", "BLOB": "LONGBLOB"},
        "postgres": {"TEXT": "TEXT", "VARCHAR(255)": "VARCHAR(255)", "INTEGER": "BIGINT",
                     "REAL": "DOUBLE PRECISION", "BOOLEAN": "BOOLEAN", "DATETIME": "TIMESTAMP", "BLOB": "BYTEA"},
    }[engine][kind]
    if pk and engine == "mysql" and mapped == "LONGTEXT":
        mapped = "VARCHAR(255)"
    if pk and auto:
        if engine == "sqlite":
            return f"{_q(name, engine)} INTEGER PRIMARY KEY AUTOINCREMENT"
        if engine == "mysql":
            return f"{_q(name, engine)} BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY"
        return f'{_q(name, engine)} BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY'
    part = f"{_q(name, engine)} {mapped}"
    if not nullable:
        part += " NOT NULL"
    return part


def create_table(connection_id: str, table: str, columns: list[dict[str, Any]]) -> dict[str, Any]:
    clean = _admin_table_name(table)
    if not columns or len(columns) > 60:
        raise DBAdminError("新建表需要 1～60 个字段")
    names = [_admin_table_name(c.get("name") or "") for c in columns]
    if len(set(names)) != len(names):
        raise DBAdminError("字段名不能重复")
    if sum(1 for c in columns if c.get("primary_key")) > 1:
        raise DBAdminError("只能设置一个主键字段")
    record = _connection(connection_id)
    existing = {t["name"] for t in list_tables(connection_id)}
    if clean in existing:
        raise DBAdminError(f"表 {clean} 已存在")
    with _open(record) as (engine, con):
        defs = [_ddl_column(engine, c) for c in columns]
        pk = next((_admin_table_name(c["name"]) for c in columns if c.get("primary_key")), None)
        auto_pk = any(c.get("primary_key") and c.get("auto") for c in columns)
        if pk and not auto_pk:
            defs.append(f"PRIMARY KEY ({_q(pk, engine)})")
        ddl = f"CREATE TABLE {_q(clean, engine)} (" + ", ".join(defs) + ")"
        _exec(con, engine, ddl)
        _commit(con, engine)
    return {"ok": True, "table": clean, "columns": len(columns), "engine": record.get("engine")}


def rename_table(connection_id: str, table: str, new_name: str) -> dict[str, Any]:
    old = _admin_table_name(table)
    target = _admin_table_name(new_name)
    if old == target:
        raise DBAdminError("新表名和原表名相同")
    _guard_local_table(connection_id, old)
    record = _connection(connection_id)
    _admin_table(connection_id, old)
    existing = {t["name"] for t in list_tables(connection_id)}
    if target in existing:
        raise DBAdminError(f"表 {target} 已存在")
    backup = _safety_snapshot("rename") if connection_id == "local" else ""
    with _open(record) as (engine, con):
        if engine == "mysql":
            sql = f"RENAME TABLE {_q(old, engine)} TO {_q(target, engine)}"
        else:
            sql = f"ALTER TABLE {_q(old, engine)} RENAME TO {_q(target, engine)}"
        _exec(con, engine, sql)
        _commit(con, engine)
    return {"ok": True, "from": old, "to": target, "backup": backup}


def truncate_table(connection_id: str, table: str, confirm: str) -> dict[str, Any]:
    clean = _admin_table_name(table)
    if str(confirm or "").strip() != clean:
        raise DBAdminError("请输入完整表名确认清空")
    record = _connection(connection_id)
    _admin_table(connection_id, clean)
    backup = _safety_snapshot("truncate") if connection_id == "local" else ""
    with _open(record) as (engine, con):
        if engine == "sqlite":
            cur = con.execute(f"DELETE FROM {_q(clean, engine)}")
            affected = int(getattr(cur, "rowcount", 0) or 0)
            has_seq = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone()
            if has_seq:
                con.execute("DELETE FROM sqlite_sequence WHERE name=?", (clean,))
        elif engine == "mysql":
            cur = _exec(con, engine, f"TRUNCATE TABLE {_q(clean, engine)}")
            affected = int(getattr(cur, "rowcount", 0) or 0)
        else:
            cur = _exec(con, engine, f"TRUNCATE TABLE {_q(clean, engine)} RESTART IDENTITY")
            affected = int(getattr(cur, "rowcount", 0) or 0)
        _commit(con, engine)
    return {"ok": True, "table": clean, "affected": affected, "backup": backup}


def drop_table(connection_id: str, table: str, confirm: str) -> dict[str, Any]:
    clean = _admin_table_name(table)
    _guard_local_table(connection_id, clean)
    if str(confirm or "").strip() != clean:
        raise DBAdminError("请输入完整表名确认删除")
    record = _connection(connection_id)
    _admin_table(connection_id, clean)
    backup = _safety_snapshot("drop") if connection_id == "local" else ""
    with _open(record) as (engine, con):
        _exec(con, engine, f"DROP TABLE {_q(clean, engine)}")
        _commit(con, engine)
    return {"ok": True, "table": clean, "backup": backup}


# ------------------------------------------------------------------ 概览 / 健康
def overview(connection_id: str = "local") -> dict[str, Any]:
    record = _connection(connection_id)
    tables = list_tables(connection_id)
    table_count = len([t for t in tables if t["kind"] == "table"])
    view_count = len([t for t in tables if t["kind"] == "view"])
    row_count = sum(int(t.get("rows") or 0) for t in tables)
    result = {
        "connection": _public_connection(record) if connection_id != "local" else {
            "id": "local", "name": "当前工作台数据库", "engine": "sqlite",
            "engine_label": "SQLite", "path": str(DB_PATH), "database": DB_PATH.name,
            "host": "", "port": 0, "username": "", "password_set": False, "ssl": False,
        },
        "table_count": table_count, "view_count": view_count,
        "row_count": row_count, "row_count_estimated": any(t.get("rows_estimated") for t in tables),
    }
    if record.get("engine") == "sqlite":
        path = Path(record.get("path") or DB_PATH)
        result["size"] = path.stat().st_size if path.exists() else 0
        result["path"] = str(path)
        try:
            version_row = sqlite3.connect(str(path)).execute("SELECT sqlite_version()").fetchone()
            result["version"] = "SQLite " + str(version_row[0]) if version_row else "SQLite"
        except Exception:
            result["version"] = "SQLite"
        try:
            con = sqlite3.connect(str(path))
            result["schema_version"] = int(con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0)
            con.close()
        except Exception:
            result["schema_version"] = 0
    else:
        with _open(record) as (engine, con):
            if engine == "mysql":
                cur = con.cursor()
                cur.execute("SELECT VERSION() AS v")
                result["version"] = "MySQL " + str((cur.fetchone() or {}).get("v", ""))
            else:
                cur = con.cursor()
                cur.execute("SELECT version() AS v")
                result["version"] = str((cur.fetchone() or {}).get("v", "PostgreSQL"))
    result["engines"] = engine_info()
    result["protected_tables"] = sorted(CORE_TABLES) if connection_id == "local" else []
    return result


def health(connection_id: str = "local") -> dict[str, Any]:
    record = _connection(connection_id)
    checks: list[dict[str, Any]] = []
    started = time.perf_counter()
    with _open(record) as (engine, con):
        if engine == "sqlite":
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
            fk_rows = con.execute("PRAGMA foreign_key_check").fetchmany(100)
            page_size = int(con.execute("PRAGMA page_size").fetchone()[0] or 0)
            page_count = int(con.execute("PRAGMA page_count").fetchone()[0] or 0)
            free_pages = int(con.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            checks.append({"name": "完整性检查", "ok": str(integrity).lower() == "ok",
                           "detail": str(integrity)})
            checks.append({"name": "外键检查", "ok": not fk_rows,
                           "detail": "未发现断裂外键" if not fk_rows else f"发现 {len(fk_rows)} 条异常"})
            checks.append({"name": "可回收空间", "ok": True,
                           "detail": f"{round(free_pages * page_size / 1024 / 1024, 2)} MB 空闲页"})
            checks.append({"name": "文件大小", "ok": True,
                           "detail": f"{round(page_count * page_size / 1024 / 1024, 2)} MB"})
        elif engine == "mysql":
            cur = con.cursor()
            cur.execute("SELECT VERSION() AS v, DATABASE() AS d")
            row = cur.fetchone() or {}
            checks.append({"name": "版本", "ok": True, "detail": "MySQL " + str(row.get("v") or "")})
            checks.append({"name": "当前数据库", "ok": bool(row.get("d")), "detail": row.get("d") or "未选择"})
            cur.execute("SHOW TABLES")
            checks.append({"name": "表访问", "ok": True, "detail": f"可读取 {len(cur.fetchall())} 个表"})
        else:
            cur = con.cursor()
            cur.execute("SELECT version() AS v, current_database() AS d")
            row = cur.fetchone() or {}
            checks.append({"name": "版本", "ok": True, "detail": str(row.get("v") or "PostgreSQL")})
            checks.append({"name": "当前数据库", "ok": bool(row.get("d")), "detail": row.get("d") or "未选择"})
            cur.execute("SELECT count(*) AS c FROM information_schema.tables WHERE table_schema='public'")
            checks.append({"name": "表访问", "ok": True,
                           "detail": f"可读取 {int((cur.fetchone() or {}).get('c') or 0)} 个表"})
    return {"ok": all(c["ok"] for c in checks), "checks": checks,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def vacuum(connection_id: str = "local") -> dict[str, Any]:
    record = _connection(connection_id)
    if record.get("engine") != "sqlite":
        raise DBAdminError("空间整理目前只对 SQLite 开放；MySQL/PostgreSQL 请使用服务端的 OPTIMIZE/VACUUM 策略")
    before = Path(record["path"]).stat().st_size
    with _open(record) as (engine, con):
        con.execute("VACUUM")
        con.commit()
    after = Path(record["path"]).stat().st_size
    return {"ok": True, "before": before, "after": after,
            "saved": max(0, before - after)}


# ------------------------------------------------------------------ SQL 控制台
_READ_ONLY_START = re.compile(r"^\s*(select|with|explain|show|describe|desc|pragma)\b", re.I)
_WRITE_WORD = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|replace|merge|vacuum|attach|detach)\b", re.I)


def run_query(connection_id: str, sql: str, allow_write: bool = False,
              limit: int = 100) -> dict[str, Any]:
    raw = (sql or "").strip()
    if not raw:
        raise DBAdminError("请输入 SQL")
    if ";" in raw.rstrip(";"):
        raise DBAdminError("一次只执行一条 SQL；请删掉多余的分号后再试")
    raw = raw.rstrip(";").strip()
    if not allow_write:
        if not _READ_ONLY_START.match(raw):
            raise DBAdminError("安全模式只允许 SELECT / WITH / SHOW / EXPLAIN；写入请打开“允许写操作”")
        if raw.lower().startswith("with") and _WRITE_WORD.search(raw):
            raise DBAdminError("安全模式不接受带写操作的 WITH 语句")
    limit = max(1, min(500, int(limit or 100)))
    started = time.perf_counter()
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        cur = _exec(con, engine, raw, ())
        cols, rows = _raw_result_rows(cur)
        if allow_write:
            _commit(con, engine)
        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]
        return {
            "columns": cols, "rows": rows, "affected": int(getattr(cur, "rowcount", -1) or 0),
            "last_id": getattr(cur, "lastrowid", None),
            "truncated": truncated, "limit": limit,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "write": bool(allow_write),
        }


# ------------------------------------------------------------------ 备份与导出
def _snapshot(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(DB_PATH), timeout=30)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    return dest


def create_database_backup(connection_id: str = "local") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    record = _connection(connection_id)
    if record.get("engine") != "sqlite":
        raise DBAdminError("外部 MySQL/PostgreSQL 请使用“导出 SQL 脚本”，本机 SQLite 可直接生成 .db 快照")
    dest = BACKUP_DIR / f"database-{stamp}.db"
    if connection_id == "local":
        _snapshot(dest)
    else:
        src = sqlite3.connect(record["path"], timeout=30)
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()
    _prune_backups()
    return dest


def _prune_backups(keep: int = 10) -> None:
    try:
        files = sorted(BACKUP_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[keep:]:
            p.unlink()
    except Exception:
        pass


def _csv_cell(value: Any) -> str:
    value = _json_value(value)
    s = "" if value is None else str(value)
    if any(ch in s for ch in ',"\n\r'):
        return '"' + s.replace('"', '""') + '"'
    return s


def export_table_csv(connection_id: str, table: str) -> tuple[str, bytes]:
    record = _connection(connection_id)
    with _open(record) as (engine, con):
        schema = (_sqlite_schema(con, table) if engine == "sqlite" else
                  _mysql_schema(con, record.get("database") or "", table) if engine == "mysql" else
                  _pg_schema(con, table))
        cols = [c["name"] for c in schema["columns"]]
        rows = _cur_rows(_exec(con, engine, f"SELECT * FROM {_q(table, engine)}"))
    lines = [",".join(_csv_cell(c) for c in cols)]
    for row in rows:
        lines.append(",".join(_csv_cell(row.get(c)) for c in cols))
    name = f"{table}-{time.strftime('%Y%m%d-%H%M%S')}.csv"
    return name, ("\ufeff" + "\n".join(lines)).encode("utf-8")


# ------------------------------------------------------------------ 迁移
def _textual(col: dict[str, Any]) -> bool:
    typ = str(col.get("type") or "").upper()
    return any(x in typ for x in ("TEXT", "CHAR", "CLOB", "VARCHAR", "STRING"))


def _mapped_type(col: dict[str, Any], engine: str, indexed: bool = False) -> str:
    typ = str(col.get("type") or "").upper()
    if "INT" in typ or "BOOL" in typ:
        return "BIGINT"
    if any(x in typ for x in ("REAL", "FLOA", "DOUB", "NUMERIC", "DECIMAL")):
        return "DOUBLE PRECISION" if engine == "postgres" else "DOUBLE"
    if "BLOB" in typ or "BINARY" in typ:
        return "BYTEA" if engine == "postgres" else "LONGBLOB"
    if _textual(col):
        if indexed:
            return "VARCHAR(255)" if engine == "mysql" else "VARCHAR"
        return "TEXT" if engine == "postgres" else "LONGTEXT"
    return "TEXT" if engine == "postgres" else "LONGTEXT"


def _clean_default(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.upper() == "NULL":
        return None
    if "(" in s or ")" in s:
        return None
    return s


def _create_table_sql(schema: dict[str, Any], engine: str) -> str:
    indexed: set[str] = set()
    for idx in schema.get("indexes") or []:
        for c in idx.get("columns") or []:
            indexed.add(c)
    indexed.update(schema.get("primary_key") or [])
    pks = schema.get("primary_key") or []
    parts: list[str] = []
    auto_single = len(pks) == 1 and next((c for c in schema["columns"] if c["name"] == pks[0]), {}).get("auto")
    for col in schema["columns"]:
        name = col["name"]
        typ = _mapped_type(col, engine, name in indexed)
        if auto_single and name == pks[0]:
            if engine == "mysql":
                parts.append(f"{_q(name, engine)} BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY")
            else:
                parts.append(f"{_q(name, engine)} BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
            continue
        piece = f"{_q(name, engine)} {typ}"
        if col.get("pk") or not col.get("nullable"):
            piece += " NOT NULL"
        if not col.get("pk") and not auto_single:
            default = _clean_default(col.get("default"))
            if default and not (engine == "mysql" and _textual(col)):
                piece += " DEFAULT " + default
        parts.append(piece)
    if pks and not auto_single:
        parts.append("PRIMARY KEY (" + ",".join(_q(c, engine) for c in pks) + ")")
    suffix = ""
    if engine == "mysql":
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    return f"CREATE TABLE {_q(schema['table'], engine)} (\n  " + ",\n  ".join(parts) + f"\n){suffix}"


def _index_sql(schema: dict[str, Any], engine: str, limit: int = 63) -> list[str]:
    out = []
    for idx in schema.get("indexes") or []:
        cols = [c for c in (idx.get("columns") or []) if c]
        if not cols or set(cols) == set(schema.get("primary_key") or []):
            continue
        name = str(idx.get("name") or "")[:limit - 6]
        if engine == "mysql" and len(name) > 63:
            name = name[:30] + "_" + uuid.uuid4().hex[:8]
        unique = "UNIQUE " if idx.get("unique") else ""
        out.append(f"CREATE {unique}INDEX {_q(name, engine)} ON "
                   f"{_q(schema['table'], engine)} ({','.join(_q(c, engine) for c in cols)})")
    return out


def _fk_sql(schema: dict[str, Any], engine: str) -> list[str]:
    out = []
    for fk in schema.get("foreign_keys") or []:
        if not fk.get("from") or not fk.get("table") or not fk.get("to"):
            continue
        name = str(fk.get("name") or "")[:60]
        if engine == "mysql" and len(name) > 63:
            name = "fk_" + uuid.uuid4().hex[:12]
        rule = str(fk.get("on_delete") or "NO ACTION").upper()
        if rule not in ("CASCADE", "SET NULL", "RESTRICT", "NO ACTION"):
            rule = "NO ACTION"
        out.append(
            f"ALTER TABLE {_q(schema['table'], engine)} ADD CONSTRAINT {_q(name, engine)} "
            f"FOREIGN KEY ({_q(fk['from'], engine)}) REFERENCES {_q(fk['table'], engine)} "
            f"({_q(fk['to'], engine)}) ON DELETE {rule}")
    return out


def _source_schemas() -> tuple[Path, list[dict[str, Any]], dict[str, int]]:
    temp_dir = DATA_DIR / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    snap = temp_dir / f"migrate-source-{uuid.uuid4().hex[:8]}.db"
    _snapshot(snap)
    con = sqlite3.connect(str(snap), timeout=20)
    con.row_factory = sqlite3.Row
    try:
        tables = _sqlite_tables(con)
        base = [t for t in tables if t["kind"] == "table"]
        schemas = [_sqlite_schema(con, t["name"]) for t in base]
        counts = {t["name"]: int(t["rows"] or 0) for t in base}
        return snap, schemas, counts
    finally:
        con.close()


def _target_tables(engine: str, con: Any, database: str = "") -> list[str]:
    if engine == "mysql":
        cur = con.cursor()
        cur.execute("SELECT TABLE_NAME AS name FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE'", (database,))
        return [r["name"] for r in cur.fetchall()]
    if engine == "postgres":
        cur = con.cursor()
        cur.execute("SELECT tablename AS name FROM pg_tables WHERE schemaname='public'")
        return [r["name"] for r in cur.fetchall()]
    if engine == "sqlite":
        return [r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    return []


def _ensure_target_database(record: dict[str, Any], create_database: bool) -> None:
    engine = record.get("engine")
    if engine == "sqlite":
        target = Path(record["path"]).resolve()
        if target == Path(DB_PATH).resolve():
            raise DBAdminError("迁移目标不能是当前工作台主库本身")
        target.parent.mkdir(parents=True, exist_ok=True)
        return
    if not create_database:
        return
    dbname = str(record.get("database") or "")
    if engine == "mysql":
        with _open(record, server=True) as (_, con):
            con.cursor().execute(
                f"CREATE DATABASE IF NOT EXISTS {_q(dbname, 'mysql')} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        return
    with _open(record, database="postgres") as (_, con):
        con.autocommit = True
        cur = con.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {_q(dbname, 'postgres')}")


def preflight_migration(connection_id: str, create_database: bool = False,
                        overwrite: bool = False) -> dict[str, Any]:
    record = _connection(connection_id)
    if connection_id == "local":
        raise DBAdminError("迁移目标不能是当前工作台数据库本身")
    engine = record.get("engine")
    if engine not in ("mysql", "postgres", "sqlite"):
        raise DBAdminError("只支持迁移到 MySQL / MariaDB、PostgreSQL 或另一个 SQLite 文件")
    tables = list_tables("local")
    base = [t for t in tables if t["kind"] == "table"]
    row_count = sum(int(t["rows"] or 0) for t in base)
    warnings = ["kb_fts 是 SQLite 全文检索索引，不会复制到 MySQL/PostgreSQL；工作台主库仍是本地 SQLite。"]
    target_exists = []
    try:
        _ensure_target_database(record, create_database)
        if engine == "sqlite" and not Path(record.get("path") or "").exists():
            target_exists = []
        else:
            with _open(record) as (_, con):
                target_exists = _target_tables(engine, con, record.get("database") or "")
    except DBAdminError as exc:
        return {"ok": False, "error": str(exc), "tables": len(base), "rows": row_count,
                "warnings": warnings, "target_tables": []}
    conflicts = sorted(set(target_exists) & ({t["name"] for t in base} | {"_wb_migration_state"}))
    return {
        "ok": True, "engine": engine, "engine_label": ENGINES[engine]["label"],
        "database": record.get("database") or record.get("path"),
        "tables": len(base), "rows": row_count, "target_table_count": len(target_exists),
        "conflicts": conflicts, "overwrite": bool(overwrite),
        "ready": not conflicts or overwrite, "warnings": warnings,
        "message": ("目标库已有同名表；必须开启“覆盖同名表”才能继续。" if conflicts and not overwrite
                    else "检查通过，可以开始迁移。"),
    }


def migrate_to(connection_id: str, create_database: bool = False, overwrite: bool = False,
               progress: Callable[[int, str, dict[str, Any] | None], None] | None = None) -> dict[str, Any]:
    """把本地 SQLite 快照复制到目标库。progress(pct, message, detail)。"""
    callback = progress or (lambda *_: None)
    record = _connection(connection_id)
    if connection_id == "local":
        raise DBAdminError("不能迁移到当前库本身")
    engine = record.get("engine")
    started = time.time()
    callback(2, "正在生成源库一致性快照…", None)
    snapshot, schemas, source_counts = _source_schemas()
    warnings: list[str] = []
    try:
        _ensure_target_database(record, create_database)
        if engine == "sqlite":
            target = Path(record["path"])
            if target.exists() and not overwrite:
                raise DBAdminError("目标 SQLite 文件已存在；请先勾选“覆盖同名表/覆盖目标文件”")
            callback(40, "正在复制 SQLite 数据库…", None)
            dst = sqlite3.connect(str(target))
            src = sqlite3.connect(str(snapshot))
            try:
                src.backup(dst)
                dst.commit()
                verified = {}
                for schema in schemas:
                    name = schema["table"]
                    expected = source_counts.get(name, 0)
                    try:
                        got = int(dst.execute(f"SELECT COUNT(*) FROM {_q(name, 'sqlite')}").fetchone()[0])
                    except Exception:
                        got = 0
                    verified[name] = {"expected": expected, "actual": got, "ok": expected == got}
                    if expected != got:
                        warnings.append(f"{name} 行数不一致：源 {expected}，目标 {got}")
            finally:
                dst.close()
                src.close()
            callback(100, "SQLite 迁移完成", None)
            result = {"ok": all(v["ok"] for v in verified.values()), "engine": "sqlite",
                      "tables": len(verified), "rows": sum(source_counts.values()),
                      "verified": verified, "warnings": warnings,
                      "elapsed": round(time.time() - started, 1),
                      "target": str(target)}
            _append_history(result)
            return result

        callback(8, "正在检查目标库…", None)
        with _open(record) as (engine, con):
            target_names = _target_tables(engine, con, record.get("database") or "")
            conflicts = sorted(set(target_names) & {s["table"] for s in schemas})
            if overwrite and "_wb_migration_state" in target_names:
                conflicts = sorted(set(conflicts) | {"_wb_migration_state"})
            if conflicts and not overwrite:
                raise DBAdminError("目标库已有同名表：" + "、".join(conflicts[:8]) + "；请勾选覆盖后重试")
            if conflicts:
                callback(10, "正在清理目标库同名表…", {"tables": conflicts})
                if engine == "mysql":
                    con.cursor().execute("SET FOREIGN_KEY_CHECKS=0")
                for name in conflicts:
                    _exec(con, engine, f"DROP TABLE IF EXISTS {_q(name, engine)} CASCADE"
                          if engine == "postgres" else f"DROP TABLE IF EXISTS {_q(name, engine)}")
                if engine == "mysql":
                    con.cursor().execute("SET FOREIGN_KEY_CHECKS=1")
                _commit(con, engine)

            callback(15, f"正在创建 {len(schemas)} 张表…", None)
            for i, schema in enumerate(schemas, 1):
                _exec(con, engine, _create_table_sql(schema, engine))
                callback(15 + int(15 * i / max(1, len(schemas))), f"创建表 {schema['table']}",
                         {"table": schema["table"]})
            _commit(con, engine)

            total_rows = sum(source_counts.values()) or 1
            copied_rows = 0
            source = sqlite3.connect(str(snapshot))
            source.row_factory = sqlite3.Row
            try:
                for i, schema in enumerate(schemas, 1):
                    table = schema["table"]
                    cols = [c["name"] for c in schema["columns"]]
                    if schema["kind"] != "table":
                        continue
                    callback(31, f"正在复制 {table}（{source_counts.get(table, 0)} 行）…",
                             {"table": table})
                    cur = source.execute(f"SELECT * FROM {_q(table, 'sqlite')}")
                    batch = cur.fetchmany(400)
                    while batch:
                        rows = [[_json_value(r[c]) for c in cols] for r in batch]
                        if rows:
                            sql = (f"INSERT INTO {_q(table, engine)} "
                                   f"({','.join(_q(c, engine) for c in cols)}) VALUES "
                                   f"({_ph(engine, len(cols))})")
                            if engine == "mysql":
                                target_cur = con.cursor()
                                target_cur.executemany(sql, [tuple(r) for r in rows])
                            else:
                                target_cur = con.cursor()
                                target_cur.executemany(sql, [tuple(r) for r in rows])
                                con.commit()
                            copied_rows += len(rows)
                        pct = 31 + int(47 * copied_rows / total_rows)
                        callback(min(78, pct), f"{table}：已复制 {copied_rows}/{total_rows} 行",
                                 {"table": table, "rows": copied_rows, "total": total_rows})
                        batch = cur.fetchmany(400)
            finally:
                source.close()

            callback(80, "正在创建索引和外键…", None)
            for schema in schemas:
                for sql in _index_sql(schema, engine):
                    try:
                        _exec(con, engine, sql)
                    except Exception as exc:
                        warnings.append(f"索引 {schema['table']}：{exc}")
                for sql in _fk_sql(schema, engine):
                    try:
                        _exec(con, engine, sql)
                    except Exception as exc:
                        warnings.append(f"外键 {schema['table']}：{exc}")
            _commit(con, engine)

            if engine == "postgres":
                # identity 序列要推到已复制的最大 id 之后，避免后续插入撞主键
                for schema in schemas:
                    if len(schema.get("primary_key") or []) != 1:
                        continue
                    pk = schema["primary_key"][0]
                    auto = next((c.get("auto") for c in schema["columns"]
                                 if c["name"] == pk), False)
                    if not auto:
                        continue
                    try:
                        con.cursor().execute(
                            f"SELECT setval(pg_get_serial_sequence({_q(schema['table'], 'postgres')}, "
                            f"{_q(pk, 'postgres')}), "
                            f"COALESCE((SELECT MAX({_q(pk, 'postgres')}) FROM {_q(schema['table'], 'postgres')}),0)+1, false)")
                    except Exception as exc:
                        warnings.append(f"序列 {schema['table']}：{exc}")
                con.commit()

            callback(90, "正在校验行数…", None)
            verified: dict[str, Any] = {}
            for schema in schemas:
                name = schema["table"]
                if engine == "mysql":
                    cur2 = con.cursor()
                    cur2.execute(f"SELECT COUNT(*) AS c FROM {_q(name, engine)}")
                    got = int((cur2.fetchone() or {}).get("c") or 0)
                elif engine == "postgres":
                    cur2 = con.cursor()
                    cur2.execute(f"SELECT COUNT(*) AS c FROM {_q(name, engine)}")
                    got = int((cur2.fetchone() or {}).get("c") or 0)
                else:
                    got = 0
                expected = source_counts.get(name, 0)
                verified[name] = {"expected": expected, "actual": got, "ok": expected == got}
                if expected != got:
                    warnings.append(f"{name} 行数不一致：源 {expected}，目标 {got}")
            try:
                meta = {
                    "schema_version": 1, "source": "workbench-sqlite",
                    "migrated_at": time.time(), "app_version": "0.7.73",
                    "tables": len(schemas), "rows": copied_rows,
                }
                cols = [("schema_version", "BIGINT"), ("source", "VARCHAR(64)"),
                        ("migrated_at", "DOUBLE" if engine == "mysql" else "DOUBLE PRECISION"),
                        ("app_version", "VARCHAR(32)"), ("tables", "BIGINT"), ("rows", "BIGINT")]
                _exec(con, engine, f"CREATE TABLE {_q('_wb_migration_state', engine)} (" +
                      ",".join(f"{_q(n, engine)} {t}" for n, t in cols) + ")")
                vals = [meta["schema_version"], meta["source"], meta["migrated_at"],
                        meta["app_version"], meta["tables"], meta["rows"]]
                _exec(con, engine, f"INSERT INTO {_q('_wb_migration_state', engine)} "
                      f"({','.join(_q(n, engine) for n, _ in cols)}) VALUES ({_ph(engine, 6)})",
                      tuple(vals))
                _commit(con, engine)
            except Exception as exc:
                warnings.append(f"迁移标记写入失败：{exc}")

        result = {
            "ok": all(v["ok"] for v in verified.values()),
            "engine": engine, "tables": len(verified), "rows": copied_rows,
            "target": record.get("database") or record.get("path"),
            "verified": verified, "warnings": warnings,
            "elapsed": round(time.time() - started, 1),
        }
        callback(100, "迁移完成", {"warnings": warnings})
        _append_history(result)
        return result
    finally:
        try:
            snapshot.unlink(missing_ok=True)
        except Exception:
            pass


def _append_history(result: dict[str, Any]) -> None:
    try:
        rows = []
        if MIGRATION_HISTORY_PATH.exists():
            rows = json.loads(MIGRATION_HISTORY_PATH.read_text("utf-8"))
            if not isinstance(rows, list):
                rows = []
        rows.insert(0, {
            "ts": time.time(), "engine": result.get("engine"),
            "target": result.get("target"), "tables": result.get("tables"),
            "rows": result.get("rows"), "ok": result.get("ok"),
            "warnings": len(result.get("warnings") or []),
        })
        MIGRATION_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MIGRATION_HISTORY_PATH.write_text(json.dumps(rows[:20], ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def migration_history() -> list[dict[str, Any]]:
    try:
        data = json.loads(MIGRATION_HISTORY_PATH.read_text("utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ------------------------------------------------------------------ 导出 SQL
def _sql_literal(value: Any, engine: str) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).replace("'", "''")
    if engine == "mysql":
        s = s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    return "'" + s + "'"


def export_sql_script(connection_id: str, target_engine: str = "mysql") -> Path:
    if target_engine not in ("mysql", "postgres"):
        raise DBAdminError("SQL 脚本只支持 MySQL 或 PostgreSQL 方言")
    snapshot, schemas, _ = _source_schemas()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"workbench-{target_engine}-{time.strftime('%Y%m%d-%H%M%S')}.sql"
    path = BACKUP_DIR / stem
    try:
        with path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(f"-- Workbench database export ({target_engine})\n")
            f.write(f"-- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("-- Source: local SQLite; kb_fts (FTS index) is intentionally omitted.\n\n")
            if target_engine == "mysql":
                f.write("SET NAMES utf8mb4;\nSET FOREIGN_KEY_CHECKS=0;\n\n")
            for schema in schemas:
                f.write(_create_table_sql(schema, target_engine) + ";\n\n")
            src = sqlite3.connect(str(snapshot))
            src.row_factory = sqlite3.Row
            try:
                for schema in schemas:
                    table = schema["table"]
                    cols = [c["name"] for c in schema["columns"]]
                    f.write(f"-- data: {table}\n")
                    for row in src.execute(f"SELECT * FROM {_q(table, 'sqlite')}"):
                        vals = ",".join(_sql_literal(row[c], target_engine) for c in cols)
                        f.write(f"INSERT INTO {_q(table, target_engine)} "
                                f"({','.join(_q(c, target_engine) for c in cols)}) VALUES ({vals});\n")
                    f.write("\n")
            finally:
                src.close()
            for schema in schemas:
                for sql in _index_sql(schema, target_engine):
                    f.write(sql + ";\n")
                for sql in _fk_sql(schema, target_engine):
                    f.write(sql + ";\n")
            if target_engine == "mysql":
                f.write("\nSET FOREIGN_KEY_CHECKS=1;\n")
        return path
    finally:
        try:
            snapshot.unlink(missing_ok=True)
        except Exception:
            pass
