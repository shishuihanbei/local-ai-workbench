"""前台功能开关与图标库 API。"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..db import audit
from ..security import admin_user, current_user
from ..services import front_features

router = APIRouter(prefix="/api/front", tags=["front"])
admin_router = APIRouter(prefix="/api/admin", tags=["front-admin"])

_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|webp|svg\+xml);base64,", re.I)
_MAX_ICON_BYTES = 160 * 1024


class FeatureItem(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    enabled: bool | None = None
    icon_key: str = Field(default="", max_length=40)
    icon_tone: str = Field(default="", max_length=20)
    icon_id: int = Field(default=-1, ge=-1, le=9999999)


class SaveBody(BaseModel):
    items: list[FeatureItem] = Field(min_length=1, max_length=40)


class IconBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    data: str = Field(min_length=20, max_length=400000)


@router.get("/features")
async def get_front_features(user: dict[str, Any] = Depends(current_user)):
    return await front_features.public_features()


@admin_router.get("/front-features")
async def get_front_catalog(user: dict[str, Any] = Depends(admin_user)):
    data = await front_features.catalog()
    data["can_edit"] = True
    return data


@admin_router.put("/front-features")
async def put_front_catalog(body: SaveBody, user: dict[str, Any] = Depends(admin_user)):
    items = []
    for item in body.items:
        row = item.model_dump()
        if row["icon_id"] < 0:
            row.pop("icon_id")
        items.append(row)
    before = {x["key"]: x for x in (await front_features.catalog())["items"]}
    try:
        data = await front_features.save_features(items, username=user.get("username") or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    changed = []
    for x in data["items"]:
        old = before.get(x["key"], {})
        if (bool(old.get("enabled")) != bool(x["enabled"]) or
                (old.get("icon_key") or "") != (x.get("icon_key") or "") or
                (old.get("icon_tone") or "") != (x.get("icon_tone") or "") or
                int(old.get("icon_id") or 0) != int(x.get("icon_id") or 0)):
            changed.append(x["key"])
    detail = f"实际变更 {len(changed)} 项：{', '.join(changed)}" if changed else "无变化"
    await audit(user, "front_features.save", "前台功能", detail)
    return data


@admin_router.get("/front-icons")
async def get_front_icons(user: dict[str, Any] = Depends(admin_user)):
    data = await front_features.catalog()
    return {"icons": data["icons"], "presets": data["presets"]}


@admin_router.post("/front-icons")
async def post_front_icon(body: IconBody, user: dict[str, Any] = Depends(admin_user)):
    match = _DATA_URL_RE.match(body.data)
    if not match:
        raise HTTPException(status_code=422, detail="图标必须是 PNG、JPEG、WebP 或 SVG 的 data URL")
    try:
        raw = base64.b64decode(body.data.split(",", 1)[1], validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="图标数据不是有效的 base64")
    if len(raw) > _MAX_ICON_BYTES:
        raise HTTPException(status_code=422, detail="图标超过 160KB，请压缩后再上传")
    mime = "image/svg+xml" if "svg" in match.group(1).lower() else f"image/{match.group(1).lower()}"
    icon = await front_features.add_icon(body.name.strip(), mime, body.data,
                                         username=user.get("username") or "")
    await audit(user, "front_icons.add", f"icon:{icon['id']}", body.name.strip())
    return icon


@admin_router.delete("/front-icons/{icon_id}")
async def delete_front_icon(icon_id: int, user: dict[str, Any] = Depends(admin_user)):
    ok = await front_features.delete_icon(icon_id)
    if not ok:
        raise HTTPException(status_code=404, detail="图标不存在")
    await audit(user, "front_icons.delete", f"icon:{icon_id}")
    return {"ok": True, "icons": (await front_features.catalog())["icons"]}
