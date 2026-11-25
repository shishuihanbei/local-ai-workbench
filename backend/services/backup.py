"""一键备份 / 恢复：数据库快照 + 密钥 + 配置文件。"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from ..config import BASE_DIR, DATA_DIR, DB_PATH, DEFAULTS, load_config, secret_key

BACKUP_FORMAT = "workbench-backup"
MIGRATION_FORMAT = "workbench-migration"
SHARE_FORMAT = "workbench-share"
FORMAT_VERSION = 1
APP_VERSION = "0.7.73"
BACKUP_DIR = DATA_DIR / "backups"
MIGRATION_DIR = DATA_DIR / "migrations"
SHARE_DIR = DATA_DIR / "shares"
KEEP_BACKUPS = 10
KEEP_MIGRATIONS = 10
KEEP_SHARES = 10
MAX_RESTORE_BYTES = 1024 * 1024 * 1024

PAYLOAD_FILES = ("workbench.db", "secret.key", "config.json", "auth_providers.json")
REQUIRED_FILES = ("workbench.db", "secret.key", "config.json")


class BackupError(RuntimeError):
    pass


def _strip_legacy_config(path: Path) -> None:
    """打包/恢复时去掉已下线功能的配置键，旧备份也不会再带回来。"""
    if not path.exists():
        return
    try:
        cfg = json.loads(path.read_text("utf-8"))
        if not isinstance(cfg, dict):
            return
        cfg = {key: value for key, value in cfg.items() if key in DEFAULTS}
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _db_snapshot(dest: Path) -> None:
    """用 SQLite backup API 生成一致性快照，避免直接复制 WAL 库。"""
    if not DB_PATH.exists():
        raise BackupError("数据库文件不存在")
    src = sqlite3.connect(str(DB_PATH), timeout=30)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()


def _cleanup_dir(folder: Path, keep: int) -> None:
    if not folder.exists():
        return
    files = sorted(folder.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[keep:]:
        try:
            path.unlink()
        except OSError:
            pass


def _cleanup(keep: int = KEEP_BACKUPS) -> None:
    _cleanup_dir(BACKUP_DIR, keep)
    _cleanup_dir(MIGRATION_DIR, KEEP_MIGRATIONS)
    _cleanup_dir(SHARE_DIR, KEEP_SHARES)


def create_backup(prefix: str = "workbench-backup") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = BACKUP_DIR / f"{prefix}-{stamp}.zip"
    tmp = Path(tempfile.mkdtemp(prefix="workbench-backup-", dir=str(BACKUP_DIR)))
    try:
        _db_snapshot(tmp / "workbench.db")
        copied: list[str] = ["workbench.db"]
        for name in ("secret.key", "config.json", "auth_providers.json"):
            src = DATA_DIR / name
            if src.exists():
                shutil.copy2(src, tmp / name)
            elif name == "secret.key":
                (tmp / name).write_text(secret_key(), "utf-8")
            elif name == "config.json":
                (tmp / name).write_text(
                    json.dumps(load_config(), ensure_ascii=False, indent=2), "utf-8")
            else:
                (tmp / name).write_text("{}", "utf-8")
            copied.append(name)
        _strip_legacy_config(tmp / "config.json")

        schema_version = 0
        try:
            con = sqlite3.connect(str(tmp / "workbench.db"))
            row = con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            schema_version = int(row[0] or 0)
            con.close()
        except Exception:
            pass

        manifest = {
            "format": BACKUP_FORMAT,
            "format_version": FORMAT_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "created_ts": time.time(),
            "app_schema": schema_version,
            "files": {name: {"size": (tmp / name).stat().st_size, "sha256": _sha256(tmp / name)}
                      for name in copied},
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in copied:
                z.write(tmp / name, name)
            z.write(tmp / "manifest.json", "manifest.json")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _cleanup()
    return zip_path


APP_ROOT_FILES = (
    "run.py", "requirements.txt", "README.md",
    "start.ps1", "start.bat", "start.sh", "stop.ps1", "stop.bat", "stop.sh",
    "restart.ps1", "restart.bat", "restart.sh",
)


def _runtime_files() -> list[str]:
    files: list[str] = []
    for name in APP_ROOT_FILES:
        if (BASE_DIR / name).exists():
            files.append(name)
    for dirname in ("backend", "frontend"):
        root = BASE_DIR / dirname
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(BASE_DIR)
            if "__pycache__" in rel.parts or path.suffix in (".pyc", ".pyo"):
                continue
            files.append(rel.as_posix())
    return files


def _migration_readme() -> str:
    return """本地 AI 工作台 · 整机迁移包

这个压缩包用于把工作台从旧电脑搬到新电脑或服务器。

