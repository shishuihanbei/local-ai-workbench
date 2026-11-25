"""用户端品牌外观：Logo、登录文案、页脚与备案信息。

配置仍保存在 data/config.json；Logo 原图落在 data/branding/，
通过公开的 /api/branding/logo 提供给登录页，便于在登录前展示。
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, load_config, save_config

BRAND_DIR = DATA_DIR / "branding"
BRAND_DIR.mkdir(parents=True, exist_ok=True)

MAX_LOGO_BYTES = 3 * 1024 * 1024
DEFAULT_COLOR = "#4f6ef7"
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
         ".gif": "image/gif"}


def normalize_color(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
        return text.lower()
    if re.fullmatch(r"#[0-9a-fA-F]{3}", text):
        return "#" + "".join(ch * 2 for ch in text[1:]).lower()
    return DEFAULT_COLOR


def safe_link(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if text.startswith(("http://", "https://")):
        return text[:500]
    return fallback


def _logo_name(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or load_config()
    return Path(str(cfg.get("brand_logo") or "")).name


def logo_file() -> tuple[Path, str] | None:
    """返回已上传 Logo 的文件和 MIME；未上传或文件丢失时返回 None。"""
    name = _logo_name()
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        return None
    suffix = Path(name).suffix.lower()
    if suffix not in _MIME:
        return None
    path = BRAND_DIR / name
    if not path.is_file():
        return None
    return path, _MIME[suffix]


def logo_url(cfg: dict[str, Any] | None = None) -> str:
    name = _logo_name(cfg)
    if not name:
        return ""
    path = BRAND_DIR / name
    if not path.is_file():
        return ""
    try:
        version = int(path.stat().st_mtime * 1000)
    except OSError:
        version = 0
    return f"/api/branding/logo?v={version}"


def _detect_image(raw: bytes) -> tuple[str, str] | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def save_logo(raw: bytes) -> dict[str, str]:
    """校验并保存 Logo 原图，返回立即生效的访问地址。"""
    if not raw:
        raise ValueError("请选择一张 Logo 图片")
    if len(raw) > MAX_LOGO_BYTES:
        raise ValueError("Logo 不能超过 3 MB")
    detected = _detect_image(raw)
    if not detected:
        raise ValueError("Logo 仅支持 PNG、JPG、WebP 或 GIF")
    suffix, _ = detected
    cfg = load_config()
    old = _logo_name(cfg)
    if old:
        try:
            (BRAND_DIR / old).unlink(missing_ok=True)
        except OSError:
            pass
    filename = f"logo-{uuid.uuid4().hex[:12]}{suffix}"
    (BRAND_DIR / filename).write_bytes(raw)
    cfg["brand_logo"] = filename
    save_config(cfg)
    return {"filename": filename, "url": logo_url(cfg),
            "mime": _MIME[suffix], "size": len(raw)}


def remove_logo() -> dict[str, bool]:
    cfg = load_config()
    old = _logo_name(cfg)
    if old:
        try:
            (BRAND_DIR / old).unlink(missing_ok=True)
        except OSError:
            pass
    cfg["brand_logo"] = ""
    save_config(cfg)
    return {"ok": True}


def public() -> dict[str, Any]:
    """登录页可见的品牌信息，不包含联系邮箱等后台资料。"""
    cfg = load_config()
    org = str(cfg.get("org_name") or "本地 AI 工作台").strip() or "本地 AI 工作台"
    copyright = str(cfg.get("brand_copyright") or "").strip() \
        or f"© {datetime.now().year} {org}"
    return {
        "org_name": org,
        "org_short_name": str(cfg.get("org_short_name") or "").strip() or org,
        "brand_tagline": str(cfg.get("brand_tagline") or "Local AI Workbench").strip(),
        "brand_login_title": str(cfg.get("brand_login_title") or "").strip(),
        "brand_login_lead": str(cfg.get("brand_login_lead") or "").strip(),
        "brand_login_foot": str(cfg.get("brand_login_foot") or "").strip(),
        "brand_auth_subtitle": str(cfg.get("brand_auth_subtitle") or "").strip(),
        "brand_primary": normalize_color(cfg.get("brand_primary")),
        "brand_icp": str(cfg.get("brand_icp") or "").strip(),
        "brand_icp_url": safe_link(cfg.get("brand_icp_url"), "https://beian.miit.gov.cn/"),
        "brand_police": str(cfg.get("brand_police") or "").strip(),
        "brand_police_url": safe_link(cfg.get("brand_police_url"),
                                       "https://beian.mps.gov.cn/#/query/webSearch"),
        "brand_copyright": copyright,
        "brand_logo_url": logo_url(cfg),
        "watermark_enabled": bool(cfg.get("watermark_enabled")),
        "watermark_text": str(cfg.get("watermark_text") or "{user} · {org}"),
    }

