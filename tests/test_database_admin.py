"""数据库中心 API 测试：只使用临时 SQLite，不碰线上数据。"""
from __future__ import annotations

import base64
import json
import time


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _key(**pk) -> str:
    return base64.urlsafe_b64encode(json.dumps(pk, separators=(",", ":")).encode()).decode().rstrip("=")


def test_database_overview_and_schema(client, admin_token):
    h = auth(admin_token)
    r = client.get("/api/admin/database/overview", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connection"]["engine"] == "sqlite"
    assert body["table_count"] >= 1
    assert body["version"].startswith("SQLite")

    r = client.get("/api/admin/database/tables", headers=h)
    assert r.status_code == 200
    tables = {t["name"] for t in r.json()["tables"]}
    assert {"users", "settings", "schema_migrations"} <= tables

    r = client.get("/api/admin/database/table/settings/schema", headers=h)
    assert r.status_code == 200
    cols = {c["name"]: c for c in r.json()["columns"]}
    assert cols["key"]["pk"] == 1

    r = client.get("/api/admin/database/health", headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_database_row_crud_and_search(client, admin_token):
    h = auth(admin_token)
    r = client.post("/api/admin/database/table/settings/rows", headers=h,
                    json={"values": {"key": "pytest_key", "value": "one"}})
    assert r.status_code == 200, r.text
    key = _key(key="pytest_key")
    r = client.get(f"/api/admin/database/table/settings/row?key={key}", headers=h)
    assert r.status_code == 200
    assert r.json()["row"]["value"] == "one"

    r = client.get("/api/admin/database/table/settings/rows?search=pytest_key", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.patch(f"/api/admin/database/table/settings/row?key={key}", headers=h,
                     json={"key": key, "values": {"value": "two"}})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/admin/database/table/settings/row?key={key}", headers=h).json()["row"]["value"] == "two"

    r = client.request("DELETE", f"/api/admin/database/table/settings/row?key={key}", headers=h,
                       json={"key": key})
    assert r.status_code == 200, r.text


def test_database_sql_read_only_and_write_switch(client, admin_token):
    h = auth(admin_token)
    r = client.post("/api/admin/database/query", headers=h,
                    json={"connection": "local", "sql": "SELECT name FROM sqlite_master LIMIT 3"})
    assert r.status_code == 200, r.text
    assert r.json()["write"] is False
    assert len(r.json()["columns"]) == 1

    r = client.post("/api/admin/database/query", headers=h,
                    json={"connection": "local", "sql": "DELETE FROM settings"})
    assert r.status_code == 400
    assert "只读" in r.text or "写" in r.text


def test_database_connection_and_sqlite_migration(client, admin_token, tmp_path):
    h = auth(admin_token)
    target = tmp_path / "migrated.db"
    r = client.post("/api/admin/database/connections", headers=h, json={
        "name": "pytest sqlite", "engine": "sqlite", "path": str(target),
    })
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    r = client.get("/api/admin/database/connections", headers=h)
    conn = [c for c in r.json()["connections"] if c["id"] == cid][0]
    assert conn["password_set"] is False

    r = client.post(f"/api/admin/database/connections/{cid}/test", headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["version"] == "尚未创建"

    r = client.post("/api/admin/database/migrate/preflight", headers=h,
                    json={"connection_id": cid, "create_database": False, "overwrite": False})
    assert r.status_code == 200, r.text
    assert r.json()["ready"] is True
    assert not target.exists()

    r = client.post("/api/admin/database/migrate", headers=h,
                    json={"connection_id": cid, "create_database": False, "overwrite": False})
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    job = None
    for _ in range(40):
        time.sleep(0.1)
        r = client.get(f"/api/admin/database/migrate/{job_id}", headers=h)
        assert r.status_code == 200
        job = r.json()
        if job["status"] != "running":
            break
    assert job and job["status"] == "ok", job
    assert job["result"]["verified"]["settings"]["ok"] is True
    assert target.exists()

    r = client.get(f"/api/admin/database/table/settings/schema?connection={cid}", headers=h)
    assert r.status_code == 200
    assert r.json()["table"] == "settings"

    r = client.delete(f"/api/admin/database/connections/{cid}", headers=h)
    assert r.status_code == 200


def test_database_parse_url_and_exports(client, admin_token):
    h = auth(admin_token)
    r = client.post("/api/admin/database/connections/parse", headers=h,
                    json={"url": "mysql://user:pa%20ss@db.example.com:3306/workbench?ssl=true"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["engine"] == "mysql"
    assert p["port"] == 3306
    assert p["password"] == "pa ss"
    assert p["ssl"] is True

    r = client.post("/api/admin/database/backup", headers=h)
    assert r.status_code == 200
    assert len(r.content) > 1000

    r = client.post("/api/admin/database/export-sql?target_engine=mysql", headers=h)
    assert r.status_code == 200
    assert "CREATE TABLE" in r.text

    r = client.get("/api/admin/database/table/models/export.csv", headers=h)
    assert r.status_code == 200
    assert r.text.startswith("\ufeff")


def test_database_table_create_rename_truncate_drop(client, admin_token):
    h = auth(admin_token)
    cols = [
        {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True, "auto": True},
        {"name": "label", "type": "TEXT", "nullable": True},
    ]
    r = client.post("/api/admin/database/table", headers=h,
                    json={"connection": "local", "table": "pytest_notes", "columns": cols})
    assert r.status_code == 200, r.text
    assert r.json()["columns"] == 2

    r = client.get("/api/admin/database/table/pytest_notes/schema", headers=h)
    assert r.status_code == 200
    s = r.json()
    assert s["primary_key"] == ["id"]
    assert s["columns"][0]["nullable"] is False
    assert 'INTEGER PRIMARY KEY AUTOINCREMENT' in s["create_sql"]

    r = client.post("/api/admin/database/table/pytest_notes/rows", headers=h,
                    json={"values": {"label": "hello"}})
    assert r.status_code == 200, r.text

    r = client.post("/api/admin/database/table/pytest_notes/rename", headers=h,
                    json={"new_name": "pytest_notes_v2"})
    assert r.status_code == 200, r.text
    assert r.json()["to"] == "pytest_notes_v2"

    r = client.post("/api/admin/database/table/pytest_notes_v2/truncate", headers=h,
                    json={"confirm": "pytest_notes_v2"})
    assert r.status_code == 200, r.text
    assert r.json()["affected"] >= 1

    r = client.request("DELETE", "/api/admin/database/table/pytest_notes_v2", headers=h,
                       json={"confirm": "pytest_notes_v2"})
    assert r.status_code == 200, r.text

    r = client.get("/api/admin/database/tables", headers=h)
    assert "pytest_notes_v2" not in {t["name"] for t in r.json()["tables"]}

    r = client.request("DELETE", "/api/admin/database/table/users", headers=h,
                       json={"confirm": "users"})
    assert r.status_code == 400
    assert "依赖" in r.json()["detail"]


def test_database_health_reports_and_repairs_orphan_rows(client, admin_token):
    import sqlite3
    from pathlib import Path

    h = auth(admin_token)
    from backend.config import DB_PATH
    db_path = Path(DB_PATH)
    con = sqlite3.connect(str(db_path))
    try:
        con.execute(
            "INSERT INTO auth_identities (user_id, provider, provider_uid, display_name, meta, created_at) "
            "VALUES (999999, 'username', 'pytest_orphan', 'pytest orphan', '{}', ?)",
            (time.time(),))
        con.commit()
    finally:
        con.close()

    r = client.get("/api/admin/database/health", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    fk = next(c for c in body["checks"] if c["name"] == "外键检查")
    assert fk["ok"] is False
    assert fk["details"] and fk["details"][0]["table"] == "auth_identities"
    assert fk["details"][0]["parent"] == "users"
    assert "auth_identities" in fk["hint"]

    r = client.post("/api/admin/database/repair-foreign-keys", headers=h)
    assert r.status_code == 200, r.text
    fixed = r.json()
    assert fixed["total"] >= 1 and fixed["remaining"] == 0
    assert fixed["backup"].endswith(".db")
    assert any(item["table"] == "auth_identities" for item in fixed["deleted"])

    r = client.get("/api/admin/database/health", headers=h)
    assert r.json()["ok"] is True
