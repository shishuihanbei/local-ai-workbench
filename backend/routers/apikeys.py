"""API 管理：访问位置判断、地址生成、用户 API Key 管理。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..config import load_config
from ..db import audit
from ..security import current_user
from ..services import access, apikeys, netinfo
from ..services.tunnel import tunnel

router = APIRouter(prefix="/api", tags=["api-keys"])


class KeyBody(BaseModel):
    name: str = "默认密钥"


def _public_tunnel_api() -> dict[str, Any]:
    st = tunnel.status()
    url = str(st.get("url") or "").rstrip("/")
    ready = bool(st.get("running") and st.get("ready") and url)
    target = st.get("target_mode") or "panel"
    return {
        "running": bool(st.get("running")),
        "ready": ready,
        "url": url if ready else "",
        "api_base": f"{url}/v1" if ready and target == "panel" else "",
        "target": target,
    }


@router.get("/api-keys/context")
async def api_context(request: Request, user: dict = Depends(current_user)):
    net = netinfo.detect(request)
    models = await apikeys.models_for(user)
    public = _public_tunnel_api()
    public_api = public["api_base"] or (net["current_base"] if net["is_external"] else "")
    cfg = load_config()
    default_model = cfg.get("model") or (models[0]["id"] if models else "")
    if user.get("role") != "admin":
        first = await access.first_model(user)
        if first:
            default_model = first
    return {
        "network": net,
        "api": {
            "recommended_base": net["recommended_base"],
            "chat_endpoint": f"{net['recommended_base']}/chat/completions",
            "models_endpoint": f"{net['recommended_base']}/models",
            "auth_header": "Authorization: Bearer <你的 API Key>",
            "openai_compatible": True,
        },
        "urls": [
            {"key": "recommended", "label": "推荐地址", "url": net["recommended_base"],
             "note": net["hint"]},
            {"key": "local", "label": "本机使用", "url": net["local_base"],
             "note": "只有这台电脑能访问"},
            {"key": "lan", "label": "同一内网", "url": net["lan_base"],
             "note": "同一路由器/局域网内的设备可用"},
            {"key": "public", "label": "外网使用", "url": public_api,
             "note": "当前公网地址" if public_api
             else "需要先在内网穿透页开启，目标选“管理控制台”"},
            {"key": "current", "label": "当前访问地址", "url": net["current_base"],
             "note": "你现在打开这个控制台时使用的地址"},
        ],
        "tunnel": public,
        "models": models,
        "default_model": default_model,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    }


@router.get("/api-keys")
async def list_api_keys(all: bool = False, user: dict = Depends(current_user)):
    return {"items": await apikeys.list_keys(user, all_users=all),
            "is_admin": user.get("role") == "admin"}


@router.post("/api-keys")
async def create_api_key(body: KeyBody, user: dict = Depends(current_user)):
    try:
        token, item = await apikeys.create(user, body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await audit(user, "api_key.create", target=item.get("masked", ""), detail=item.get("name", ""))
    return {"key": token, "item": item,
            "warning": "这串 Key 只显示一次，请立即复制保存；关闭后将无法再次查看。"}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: int, user: dict = Depends(current_user)):
    ok = await apikeys.revoke(user, key_id)
    if not ok:
        raise HTTPException(404, "密钥不存在或无权操作")
    await audit(user, "api_key.revoke", target=str(key_id))
    return {"ok": True}
