"""认证：首次初始化、注册、登录、退出、会话信息、改密、数据导出。"""
from __future__ import annotations

import re
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from ..errors import (
    ACCOUNT_DISABLED,
    INVALID_CREDENTIALS,
    RATE_LIMITED,
    REGISTER_CLOSED,
    APIError,
)

from ..db import audit, execute, fetch_all, fetch_one
from ..security import (CSRF_COOKIE, SESSION_COOKIE, admin_permissions, admin_user, check_csrf,
                        clear_login_fail, client_ip, create_access_token, create_session,
                        current_user, hash_password, login_blocked, new_csrf, note_login_fail,
                        password_problem, revoke_session, revoke_user_sessions, verify_password)
from ..config import load_config
from ..services import branding
from ..services import access, auth_identity, auth_oauth, auth_providers, netinfo, otp

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 注册按 IP 限流：10 分钟内最多 6 次，防止有人脚本批量开号
_REG_HITS: dict[str, list[float]] = {}
_REG_WINDOW, _REG_MAX = 600, 6
_OAUTH_STATES: dict[str, float] = {}


def _register_gate(ip: str) -> int:
    now = time.time()
    hist = [t for t in _REG_HITS.get(ip, []) if now - t < _REG_WINDOW]
    _REG_HITS[ip] = hist
    if len(hist) >= _REG_MAX:
        return int(_REG_WINDOW - (now - hist[0])) + 1
    hist.append(now)
    return 0


class SetupBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=8, max_length=128)


class ChangePwBody(BaseModel):
    old_password: str
    new_password: str


class OtpSendBody(BaseModel):
    channel: str
    target: str


class OtpLoginBody(BaseModel):
    channel: str
    target: str
    code: str


class OtpRegisterBody(BaseModel):
    channel: str
    target: str
    code: str
    username: str | None = None


class OtpBindBody(BaseModel):
    channel: str
    target: str
    code: str


@router.get("/state")
async def auth_state(request: Request, wb_session: str | None = None):
    users = await fetch_one("SELECT COUNT(*) c FROM users")
    from ..security import session_user
    user = await session_user(request.cookies.get(SESSION_COOKIE))
    cfg = load_config()
    return {"initialized": bool(users and users["c"]),
            "allow_register": bool(cfg.get("allow_register")),
            "branding": branding.public(),
            "user": user}


@router.get("/providers")
async def list_providers():
    """公开的登录方式状态，供登录页和设置页渲染入口。"""
    cfg = load_config()
    return {"default": "username", "allow_register": bool(cfg.get("allow_register")),
            "items": auth_providers.public_providers()}


@router.get("/identities")
async def my_identities(user: dict = Depends(current_user)):
    """当前账号已绑定的登录方式。用户名会始终补一条，兼容老账号。"""
    rows = await auth_identity.list_identities(user["id"])
    if not any(r["provider"] == "username" for r in rows):
        await auth_identity.link_identity(user["id"], "username", user["username"], user["username"])
        rows = await auth_identity.list_identities(user["id"])
    labels = auth_providers.LABELS
    status = {p["key"]: p for p in auth_providers.public_providers()}
    items = [{**r, "label": labels.get(r["provider"], r["provider"]),
              "ready": bool(status.get(r["provider"], {}).get("ready"))} for r in rows]
    return {"items": items, "providers": auth_providers.public_providers()}


def _oauth_redirect(request: Request, ok: bool = False, message: str = "") -> RedirectResponse:
    cfg = load_config()
    base = ""
    if cfg.get("serve_frontend"):
        base = netinfo.origin(request)
    base = base or str(cfg.get("frontend_url") or "").strip() or netinfo.origin(request)
    base = base or str(request.base_url)
    base = base.rstrip("/")
    sep = "&" if "?" in base else "?"
    return RedirectResponse(
        f"{base}{sep}oauth={'ok' if ok else 'error'}&message={quote(message[:120])}",
        status_code=302)


async def _attach_session(response: Response, user_id: int, username: str, role: str,
                          request: Request) -> None:
    token, _sid = await create_session(user_id, client_ip(request), request.headers.get("user-agent", ""))
    csrf = new_csrf()
    hours = int(load_config().get("session_hours", 72))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=hours * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")


def _oauth_username(provider: str, nickname: str, provider_uid: str) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff-]", "", nickname or "").strip("_")[:24]
    if len(base) < 2:
        base = f"{provider}_{provider_uid[-6:]}"
    return base[:32]


