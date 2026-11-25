"""管理台数据库中心 API：浏览、编辑、SQL、外部连接与一键外迁。"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..db import audit
from ..security import admin_user
from ..services import database_admin as dba

router = APIRouter(prefix="/api/admin/database", tags=["database-admin"])

_JOBS: dict[str, dict[str, Any]] = {}
_ACTIVE_JOB: str | None = None


class ConnectionBody(BaseModel):
    name: str = Field(default="", max_length=60)
    engine: str = Field(default="mysql", max_length=20)
    host: str = Field(default="127.0.0.1", max_length=255)
    port: int = 0
    database: str = Field(default="", max_length=255)
    path: str = Field(default="", max_length=1000)
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=500)
    ssl: bool = False
    note: str = Field(default="", max_length=500)


class UrlBody(BaseModel):
    url: str = ""


class RowBody(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    key: str = ""


class QueryBody(BaseModel):
    connection: str = "local"
    sql: str = ""
    allow_write: bool = False
    limit: int = 100


class MigrateBody(BaseModel):
    connection_id: str
    create_database: bool = True
    overwrite: bool = False


class ColumnBody(BaseModel):
    name: str = Field(default="", max_length=64)
    type: str = Field(default="TEXT", max_length=30)
    nullable: bool = True
    primary_key: bool = False
    auto: bool = False


class CreateTableBody(BaseModel):
    table: str = Field(default="", max_length=64)
    columns: list[ColumnBody] = Field(default_factory=list)
    connection: str = "local"


class RenameTableBody(BaseModel):
    new_name: str = Field(default="", max_length=64)


class ConfirmTableBody(BaseModel):
    confirm: str = ""


def _raise(exc: Exception) -> None:
    if isinstance(exc, dba.DBAdminError):
        raise HTTPException(400, str(exc))
    raise exc


def _public_table(t: dict[str, Any]) -> dict[str, Any]:
    return t


@router.get("/overview")
async def overview(connection: str = "local", user: dict = Depends(admin_user)):
    try:
        return await asyncio.to_thread(dba.overview, connection)
    except Exception as exc:
        _raise(exc)


@router.get("/tables")
async def tables(connection: str = "local", user: dict = Depends(admin_user)):
    try:
        return {"connection": connection, "tables": await asyncio.to_thread(dba.list_tables, connection)}
    except Exception as exc:
        _raise(exc)


@router.get("/table/{table}/schema")
async def table_schema(table: str, connection: str = "local", user: dict = Depends(admin_user)):
    try:
        return await asyncio.to_thread(dba.table_schema, connection, table)
    except Exception as exc:
        _raise(exc)


@router.get("/table/{table}/rows")
async def table_rows(table: str, connection: str = "local", limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0), search: str = "", sort: str = "",
                     order: str = "desc", user: dict = Depends(admin_user)):
    try:
        return await asyncio.to_thread(
            dba.table_rows, connection, table, limit, offset, search[:120], sort, order)
    except Exception as exc:
        _raise(exc)


@router.get("/table/{table}/row")
async def get_row(table: str, key: str, connection: str = "local", user: dict = Depends(admin_user)):
    try:
        return await asyncio.to_thread(dba.get_row, connection, table, key)
    except Exception as exc:
        _raise(exc)


@router.post("/table/{table}/rows")
async def create_row(table: str, body: RowBody, connection: str = "local",
                     user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.create_row, connection, table, body.values)
        await audit(user, "database.row.create", target=f"{connection}:{table}",
                    detail=f"fields={len(body.values)}")
        return result
    except Exception as exc:
        _raise(exc)


@router.patch("/table/{table}/row")
async def update_row(table: str, body: RowBody, connection: str = "local",
                     user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.update_row, connection, table, body.key, body.values)
        await audit(user, "database.row.update", target=f"{connection}:{table}",
                    detail=f"fields={','.join(body.values.keys())[:300]}")
        return result
    except Exception as exc:
        _raise(exc)


@router.delete("/table/{table}/row")
async def delete_row(table: str, body: RowBody, connection: str = "local",
                     user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.delete_row, connection, table, body.key)
        await audit(user, "database.row.delete", target=f"{connection}:{table}", detail="delete by primary key")
        return result
    except Exception as exc:
        _raise(exc)


@router.post("/table")
async def create_table(body: CreateTableBody, user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(
            dba.create_table, body.connection, body.table,
            [c.model_dump() for c in body.columns])
        await audit(user, "database.table.create", target=f"{body.connection}:{result['table']}",
                    detail=f"columns={result.get('columns')}")
        return result
    except Exception as exc:
        _raise(exc)


@router.post("/table/{table}/rename")
async def rename_table(table: str, body: RenameTableBody, connection: str = "local",
                       user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.rename_table, connection, table, body.new_name)
        await audit(user, "database.table.rename", target=f"{connection}:{table}",
                    detail=f"to={result.get('to')}")
        return result
    except Exception as exc:
        _raise(exc)


@router.post("/table/{table}/truncate")
async def truncate_table(table: str, body: ConfirmTableBody, connection: str = "local",
                         user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.truncate_table, connection, table, body.confirm)
        await audit(user, "database.table.truncate", target=f"{connection}:{table}",
                    detail=f"affected={result.get('affected')}")
        return result
    except Exception as exc:
        _raise(exc)


@router.delete("/table/{table}")
async def drop_table(table: str, body: ConfirmTableBody, connection: str = "local",
                     user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.drop_table, connection, table, body.confirm)
        await audit(user, "database.table.drop", target=f"{connection}:{table}")
        return result
    except Exception as exc:
        _raise(exc)


@router.post("/query")
async def run_query(body: QueryBody, user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(
            dba.run_query, body.connection, body.sql, body.allow_write, body.limit)
        if body.allow_write:
            await audit(user, "database.query.write", target=body.connection,
                        detail=f"sql_chars={len(body.sql)} affected={result.get('affected')}")
        return result
    except Exception as exc:
        _raise(exc)


@router.get("/health")
async def health(connection: str = "local", user: dict = Depends(admin_user)):
    try:
        return await asyncio.to_thread(dba.health, connection)
    except Exception as exc:
        _raise(exc)


@router.post("/vacuum")
async def vacuum(connection: str = "local", user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.vacuum, connection)
        await audit(user, "database.vacuum", target=connection, detail=f"saved={result.get('saved')}")
        return result
    except Exception as exc:
        _raise(exc)


@router.post("/backup")
async def backup(connection: str = "local", user: dict = Depends(admin_user)):
    try:
        path = await asyncio.to_thread(dba.create_database_backup, connection)
    except Exception as exc:
        _raise(exc)
    await audit(user, "database.backup", target=connection, detail=path.name)
    return FileResponse(str(path), filename=path.name, media_type="application/octet-stream")


@router.post("/export-sql")
async def export_sql(connection: str = "local", target_engine: str = "mysql",
                     user: dict = Depends(admin_user)):
    if connection != "local":
        raise HTTPException(400, "SQL 脚本用于把当前工作台数据导出，暂不从外部连接反向导出")
    try:
        path = await asyncio.to_thread(dba.export_sql_script, connection, target_engine)
    except Exception as exc:
        _raise(exc)
    await audit(user, "database.export.sql", target=target_engine, detail=path.name)
    return FileResponse(str(path), filename=path.name, media_type="text/plain; charset=utf-8")


@router.get("/table/{table}/export.csv")
async def export_csv(table: str, connection: str = "local", user: dict = Depends(admin_user)):
    try:
        name, data = await asyncio.to_thread(dba.export_table_csv, connection, table)
    except Exception as exc:
        _raise(exc)
    await audit(user, "database.export.csv", target=f"{connection}:{table}", detail=name)
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ 外部连接
@router.get("/connections")
async def connections(user: dict = Depends(admin_user)):
    return {"connections": dba.list_connections(), "engines": dba.engine_info()}


@router.post("/connections")
async def create_connection(body: ConnectionBody, user: dict = Depends(admin_user)):
    try:
        row = dba.save_connection(body.model_dump())
        await audit(user, "database.connection.create", target=row["name"], detail=row["engine"])
        return row
    except Exception as exc:
        _raise(exc)


@router.put("/connections/{connection_id}")
async def update_connection(connection_id: str, body: ConnectionBody,
                            user: dict = Depends(admin_user)):
    try:
        row = dba.save_connection(body.model_dump(), connection_id)
        await audit(user, "database.connection.update", target=row["name"], detail=row["engine"])
        return row
    except Exception as exc:
        _raise(exc)


@router.delete("/connections/{connection_id}")
async def remove_connection(connection_id: str, user: dict = Depends(admin_user)):
    try:
        dba.delete_connection(connection_id)
        await audit(user, "database.connection.delete", target=connection_id)
        return {"ok": True}
    except Exception as exc:
        _raise(exc)


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, user: dict = Depends(admin_user)):
    try:
        result = await asyncio.to_thread(dba.test_connection, connection_id)
        await audit(user, "database.connection.test", target=connection_id,
                    detail=str(result.get("version") or "")[:200])
        return result
    except Exception as exc:
        _raise(exc)


@router.post("/connections/parse")
async def parse_connection(body: UrlBody, user: dict = Depends(admin_user)):
    try:
        return dba.parse_connection_url(body.url)
    except Exception as exc:
        _raise(exc)


# ------------------------------------------------------------------ 迁移任务
def _job_update(job: dict[str, Any], pct: int, message: str,
                detail: dict[str, Any] | None = None) -> None:
    job["progress"] = max(0, min(100, int(pct)))
    job["message"] = message
    job["updated_at"] = time.time()
    if detail:
        job["detail"] = detail
    logs = job.setdefault("logs", [])
    if not logs or logs[-1].get("message") != message:
        logs.append({"ts": time.time(), "pct": job["progress"], "message": message})
        del logs[:-16]


async def _run_migration_job(job_id: str, body: MigrateBody) -> None:
    global _ACTIVE_JOB
    job = _JOBS[job_id]
    try:
        result = await asyncio.to_thread(
            dba.migrate_to, body.connection_id, body.create_database, body.overwrite,
            lambda pct, msg, detail=None: _job_update(job, pct, msg, detail))
        job["result"] = result
        job["status"] = "ok" if result.get("ok") else "error"
        job["progress"] = 100
        job["message"] = "迁移完成" if result.get("ok") else "迁移完成，但行数校验未通过"
        job["finished_at"] = time.time()
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)
        job["message"] = "迁移失败：" + str(exc)
        job["finished_at"] = time.time()
    finally:
        _ACTIVE_JOB = None


@router.post("/migrate/preflight")
async def migration_preflight(body: MigrateBody, user: dict = Depends(admin_user)):
    try:
        return await asyncio.to_thread(
            dba.preflight_migration, body.connection_id, body.create_database, body.overwrite)
    except Exception as exc:
        _raise(exc)


@router.post("/migrate")
async def start_migration(body: MigrateBody, user: dict = Depends(admin_user)):
    global _ACTIVE_JOB
    if _ACTIVE_JOB and _ACTIVE_JOB in _JOBS and _JOBS[_ACTIVE_JOB].get("status") == "running":
        raise HTTPException(409, "已有迁移任务在运行，请等它完成或失败后再试")
    try:
        pre = await asyncio.to_thread(
            dba.preflight_migration, body.connection_id, body.create_database, body.overwrite)
        if not pre.get("ok"):
            raise HTTPException(400, pre.get("error") or "迁移检查未通过")
        if not pre.get("ready"):
            raise HTTPException(400, pre.get("message") or "目标库已有同名表，请先勾选覆盖")
    except HTTPException:
        raise
    except Exception as exc:
        _raise(exc)
    job_id = "mig_" + uuid.uuid4().hex[:10]
    job = {
        "id": job_id, "status": "running", "progress": 0,
        "message": "准备迁移…", "detail": {}, "logs": [], "error": "",
        "connection_id": body.connection_id, "created_at": time.time(),
        "updated_at": time.time(), "finished_at": None, "result": None,
    }
    _JOBS[job_id] = job
    _ACTIVE_JOB = job_id
    await audit(user, "database.migrate.start", target=body.connection_id,
                detail=f"create_db={body.create_database} overwrite={body.overwrite}")
    asyncio.create_task(_run_migration_job(job_id, body))
    return job


@router.get("/migrate/{job_id}")
async def migration_status(job_id: str, user: dict = Depends(admin_user)):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "迁移任务不存在或服务已重启")
    return job


@router.get("/migration-history")
async def migration_history(user: dict = Depends(admin_user)):
    return {"history": dba.migration_history()}
