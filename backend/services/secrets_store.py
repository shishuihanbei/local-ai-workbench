"""供应商 API Key 的静态加密。

- 算法：AES-256-GCM，随机 12 字节 nonce，AAD 固定为 provider.api_key
- 主密钥：由 `config.secret_key()`（data/secret.key 或 WORKBENCH_SECRET）经 HKDF-SHA256 派生
- 存储格式：`enc:v1:<base64url(nonce|ciphertext|tag)>`
- 兼容旧数据：没有前缀的值按明文读取；启动时自动迁移为密文
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import secret_key
from ..db import execute, fetch_all

PREFIX = "enc:v1:"
_AAD = b"provider.api_key"
_cache: bytes | None = None


def _master() -> bytes:
    global _cache
    if _cache is None:
        _cache = HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=b"workbench-provider-keys", info=b"aes-gcm-v1",
        ).derive(secret_key().encode("utf-8"))
    return _cache


def is_encrypted(value: str | None) -> bool:
    return bool(value) and str(value).startswith(PREFIX)


def encrypt(value: str | None) -> str:
    """空值原样返回；已加密的不重复加密。"""
    if not value:
        return ""
    if is_encrypted(value):
        return value
    nonce = os.urandom(12)
    blob = AESGCM(_master()).encrypt(nonce, str(value).encode("utf-8"), _AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + blob).decode().rstrip("=")


def decrypt(value: str | None) -> str:
    """密文解密；旧明文原样返回；密文损坏抛 ValueError。"""
    if not value:
        return ""
    if not is_encrypted(value):
        return str(value)
    raw = base64.urlsafe_b64decode(value[len(PREFIX):] + "=" * (-len(value[len(PREFIX):]) % 4))
    nonce, blob = raw[:12], raw[12:]
    return AESGCM(_master()).decrypt(nonce, blob, _AAD).decode("utf-8")


async def migrate() -> int:
    """把历史明文 Key 批量转为密文，返回迁移条数。"""
    rows = await fetch_all("SELECT id, api_key FROM providers WHERE api_key IS NOT NULL AND api_key != ''")
    moved = 0
    for r in rows:
        if is_encrypted(r["api_key"]):
            continue
        await execute("UPDATE providers SET api_key=? WHERE id=?", (encrypt(r["api_key"]), r["id"]))
        moved += 1
    return moved