async def _oauth_create_user(provider: str, identity: dict) -> int:
    if not load_config().get("allow_register"):
        raise APIError(403, "管理员未开放自助注册，第三方账号无法自动创建", REGISTER_CLOSED)
    if not await fetch_one("SELECT id FROM users WHERE role='admin' AND disabled=0"):
        raise HTTPException(409, "系统还没有管理员")
    base = _oauth_username(provider, identity["display_name"], identity["provider_uid"])
    username = base
    n = 1
    while await fetch_one("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)):
        n += 1
        suffix = f"_{n}"
        username = base[:32 - len(suffix)] + suffix
    local = await fetch_all("SELECT key FROM models ORDER BY sort,key")
    uid = await execute(
        "INSERT INTO users(username,password_hash,role,allowed_models,created_at) VALUES(?,?,?,?,?)",
        (username, hash_password(secrets.token_urlsafe(32)), "user",
         access.normalize([r["key"] for r in local]), time.time()))
    await auth_identity.link_identity(uid, provider, identity["provider_uid"],
                                      identity["display_name"], identity.get("meta") or
                                      {"avatar": identity.get("avatar", "")})
    await audit({"id": uid, "username": username}, f"auth.{provider}.register",
                detail=f"{provider} 自动创建账号", ip="")
    return uid


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, request: Request):
    provider = provider.strip().lower()
    if provider not in ("qq", "wechat"):
        raise HTTPException(404, "不支持的第三方登录")
    item = auth_providers.public_item(provider)
    if not item.get("enabled"):
        raise HTTPException(501, f"{item['label']} 登录接口已预留，配置后启用")
    if not item.get("ready"):
        raise HTTPException(501, f"{item['label']} 登录配置不完整，请填 client/app id、secret 和回调地址")
    state = auth_providers.make_state(provider)
    fallback = (netinfo.origin(request) or str(request.base_url).rstrip("/")) + f"/api/auth/oauth/{provider}/callback"
    return RedirectResponse(auth_providers.oauth_authorize_url(provider, state, fallback), status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, code: str = "", state: str = "",
                         error: str = "", error_description: str = ""):
    provider = provider.strip().lower()
    if provider not in ("qq", "wechat"):
        raise HTTPException(404, "不支持的第三方登录")
    if error:
        return _oauth_redirect(request, False, error_description or error)
    if not auth_providers.verify_state(provider, state):
        return _oauth_redirect(request, False, "登录状态已失效，请重新发起")
    now = time.time()
    for key, ts in list(_OAUTH_STATES.items()):
        if now - ts > 600:
            _OAUTH_STATES.pop(key, None)
    if state in _OAUTH_STATES:
        return _oauth_redirect(request, False, "该登录请求已使用，请重新发起")
    _OAUTH_STATES[state] = now
    if not code:
        return _oauth_redirect(request, False, "第三方未返回授权码")

    try:
        identity = await auth_oauth.exchange_code(provider, code)
    except auth_oauth.OAuthError as exc:
        return _oauth_redirect(request, False, str(exc))
    except Exception:
        return _oauth_redirect(request, False, "连接第三方登录服务失败")

    row = await auth_identity.resolve_identity(provider, identity["provider_uid"])
    if row:
        if row["disabled"]:
            return _oauth_redirect(request, False, "该账号已被禁用")
        uid, username, role = int(row["user_id"]), row["username"], row["role"]
        await auth_identity.touch_identity(int(row["id"]))
    else:
        try:
            uid = await _oauth_create_user(provider, identity)
        except HTTPException as exc:
            return _oauth_redirect(request, False, str(exc.detail))
        user_row = await fetch_one("SELECT username,role FROM users WHERE id=?", (uid,))
        username, role = user_row["username"], user_row["role"]

    response = _oauth_redirect(request, True, "")
    await _attach_session(response, uid, username, role, request)
    await execute("UPDATE users SET last_login_at=?, last_login_ip=? WHERE id=?",
                  (time.time(), client_ip(request), uid))
    await audit({"id": uid, "username": username}, f"auth.{provider}.login", ip=client_ip(request))
    return response


@router.post("/otp/send")
async def send_otp_code(body: OtpSendBody, request: Request):
    """发送手机号 / 邮箱验证码。"""
    channel = body.channel.strip().lower()
    if channel not in ("phone", "email"):
        raise HTTPException(400, "channel 只能是 phone 或 email")
    try:
        result = await otp.send(channel, body.target)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(400, f"验证码发送失败：{str(exc)[:160]}")
    await audit({"username": body.target[-6:]}, f"auth.{channel}.otp.send",
                target=channel, ip=client_ip(request))
    return result