包含：
- 工作台程序（backend、frontend、启动脚本）
- data/workbench.db 数据库快照
- data/secret.key 加密主密钥
- data/config.json 运行配置
- data/auth_providers.json 登录方式配置
- data/uploads、data/audio、data/exports（如果有）

不包含：
- .venv 虚拟环境（新机启动时自动创建）
- 模型文件（通常很大，需要另行复制或重新下载）
- llama.cpp 二进制（新机可一键安装）
- 日志和历史备份

Windows 新机：
1. 解压到一个普通目录，例如 D:\\AI\\workbench，不要放在 Program Files 或只读目录。
2. 双击“一键迁移-双击我.bat”。
3. 脚本会尽量把模型目录指向包内 models、llama 目录；没有这两个目录时保留原配置。
4. 首次启动会自动安装 Python 依赖，然后打开 http://127.0.0.1:9100/（本机）；局域网或公网访问请使用实际访问地址。

Linux / macOS：
1. 解压到任意目录。
2. chmod +x start.sh migrate.sh
3. ./migrate.sh

迁移后检查：
- 如果是新机器，模型目录可能不同：进入控制台「部署 / 模型」检查 models_dir、llama_dir。
- 换域名、端口或公网地址后，QQ/微信回调地址、短信/邮件配置可能需要更新。
- data/secret.key 不要丢，否则已加密的供应商 Key 和登录方式密钥无法解密。
- 迁移包含密钥和账号数据，请只放在可信位置，不要发到公开网盘。
"""


def _migration_scripts(tmp: Path) -> None:
    (tmp / "migrate.ps1").write_text(r"""$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgPath = Join-Path $root "data\config.json"
if (Test-Path $cfgPath) {
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $models = Join-Path $root "models"
        $llama = Join-Path $root "llama"
        if (Test-Path $models) { $cfg.models_dir = $models }
        if (Test-Path $llama) { $cfg.llama_dir = $llama }
        $cfg.serve_frontend = $true
        $json = $cfg | ConvertTo-Json -Depth 10
        [System.IO.File]::WriteAllText($cfgPath, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Host "配置自动调整失败，请手动检查 data\config.json" -ForegroundColor Yellow
    }
}
Set-Location $root
& (Join-Path $root "start.ps1")
""", "utf-8")
    (tmp / "一键迁移-双击我.bat").write_text(
        "@echo off\r\ncd /d \"%~dp0\"\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0migrate.ps1\"\r\npause\r\n",
        "utf-8")
    (tmp / "migrate.sh").write_text(r"""#!/usr/bin/env bash
set -e
root="$(cd "$(dirname "$0")" && pwd)"
python3 - "$root" <<'PY'
import json, os, sys
root = sys.argv[1]
cfg_path = os.path.join(root, "data", "config.json")
if os.path.exists(cfg_path):
    try:
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        for key, sub in (("models_dir", "models"), ("llama_dir", "llama")):
            path = os.path.join(root, sub)
            if os.path.isdir(path):
                cfg[key] = path
        cfg["serve_frontend"] = True
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as exc:
        print("配置自动调整失败，请手动检查 data/config.json:", exc)
PY
exec "$root/start.sh"
""", "utf-8")


def create_migration_package() -> Path:
    """生成整机迁移包：程序 + 数据快照，不含模型和虚拟环境。"""
    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = MIGRATION_DIR / f"workbench-migrate-{stamp}.zip"
    tmp = Path(tempfile.mkdtemp(prefix="workbench-migrate-", dir=str(MIGRATION_DIR)))
    try:
        data_tmp = tmp / "data"
        data_tmp.mkdir(parents=True, exist_ok=True)
        _db_snapshot(data_tmp / "workbench.db")
        for name in ("secret.key", "config.json", "auth_providers.json"):
            src = DATA_DIR / name
            if src.exists():
                shutil.copy2(src, data_tmp / name)
            elif name == "secret.key":
                (data_tmp / name).write_text(secret_key(), "utf-8")
            elif name == "config.json":
                (data_tmp / name).write_text(
                    json.dumps(load_config(), ensure_ascii=False, indent=2), "utf-8")
            else:
                (data_tmp / name).write_text("{}", "utf-8")
        _strip_legacy_config(data_tmp / "config.json")
        for sub in ("uploads", "audio", "exports"):
            src = DATA_DIR / sub
            if src.exists():
                shutil.copytree(src, data_tmp / sub, dirs_exist_ok=True)

        for rel in _runtime_files():
            src = BASE_DIR / rel
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        (tmp / "迁移说明.txt").write_text(_migration_readme(), "utf-8")
        _migration_scripts(tmp)

        files: dict[str, dict[str, Any]] = {}
        for path in sorted(tmp.rglob("*")):
            if path.is_file() and path.name != "migration-manifest.json":
                rel = path.relative_to(tmp).as_posix()
                files[rel] = {"size": path.stat().st_size, "sha256": _sha256(path)}
        manifest = {
            "format": MIGRATION_FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": APP_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "created_ts": time.time(),
            "source_platform": platform.platform(),
            "includes_models": False,
            "files": files,
        }
        (tmp / "migration-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for path in sorted(tmp.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(tmp).as_posix())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _cleanup()
    return zip_path


def _share_readme() -> str:
    return """本地 AI 工作台 · 网站分享安装包

