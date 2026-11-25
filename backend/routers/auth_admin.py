"""登录方式配置管理（管理员）。"""
from __future__ import annotations

import secrets as pysecrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..db import audit
from ..security import admin_user
from ..services import auth_config, auth_delivery, auth_providers, netinfo

router = APIRouter(prefix="/api/admin/auth-providers", tags=["auth-admin"])


class TestBody(BaseModel):
    target: str = ""


@router.get("")
async def list_providers(request: Request, user: dict = Depends(admin_user)):
    base = netinfo.origin(request) or str(request.base_url).rstrip("/")
    return {
        "items": auth_config.admin_items(base),
        "note": "密钥只保存在本机 data/auth_providers.json，页面不回显原文；环境变量优先于文件配置。",
    }


@router.put("/{provider}")
async def save_provider(provider: str, body: dict, request: Request,
                        user: dict = Depends(admin_user)):
    provider = provider.strip().lower()
    if provider not in ("qq", "wechat", "phone", "email"):
        raise HTTPException(404, "不支持这个登录方式")
    try:
        auth_config.save(provider, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    base = netinfo.origin(request) or str(request.base_url).rstrip("/")
    item = auth_config.item(provider, base)
    await audit(user, f"auth_config.{provider}.save", target=provider,
                detail=f"enabled={item['enabled']} ready={item['ready']} vendor={item['vendor']}",
                )
    return {"ok": True, "item": item,
            "msg": "已保存" if item["ready"] else "已保存，但配置还不完整，请按教程补齐必填项"}


@router.post("/{provider}/test")
async def test_provider(provider: str, body: TestBody, request: Request,
                        user: dict = Depends(admin_user)):
    provider = provider.strip().lower()
    if provider not in ("qq", "wechat", "phone", "email"):
        raise HTTPException(404, "不支持这个登录方式")
    cfg = auth_providers.provider_settings(provider)
    if not auth_providers.configured(provider, cfg):
        raise HTTPException(400, "配置不完整，先保存必填项再测试")

    target = body.target.strip()
    if provider == "phone":
        if not auth_delivery.PHONE_RE.fullmatch(target):
            raise HTTPException(400, "请填写要接收测试短信的手机号")
        code = f"{pysecrets.randbelow(1_000_000):06d}"
        try:
            msg = await auth_delivery.send_sms(cfg, target, code)
        except auth_delivery.DeliveryError as exc:
            raise HTTPException(400, str(exc))
        await audit(user, "auth_config.phone.test", target=target[-4:], detail=msg)
        return {"ok": True, "msg": f"{msg}，测试验证码 {code}（不会保存用于登录）"}
    if provider == "email":
        if not auth_delivery.EMAIL_RE.fullmatch(target):
            raise HTTPException(400, "请填写要接收测试邮件的邮箱")
        code = f"{pysecrets.randbelow(1_000_000):06d}"
        text = (f"这是一封来自本地 AI 工作台的测试邮件。\n\n"
                f"测试验证码：{code}\n\n收到说明 SMTP 配置可用，可以回控制台启用邮箱登录。")
        try:
            msg = await auth_delivery.send_email(cfg, target, "AI 工作台 SMTP 测试", text)
        except auth_delivery.DeliveryError as exc:
            raise HTTPException(400, str(exc))
        await audit(user, "auth_config.email.test", target=target, detail=msg)
        return {"ok": True, "msg": f"{msg}，测试验证码 {code}"}

    await audit(user, "auth_config.oauth.test", target=provider, detail="配置完整")
    return {"ok": True,
            "msg": "配置完整，可以保存并启用；保存后请到用户端登录页实际扫码验证"}


@router.delete("/{provider}/secret/{key}")
async def clear_secret(provider: str, key: str, user: dict = Depends(admin_user)):
    provider = provider.strip().lower()
    try:
        auth_config.clear_secret(provider, key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    await audit(user, f"auth_config.{provider}.clear_secret", target=key, detail="清除密钥")
    return {"ok": True}