@router.post("/otp/login")
async def login_with_otp(body: OtpLoginBody, request: Request, response: Response):
    """手机号 / 邮箱验证码登录。"""
    channel = body.channel.strip().lower()
    if channel not in ("phone", "email"):
        raise HTTPException(400, "channel 只能是 phone 或 email")
    item = auth_providers.public_item(channel)
    if not item.get("enabled") or not item.get("ready"):
        raise HTTPException(501, f"{item['label']}登录尚未启用，请联系管理员")
    ok, message = otp.verify(channel, body.target, body.code)
    if not ok:
        raise HTTPException(400, message)
    target = otp.normalize(channel, body.target)
    row = await auth_identity.resolve_identity(channel, target)
    if not row:
        raise HTTPException(404, f"该{item['label']}还没有绑定账号，请先注册或让管理员绑定")
    if row["disabled"]:
        raise APIError(403, "账号已被禁用", ACCOUNT_DISABLED)
    await auth_identity.touch_identity(int(row["id"]))
    token, sid = await create_session(int(row["user_id"]), client_ip(request),
                                      request.headers.get("user-agent", ""))
    csrf = new_csrf()
    hours = int(load_config().get("session_hours", 72))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=hours * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")
    await execute("UPDATE users SET last_login_at=?, last_login_ip=? WHERE id=?",
                  (time.time(), client_ip(request), row["user_id"]))
    access_token, expires_in = create_access_token(int(row["user_id"]), sid, row["username"], row["role"])
    await audit({"id": row["user_id"], "username": row["username"]},
                f"auth.{channel}.login", ip=client_ip(request))
    return {"ok": True, "user": {"id": int(row["user_id"]), "username": row["username"],
                                 "role": row["role"]},
            "csrf": csrf, "access_token": access_token, "expires_in": expires_in}


def _otp_username(channel: str, target: str, wanted: str | None) -> str:
    base = re.sub(r"[^\w\u4e00-\u9fff-]", "", wanted or "").strip("_")[:24]
    if len(base) < 2:
        if channel == "email" and "@" in target:
            base = target.split("@", 1)[0][:20]
        else:
            base = target[-6:]
    base = re.sub(r"[^\w\u4e00-\u9fff-]", "", base) or "user"
    return base[:32]