这是一个“干净的程序包”，不包含原电脑的任何数据。

不包含：
- workbench.db 数据库（没有账号、对话、调用记录）
- secret.key 加密主密钥
- config.json / auth_providers.json
- data/uploads、data/audio、data/exports
- 模型文件、.venv、llama.cpp 二进制、日志

包含：
- 工作台程序（backend、frontend）
- 启动 / 停止 / 重启脚本
- requirements.txt 依赖清单
- 本说明和“一键开始-双击我.bat”

Windows 使用：
1. 解压到一个普通目录，例如 D:\\AI\\workbench，不要放 Program Files 或只读目录。
2. 双击“一键开始-双击我.bat”。
3. 首次启动会自动创建 data、安装 Python 依赖，并打开 http://127.0.0.1:9100/（本机）；局域网或公网请用实际访问地址。
4. 打开后先初始化管理员，再自己创建用户、模型、供应商、API Key 等数据。

Linux / macOS：
1. 解压到任意目录。
2. chmod +x start.sh
3. ./start.sh

说明：
- 这是新机安装包，安装后是一台全新的工作台，不会带入分享者的账号和数据。
- 模型不随包分发；进入控制台「部署 / 模型」下载或复制模型。
- 需要 Python 3.10+；Windows 安装 Python 时勾选 Add python.exe to PATH。
"""


def _share_scripts(tmp: Path) -> None:
    (tmp / "一键开始-双击我.bat").write_text(
        "@echo off\r\ncd /d \"%~dp0\"\r\npowershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0start.ps1\"\r\npause\r\n",
        "utf-8")


def create_share_package() -> Path:
    """生成干净分享包：只含程序，不含数据库、密钥、配置和模型。"""
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_path = SHARE_DIR / f"workbench-share-{stamp}.zip"
    tmp = Path(tempfile.mkdtemp(prefix="workbench-share-", dir=str(SHARE_DIR)))
    try:
        for rel in _runtime_files():
            src = BASE_DIR / rel
            dst = tmp / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        (tmp / "使用说明.txt").write_text(_share_readme(), "utf-8")
        _share_scripts(tmp)

        files: dict[str, dict[str, Any]] = {}
        for path in sorted(tmp.rglob("*")):
            if path.is_file() and path.name != "share-manifest.json":
                rel = path.relative_to(tmp).as_posix()
                files[rel] = {"size": path.stat().st_size, "sha256": _sha256(path)}
        manifest = {
            "format": SHARE_FORMAT,
            "format_version": FORMAT_VERSION,
            "app_version": APP_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "created_ts": time.time(),
            "source_platform": platform.platform(),
            "includes_data": False,
            "includes_models": False,
            "files": files,
        }
        (tmp / "share-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for path in sorted(tmp.rglob("*")):
                if path.is_file():
                    z.write(path, path.relative_to(tmp).as_posix())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _cleanup()
    return zip_path


def list_backups() -> list[dict[str, Any]]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MIGRATION_DIR.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for folder in (BACKUP_DIR, MIGRATION_DIR):
        files.extend(folder.glob("*.zip"))
    items: list[dict[str, Any]] = []
    for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
        item: dict[str, Any] = {
            "name": path.name,
            "size": path.stat().st_size,
            "created_at": path.stat().st_mtime,
            "kind": "backup",
            "directory": str(path.parent),
            "path": str(path),
        }
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
                raw = None
                for candidate in ("manifest.json", "migration-manifest.json"):
                    if candidate in names:
                        raw = json.loads(z.read(candidate).decode("utf-8"))
                        break
                if raw:
                    item["kind"] = "migration" if raw.get("format") == MIGRATION_FORMAT else "backup"
                    item["format"] = raw.get("format")
                    item["app_version"] = raw.get("app_version") or APP_VERSION
                    item["app_schema"] = raw.get("app_schema")
                    item["created_at"] = raw.get("created_ts") or item["created_at"]
                    item["file_count"] = len(raw.get("files") or {})
        except Exception:
            pass
        items.append(item)
    return items


def list_shares() -> list[dict[str, Any]]:
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for path in sorted(SHARE_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        item: dict[str, Any] = {
            "name": path.name,
            "size": path.stat().st_size,
            "created_at": path.stat().st_mtime,
            "kind": "share",
            "directory": str(path.parent),
            "path": str(path),
        }
        try:
            with zipfile.ZipFile(path) as z:
                raw = json.loads(z.read("share-manifest.json").decode("utf-8"))
            item["app_version"] = raw.get("app_version") or APP_VERSION
            item["created_at"] = raw.get("created_ts") or item["created_at"]
            item["file_count"] = len(raw.get("files") or {})
            item["includes_data"] = bool(raw.get("includes_data"))
        except Exception:
            pass
        items.append(item)
    return items


def share_path(name: str) -> Path:
    if not name.endswith(".zip") or Path(name).name != name:
        raise BackupError("分享包文件名不合法")
    path = SHARE_DIR / name
    if not path.exists():
        raise BackupError("分享包不存在")
    return path


def delete_share(name: str) -> None:
    share_path(name).unlink()


def _open_folder(folder: Path) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except FileNotFoundError as exc:
        raise BackupError("当前系统没有可用的文件管理器") from exc
    except OSError as exc:
        raise BackupError(f"无法打开文件夹：{exc}") from exc
    return str(folder)


def open_migration_folder() -> str:
    """在运行工作台的本机打开迁移包默认目录。"""
    return _open_folder(MIGRATION_DIR)


def open_share_folder() -> str:
    """在运行工作台的本机打开分享包默认目录。"""
    return _open_folder(SHARE_DIR)


def backup_path(name: str) -> Path:
    if not name.endswith(".zip") or Path(name).name != name:
        raise BackupError("备份文件名不合法")
    for folder in (BACKUP_DIR, MIGRATION_DIR):
        path = folder / name
        if path.exists():
            return path
    raise BackupError("备份文件不存在")


def delete_backup(name: str) -> None:
    backup_path(name).unlink()


def _inspect(zip_path: Path) -> dict[str, Any]:
    if not zip_path.exists() or zip_path.stat().st_size > MAX_RESTORE_BYTES:
        raise BackupError("备份文件不存在或超过 1GB")
    try:
        with zipfile.ZipFile(zip_path) as z:
            infos = z.infolist()
            names = [i.filename for i in infos if not i.is_dir()]
            if len(names) != len(set(names)):
                raise BackupError("备份里有重名文件")
            total = sum(i.file_size for i in infos)
            if total > MAX_RESTORE_BYTES * 2:
                raise BackupError("备份解压后体积过大")
            for name in names:
                p = Path(name)
                if p.is_absolute() or ".." in p.parts or name.startswith(("/", "\\")):
                    raise BackupError("备份包含不安全路径")
            if not set(REQUIRED_FILES).issubset(names) or "manifest.json" not in names:
                raise BackupError("不是完整的工作台备份")
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f"备份文件损坏：{exc}") from exc

    if manifest.get("format") != BACKUP_FORMAT:
        raise BackupError("备份格式不认识")
    if int(manifest.get("format_version") or 0) > FORMAT_VERSION:
        raise BackupError("备份由更新版本创建，请先升级工作台")
    files = manifest.get("files") or {}
    if not isinstance(files, dict) or not set(REQUIRED_FILES).issubset(files):
        raise BackupError("备份清单不完整")
    return manifest


def _validate_db(path: Path) -> None:
    try:
        con = sqlite3.connect(str(path))
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
    except Exception as exc:
        raise BackupError(f"数据库无法打开：{exc}") from exc
    if ok != "ok":
        raise BackupError(f"数据库完整性检查失败：{ok}")
    if not {"users", "sessions", "models", "settings"}.issubset(tables):
        raise BackupError("备份里的数据库不是工作台数据库")


def _replace_db(src: Path) -> None:
    """把备份库写回当前库，保留当前数据库文件句柄。"""
    source = sqlite3.connect(str(src))
    target = sqlite3.connect(str(DB_PATH), timeout=30)
    try:
        source.backup(target)
        target.commit()
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        target.close()
        source.close()


def restore_backup(zip_path: Path) -> dict[str, Any]:
    manifest = _inspect(zip_path)
    tmp = Path(tempfile.mkdtemp(prefix="workbench-restore-", dir=str(DATA_DIR)))
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        for name, meta in (manifest.get("files") or {}).items():
            path = tmp / name
            if not path.exists() or _sha256(path) != meta.get("sha256"):
                raise BackupError(f"文件校验失败：{name}")

        _validate_db(tmp / "workbench.db")
        safety = create_backup("pre-restore")

        _replace_db(tmp / "workbench.db")
        for name in ("secret.key", "config.json", "auth_providers.json"):
            src = tmp / name
            if src.exists():
                shutil.copy2(src, DATA_DIR / name)
        _strip_legacy_config(DATA_DIR / "config.json")
        return {
            "ok": True,
            "restored_at": time.time(),
            "safety_backup": safety.name,
            "schema_version": manifest.get("app_schema"),
            "restart_required": True,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
