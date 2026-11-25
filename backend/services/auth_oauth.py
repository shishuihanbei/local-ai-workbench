"""QQ / 微信 OAuth 的真实换取逻辑。

未配置凭据时不会走到这里；配置后由 /api/auth/oauth/{provider}/callback 调用。
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .auth_providers import provider_settings


class OAuthError(Exception):
    pass


def _json_body(text: str) -> dict:
    """QQ 部分接口会返回 callback( {...} ); 这里统一剥壳。"""
    text = (text or "").strip()
    match = re.search(r"callback\s*\(\s*(\{.*\})\s*\)", text, re.S)
    if match:
        text = match.group(1)
    try:
        data = json.loads(text)
    except Exception as exc:
        raise OAuthError(f"第三方返回格式无法解析: {text[:120]}") from exc
    if not isinstance(data, dict):
        raise OAuthError("第三方返回格式不是对象")
    return data


async def _qq_identity(code: str, cfg: dict) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.get(
            "https://graph.qq.com/oauth2.0/token",
            params={"grant_type": "authorization_code", "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"], "code": code,
                    "redirect_uri": cfg["redirect_uri"], "fmt": "json"})
        token_data = _json_body(token_resp.text)
        token = token_data.get("access_token")
        if not token:
            raise OAuthError(token_data.get("error_description") or "QQ 未返回 access_token")

        me_resp = await client.get(
            "https://graph.qq.com/oauth2.0/me",
            params={"access_token": token, "fmt": "json"})
        me = _json_body(me_resp.text)
        openid = me.get("openid")
        if not openid:
            raise OAuthError(me.get("error_description") or "QQ 未返回 openid")

        info_resp = await client.get(
            "https://graph.qq.com/user/get_user_info",
            params={"access_token": token, "oauth_consumer_key": cfg["client_id"], "openid": openid})
        info = _json_body(info_resp.text)
        if str(info.get("ret")) not in ("0", "None") and info.get("ret") is not None:
            raise OAuthError(info.get("msg") or "QQ 用户信息获取失败")
        nickname = str(info.get("nickname") or "").strip() or f"QQ用户{str(openid)[-6:]}"
        return {"provider_uid": str(openid), "display_name": nickname,
                "avatar": info.get("figureurl_qq_1") or info.get("figureurl_qq_2") or ""}


async def _wechat_identity(code: str, cfg: dict) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.get(
            "https://api.weixin.qq.com/sns/oauth2/access_token",
            params={"appid": cfg["app_id"], "secret": cfg["app_secret"], "code": code,
                    "grant_type": "authorization_code"})
        token_data = token_resp.json()
        if token_data.get("errcode"):
            raise OAuthError(token_data.get("errmsg") or "微信授权失败")
        access_token = token_data.get("access_token")
        openid = token_data.get("openid")
        if not access_token or not openid:
            raise OAuthError("微信未返回 access_token 或 openid")

        info_resp = await client.get(
            "https://api.weixin.qq.com/sns/userinfo",
            params={"access_token": access_token, "openid": openid, "lang": "zh_CN"})
        info = info_resp.json()
        if info.get("errcode"):
            raise OAuthError(info.get("errmsg") or "微信用户信息获取失败")
        uid = str(info.get("unionid") or openid)
        nickname = str(info.get("nickname") or "").strip() or f"微信用户{str(uid)[-6:]}"
        return {"provider_uid": uid, "display_name": nickname,
                "avatar": info.get("headimgurl") or "",
                "meta": {"openid": openid, "unionid": info.get("unionid") or ""}}


async def exchange_code(provider: str, code: str) -> dict[str, Any]:
    cfg = provider_settings(provider)
    if provider == "qq":
        return await _qq_identity(code, cfg)
    if provider == "wechat":
        return await _wechat_identity(code, cfg)
    raise OAuthError("不支持的 OAuth 登录方式")