@router.post("/otp/register")
async def register_with_otp(body: OtpRegisterBody, request: Request, response: Response):
    """手机号 / 邮箱验证码注册。"""
    channel = body.channel.strip().lower()
    if channel not in ("phone", "email"):
        raise HTTPException(400, "channel 只能是 phone 或 email")
    cfg = load_config()
    if not cfg.get("allow_register"):
        raise HTTPException(403, "管理员未开放自助注册")
    item = auth_providers.public_item(channel)
    if not item.get("enabled") or not item.get("ready"):
        raise HTTPException(501, f"{item['label']}注册尚未启用，请联系管理员")
    ok, message = otp.verify(channel, body.target, body.code)
    if not ok:
        raise HTTPException(400, message)
    target = otp.normalize(channel, body.target)
    if await auth_identity.resolve_identity(channel, target):
        raise HTTPException(409, f"该{item['label']}已经绑定账号，请直接登录")
    if not await fetch_one("SELECT id FROM users WHERE role='admin' AND disabled=0"):
        raise HTTPException(409, "系统还没有管理员")
    base = _otp_username(channel, target, body.username)
    username = base
    n = 1
    while await fetch_one("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)):
        n += 1
        suffix = f"_{n}"
        username = base[:32 - len(suffix)] + suffix
    local = await fetch_all("SELECT key FROM models ORDER BY sort,key")
    allowed = access.normalize([r["key"] for r in local])
    now = time.time()
    uid = await execute(
        "INSERT INTO users(username,password_hash,role,allowed_models,created_at) VALUES(?,?,?,?,?)",
        (username, hash_password(secrets.token_urlsafe(32)), "user", allowed, now))
    await auth_identity.link_identity(uid, channel, target, target)
    token, sid = await create_session(uid, client_ip(request), request.headers.get("user-agent", ""))
    csrf = new_csrf()
    hours = int(cfg.get("session_hours", 72))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=hours * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")
    access_token, expires_in = create_access_token(uid, sid, username, "user")
    await audit({"id": uid, "username": username}, f"auth.{channel}.register",
                detail=f"{channel} 验证码注册", ip=client_ip(request))
    return {"ok": True, "user": {"id": uid, "username": username, "role": "user"},
            "csrf": csrf, "access_token": access_token, "expires_in": expires_in}


@router.post("/identities/bind")
async def bind_identity(body: OtpBindBody, request: Request, user: dict = Depends(current_user)):
    """给当前账号绑定手机号或邮箱。"""
    channel = body.channel.strip().lower()
    if channel not in ("phone", "email"):
        raise HTTPException(400, "channel 只能是 phone 或 email")
    item = auth_providers.public_item(channel)
    if not item.get("enabled") or not item.get("ready"):
        raise HTTPException(501, f"{item['label']}绑定尚未启用，请联系管理员")
    ok, message = otp.verify(channel, body.target, body.code)
    if not ok:
        raise HTTPException(400, message)
    target = otp.normalize(channel, body.target)
    row = await auth_identity.resolve_identity(channel, target)
    if row and int(row["user_id"]) != int(user["id"]):
        raise HTTPException(409, f"该{item['label']}已经绑定了其他账号")
    if not row:
        await auth_identity.link_identity(int(user["id"]), channel, target, target)
    await audit(user, f"auth.{channel}.bind", target=channel, ip=client_ip(request))
    return {"ok": True, "msg": f"{item['label']}已绑定"}


@router.post("/setup")
async def setup(body: SetupBody, request: Request, response: Response):
    users = await fetch_one("SELECT COUNT(*) c FROM users")
    if users and users["c"]:
        raise HTTPException(400, "系统已完成初始化")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    uid = await execute(
        "INSERT INTO users(username,password_hash,role,created_at) VALUES(?,?,?,?)",
        (body.username.strip(), hash_password(body.password), "admin", time.time()))
    await auth_identity.link_identity(uid, "username", body.username, body.username)
    token, sid = await create_session(uid, client_ip(request), request.headers.get("user-agent", ""))
    csrf = new_csrf()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=int(load_config().get("session_hours", 72)) * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")
    await audit({"id": uid, "username": body.username}, "auth.setup", detail="创建管理员", ip=client_ip(request))
    token_jwt, expires_in = create_access_token(uid, sid, body.username, "admin")
    return {"ok": True, "user": {"id": uid, "username": body.username, "role": "admin"},
            "csrf": csrf, "access_token": token_jwt, "expires_in": expires_in}


@router.post("/register")
async def register(body: RegisterBody, request: Request, response: Response):
    cfg = load_config()
    if not cfg.get("allow_register"):
        raise HTTPException(403, "管理员未开放自助注册")
    if not await fetch_one("SELECT id FROM users WHERE role='admin' AND disabled=0"):
        raise HTTPException(409, "系统还没有管理员，请先在控制台初始化管理员")
    ip = client_ip(request)
    wait = _register_gate(ip)
    if wait:
        raise APIError(429, f"注册太频繁，请 {wait} 秒后再试", RATE_LIMITED, extra={"retry_after": wait})
    username = body.username.strip()
    if await fetch_one("SELECT id FROM users WHERE lower(username)=lower(?)", (username,)):
        raise HTTPException(409, "用户名已被占用")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    # 新用户默认拿到全部本地模型；第三方 API 模型由管理员按需分配
    local = await fetch_all("SELECT key FROM models ORDER BY sort,key")
    allowed = access.normalize([r["key"] for r in local])
    now = time.time()
    uid = await execute(
        "INSERT INTO users(username,password_hash,role,allowed_models,created_at) VALUES(?,?,?,?,?)",
        (username, hash_password(body.password), "user", allowed, now))
    await auth_identity.link_identity(uid, "username", username, username)
    token, sid = await create_session(uid, ip, request.headers.get("user-agent", ""))
    csrf = new_csrf()
    hours = int(cfg.get("session_hours", 72))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        max_age=hours * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")
    await audit({"id": uid, "username": username}, "auth.register", detail="自助注册", ip=ip)
    token_jwt, expires_in = create_access_token(uid, sid, username, "user")
    return {"ok": True, "user": {"id": uid, "username": username, "role": "user"},
            "csrf": csrf, "access_token": token_jwt, "expires_in": expires_in}


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    ip = client_ip(request)
    key = f"{ip}|{body.username.lower()}"
    wait = login_blocked(key)
    if wait:
        await audit({"username": body.username}, "auth.login", status="locked",
                    detail=f"锁定 {wait}s", ip=ip)
        raise APIError(429, f"尝试次数过多，请 {wait} 秒后再试", RATE_LIMITED, extra={"retry_after": wait})
    row = await fetch_one("SELECT * FROM users WHERE username=?", (body.username.strip(),))
    if not row or not verify_password(body.password, row["password_hash"]):
        note_login_fail(key)
        await audit({"username": body.username}, "auth.login", status="fail", detail="用户名或密码错误", ip=ip)
        raise APIError(401, "用户名或密码错误", INVALID_CREDENTIALS)
    if row["disabled"]:
        raise APIError(403, "账号已被禁用", ACCOUNT_DISABLED)
    clear_login_fail(key)
    token, sid = await create_session(row["id"], ip, request.headers.get("user-agent", ""))
    csrf = new_csrf()
    hours = int(load_config().get("session_hours", 72))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=hours * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, samesite="lax", path="/")
    await execute("UPDATE users SET last_login_at=?, last_login_ip=? WHERE id=?",
                  (time.time(), ip, row["id"]))
    await audit({"id": row["id"], "username": row["username"]}, "auth.login", ip=ip)
    token_jwt, expires_in = create_access_token(row["id"], sid, row["username"], row["role"])
    return {"ok": True, "user": {"id": row["id"], "username": row["username"], "role": row["role"]},
            "csrf": csrf, "access_token": token_jwt, "expires_in": expires_in}


