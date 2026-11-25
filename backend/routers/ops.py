"""网络：内网穿透。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import audit
from ..security import admin_user
from ..services.tunnel import download_cloudflared, tunnel

router = APIRouter(prefix="/api", tags=["ops"])


class TunnelBody(BaseModel):
    mode: str = "quick"
    token: str = ""
    target: str | None = None
    domain: str | None = None


# ------------------------------------------------------------------ 穿透
@router.get("/tunnel/status")
async def tunnel_status(user: dict = Depends(admin_user)):
    return tunnel.status()


@router.post("/tunnel/start")
async def tunnel_start(body: TunnelBody, user: dict = Depends(admin_user)):
    if body.mode not in ("quick", "token"):
        raise HTTPException(400, "模式只能是 quick 或 token")
    if body.target and body.target not in ("panel", "api", "frontend"):
        raise HTTPException(400, "穿透目标只能是管理控制台、模型 API 或本地前端")
    from ..config import load_config, save_config
    cfg = load_config()
    if body.target:
        cfg["tunnel_target"] = body.target
    if cfg.get("tunnel_target") not in ("panel", "api", "frontend"):
        cfg["tunnel_target"] = "panel"
    if body.domain is not None:
        domain = body.domain.strip()
        if domain and not domain.startswith(("http://", "https://")):
            domain = "https://" + domain
        cfg["tunnel_domain"] = domain
    if body.token.strip():
        cfg["tunnel_token"] = body.token.strip()
    save_config(cfg)
    ok, msg = tunnel.start(body.mode, body.token)
    await audit(user, "tunnel.start", body.mode, msg, "ok" if ok else "fail")
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "msg": msg, "status": tunnel.status()}


@router.post("/tunnel/stop")
async def tunnel_stop(user: dict = Depends(admin_user)):
    tunnel.stop()
    await audit(user, "tunnel.stop")
    return {"ok": True, "status": tunnel.status()}


@router.post("/tunnel/download")
async def tunnel_download(user: dict = Depends(admin_user)):
    res = await download_cloudflared()
    await audit(user, "tunnel.download", detail=res.get("msg", ""), status="ok" if res.get("ok") else "fail")
    if not res.get("ok"):
        raise HTTPException(400, res.get("msg", "下载失败"))
    return res


@router.get("/tunnel/log")
async def tunnel_log(tail: int = 120, user: dict = Depends(admin_user)):
    from ..config import DATA_DIR
    p = DATA_DIR / "logs" / "tunnel.log"
    if not p.exists():
        return {"lines": []}
    text = p.read_bytes()[-200_000:].decode("utf-8", "replace")
    return {"lines": text.splitlines()[-min(max(tail, 20), 500):]}
