"""FastAPI 应用入口（纯 API 服务，可独立部署）。

前后端分离模式（默认）：本服务只提供 /api/*，前端由任意静态服务器托管。
单进程模式：设置 serve_frontend=true，本服务顺带托管 frontend/ 目录。
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, FRONTEND_DIR, LOG_DIR, load_config
from . import logbus
from .db import init_db
from .routers import (admin, apikeys, auth, auth_admin, branding, chat, cluster, collab, database, files,
                      front as front_admin, kb,
                      library, memory,
                      models, my_memory, openai_api, ops, prompts as prompt_admin, system, upload_admin, users,
                      workbench)

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
              logging.StreamHandler()],
)
log = logging.getLogger("workbench")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from .services import storage
        st = storage.ensure()
        log.info("存储目录：模型 %s；平台 %s", st["models_dir"], st["platforms_dir"])
    except Exception:
        log.exception("存储目录初始化失败，将使用配置里的原路径")
    await init_db()
    try:
        from .services import prompts as prompt_registry
        seeded = await prompt_registry.seed_defaults(load_config().get("system_prompt") or "")
        if seeded:
            log.info("提示词中心已同步 %s 个内置资产", seeded)
    except Exception:
        log.exception("提示词中心种子写入失败，将使用代码默认值")
    try:
        from .services import front_features
        created = await front_features.seed_defaults(load_config())
        if created:
            log.info("前台功能注册表已补齐 %s 个入口", created)
    except Exception:
        log.exception("前台功能注册表初始化失败，将使用代码默认值")
    try:
        from .services import secrets_store
        moved = await secrets_store.migrate()
        if moved:
            log.info("已把 %s 个供应商 Key 迁移为加密存储", moved)
    except Exception:
        log.exception("供应商 Key 迁移失败，仍可按明文兼容读取")
    try:
        from .services import auth_providers
        enc = auth_providers.migrate_secrets()
        if enc:
            log.info("已把 %s 个登录方式密钥迁移为加密存储", enc)
    except Exception:
        log.exception("登录方式密钥迁移失败，仍可按明文兼容读取")
    logbus.start()
    try:
        from .services import cluster
        cluster.start_monitor()
    except Exception:
        log.exception("算力池健康检查启动失败")
    cfg = load_config()
    log.info("workbench 启动 port=%s cors=%s frontend=%s", cfg.get("port"),
             cfg.get("cors_origins"), cfg.get("serve_frontend"))

    async def _restore_local_model() -> None:
        try:
            from .services.llama import server
            ok, msg = await server.restore()
            if msg:
                log.info("恢复上次模型：%s（%s）", "成功" if ok else "跳过", msg)
        except Exception:
            log.exception("恢复上次模型失败")

    app.state.model_task = asyncio.create_task(_restore_local_model())
    try:
        from .services import retention
        await retention.start()
    except Exception:
        log.exception("生成文档自动清理启动失败")
    try:
        from .services import scheduler
        await scheduler.start()
    except Exception:
        log.exception("定时任务调度器启动失败")
    try:
        from .services import shortcuts
        res = shortcuts.ensure_once()
        if res and res.get("ok"):
            log.info("已在桌面创建前台/后台快捷方式")
    except Exception:
        log.exception("桌面快捷方式创建失败，可在控制台部署页手动创建")
    yield
    try:
        from .services import retention
        await retention.stop()
    except Exception:
        pass
    try:
        from .services import scheduler
        await scheduler.stop()
    except Exception:
        pass
    task = getattr(app.state, "model_task", None)
    if task and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    await logbus.stop()
    try:
        from .services import cluster
        await cluster.stop_monitor()
    except Exception:
        pass
    try:
        from .services.llama import server
        from .services.tunnel import tunnel
        await server.stop()
        tunnel.stop()
    except Exception:
        pass


app = FastAPI(title="本地 AI 工作台 API", version="0.8.1", docs_url=None,
              redoc_url=None, openapi_url="/api/openapi.json", lifespan=lifespan)

DOCS_DIR = Path(__file__).resolve().parent / "static" / "swagger"
if DOCS_DIR.is_dir():
    app.mount("/api/docs-assets", StaticFiles(directory=DOCS_DIR), name="api-docs-assets")


@app.get("/api/docs", include_in_schema=False)
async def api_docs():
    """离线可用的接口文档：Swagger UI 资源随程序一起分发，不依赖 CDN。"""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/api/docs-assets/swagger-ui-bundle.js",
        swagger_css_url="/api/docs-assets/swagger-ui.css",
        swagger_favicon_url="/api/docs-assets/favicon.png",
    )


def _origins() -> list[str]:
    raw = str(load_config().get("cors_origins") or "")
    if raw.strip() == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins(),
    allow_credentials=False,          # 使用 Bearer 令牌，不依赖跨站 Cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("X-API-Version", "0.8.1")
    if request.url.path.startswith("/console"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    if request.url.path == "/api/docs":
        # Swagger UI 页面自带一小段初始化脚本；只在这一页放行内联脚本。
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'")
    elif not request.url.path.startswith("/api/tts/audio"):
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
            "font-src 'self' data:; frame-ancestors 'none'")
    cost = time.time() - start
    if cost > 2:
        log.warning("慢请求 %s %s %.1fs", request.method, request.url.path, cost)
    return response


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    log.exception("未处理异常 %s: %s", request.url.path, exc)
    return JSONResponse({"detail": "服务器内部错误"}, status_code=500)


for r in (auth.router, auth_admin.router, branding.router, users.router, chat.router, files.router, files.exports_router,
          models.router, kb.router, kb.my_router, library.admin_router, library.my_router,
          ops.router, system.router, admin.router, apikeys.router, cluster.router,
          database.router, openai_api.router, memory.router, my_memory.router,
          prompt_admin.router,
          front_admin.router, front_admin.admin_router,
          collab.router, collab.admin_router, workbench.router, upload_admin.router):
    app.include_router(r)


@app.get("/api/health")
async def health():
    """免登录健康检查，供探针与前端探测后端。"""
    return {"status": "ok", "ts": time.time(), "service": "workbench-api", "version": "0.8.1"}


@app.get("/api/meta")
async def meta():
    cfg = load_config()
    return {
        "name": "本地 AI 工作台",
        "version": "0.8.1",
        "mode": "single-process" if cfg.get("serve_frontend") else "api-only",
        "features": ["chat", "models", "kb", "memory", "tts", "tunnel", "users", "audit",
                     "api_keys", "openai_api", "cluster", "workbench", "scheduled_tasks",
                     "generated_files"],
        "token_auth": True,
    }


CONSOLE_DIR = BASE_DIR / "backend" / "console"
if CONSOLE_DIR.exists():
    app.mount("/console", StaticFiles(directory=str(CONSOLE_DIR), html=True), name="console")


@app.get("/chat/{conversation_id}")
async def frontend_chat(conversation_id: int):
    """让对话有可收藏、可分享的地址：/chat/123 直接打开同一段对话。"""
    if str(load_config().get("serve_frontend", False)).lower() not in ("1", "true", "yes", "on"):
        return RedirectResponse("/console")
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        return RedirectResponse("/console")
    return FileResponse(index, media_type="text/html")


@app.get("/share/{token}")
async def shared_conversation_page(token: str):
    """只读分享页：/share/<token> 可直接在浏览器打开。"""
    if not (BASE_DIR / "frontend" / "share.html").exists():
        return RedirectResponse("/console")
    return FileResponse(BASE_DIR / "frontend" / "share.html", media_type="text/html")


@app.get("/wb/{token}")
async def shared_workbench_page(token: str):
    """工作台分享页：/wb/<token> 可直接在浏览器打开。"""
    page = BASE_DIR / "frontend" / "workbench-share.html"
    if not page.exists():
        return RedirectResponse("/console")
    return FileResponse(page, media_type="text/html")


if str(load_config().get("serve_frontend", False)).lower() in ("1", "true", "yes", "on") and FRONTEND_DIR.exists():
    # 单进程模式：前端文件直接挂在根路径（index.html 自动接管 /）
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        # 纯后端模式：根路径直接进入「管理控制台」
        return RedirectResponse("/console")


@app.get("/favicon.ico")
@app.get("/favicon.svg")
async def favicon():
    for p in (CONSOLE_DIR / "favicon.svg", FRONTEND_DIR / "favicon.svg"):
        if p.exists():
            return FileResponse(p, media_type="image/svg+xml")
    return JSONResponse({}, status_code=204)