@router.post("/logout")
async def logout(request: Request, response: Response, user: dict = Depends(current_user)):
    csrf_ok = check_csrf(request, request.cookies.get(CSRF_COOKIE), request.headers.get("x-csrf-token"))
    if not csrf_ok:
        raise HTTPException(403, "CSRF 校验失败")
    await revoke_session(user["sid"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    await audit(user, "auth.logout", ip=client_ip(request))
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    row = await fetch_one("SELECT created_at,last_login_at,last_login_ip FROM users WHERE id=?", (user["id"],))
    perms = await admin_permissions(user)
    return {"user": {**user, **(row or {}), "admin_permissions": perms}}


@router.post("/password")
async def change_password(body: ChangePwBody, request: Request, user: dict = Depends(current_user)):
    csrf_ok = check_csrf(request, request.cookies.get(CSRF_COOKIE), request.headers.get("x-csrf-token"))
    if not csrf_ok:
        raise HTTPException(403, "CSRF 校验失败")
    row = await fetch_one("SELECT password_hash FROM users WHERE id=?", (user["id"],))
    if not row or not verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(400, "原密码不正确")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(400, problem)
    await execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(body.new_password), user["id"]))
    await revoke_user_sessions(user["id"], keep_sid=user["sid"])
    await audit(user, "auth.password", detail="修改密码", ip=client_ip(request))
    return {"ok": True}


@router.get("/sessions")
async def my_sessions(user: dict = Depends(current_user)):
    rows = await fetch_all(
        "SELECT id,created_at,expires_at,ip,ua FROM sessions "
        "WHERE user_id=? AND revoked=0 AND expires_at>? ORDER BY created_at DESC LIMIT 50",
        (user["id"], time.time()))
    items = [{**r, "current": r["id"] == user["sid"]} for r in rows]
    return {"items": items, "current_sid": user["sid"]}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(request: Request, user: dict = Depends(current_user)):
    await revoke_user_sessions(user["id"], keep_sid=user["sid"])
    await audit(user, "auth.sessions.revoke_others", ip=client_ip(request))
    return {"ok": True}


@router.get("/export")
async def export_my_data(user: dict = Depends(current_user)):
    convs = await fetch_all(
        "SELECT id,title,model,system_prompt,created_at,updated_at FROM conversations "
        "WHERE user_id=? ORDER BY created_at", (user["id"],))
    for c in convs:
        c["messages"] = await fetch_all(
            "SELECT role,content,reasoning,tokens,created_at FROM messages "
            "WHERE conversation_id=? ORDER BY id", (c["id"],))
    payload = {"user": {"username": user["username"], "role": user["role"]},
               "exported_at": time.time(), "conversations": convs}
    filename = f"workbench-{user['username']}-{time.strftime('%Y%m%d')}.json"
    return JSONResponse(payload, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})
