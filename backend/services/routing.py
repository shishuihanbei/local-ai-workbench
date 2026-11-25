"""路由决策：本地优先 / 云端优先 / 手动指定，带 fallback 链。

返回的 decision 会原样写进 requests.decision_json，便于事后解释“为什么走这条”。
"""
from __future__ import annotations

import json

from ..config import load_config
from ..db import fetch_all, fetch_one
from .secrets_store import decrypt


async def _providers() -> list[dict]:
    return await fetch_all("SELECT * FROM providers WHERE enabled=1 ORDER BY id")


def _models_of(p: dict) -> list[str]:
    return [m.strip() for m in (p.get("models") or "").split(",") if m.strip()]


async def resolve(body, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    if getattr(body, "model", None):
        pool = await fetch_one("SELECT * FROM cluster_pools WHERE name=? AND enabled=1",
                               (body.model,))
        if pool:
            return {
                "provider": f"算力池 · {pool['name']}",
                "provider_id": None,
                "pool": pool["name"],
                "pool_id": pool["id"],
                "strategy": pool.get("strategy"),
                "base": "",
                "key": "",
                "model": pool["name"],
                "reason": f"请求模型 {pool['name']} 命中多机算力池",
                "route_id": None,
                "fallback": [],
                "price_in": 0.0,
                "price_out": 0.0,
            }
    local_enabled = bool(cfg.get("local_enabled", True))
    local = {
        "provider": "local",
        "provider_id": None,
        "base": str(cfg.get("upstream_base") or "").rstrip("/"),
        "key": str(cfg.get("upstream_key") or ""),
        "model": body.model or cfg.get("model") or "local",
        "strategy": "local",
        "reason": "本地上游（llama.cpp）",
        "route_id": None,
        "fallback": [],
        "price_in": 0.0,
        "price_out": 0.0,
    }

    providers = await _providers()
    for p in providers:
        try:
            p["api_key"] = decrypt(p.get("api_key"))
        except Exception:
            p["api_key"] = ""
    if not providers:
        if local_enabled:
            return local
        return {**local, "base": "", "disabled": True,
                "reason": "本地部署已关闭，且没有可用的第三方供应商"}

    route = await fetch_one("SELECT * FROM routes WHERE enabled=1 ORDER BY id LIMIT 1")
    strategy = (route or {}).get("strategy", "local_first")
    model_map = {}
    if route:
        try:
            model_map = json.loads(route.get("model_map") or "{}")
        except Exception:
            model_map = {}

    by_id = {p["id"]: p for p in providers}
    # 手动：请求里的 model 命中某供应商的模型清单
    if body.model:
        for p in providers:
            if body.model in _models_of(p):
                target = model_map.get(body.model, body.model)
                return {
                    "provider": p["name"], "provider_id": p["id"],
                    "base": p["base_url"].rstrip("/"), "key": p["api_key"],
                    "model": target, "strategy": "manual",
                    "reason": f"请求模型 {body.model} 命中供应商 {p['name']}",
                    "route_id": (route or {}).get("id"),
                    "fallback": json.loads((route or {}).get("fallback") or "[]"),
                    "price_in": p["price_in"], "price_out": p["price_out"],
                }

    if not local_enabled and body.model:
        row = await fetch_one("SELECT key FROM models WHERE key=? OR alias=?", (body.model, body.model))
        if row:
            return {**local, "base": "", "disabled": True,
                    "reason": "本地部署已关闭，不能调用本地模型"}

    preferred = None
    if route and route.get("provider_id") in by_id:
        preferred = by_id[route["provider_id"]]
    elif strategy == "cloud_first":
        preferred = providers[0]

    if strategy == "cloud_first" and preferred:
        target = model_map.get(local["model"], local["model"])
        if not body.model and not model_map.get(local["model"]):
            target = (_models_of(preferred) or [target])[0]
        return {
            "provider": preferred["name"], "provider_id": preferred["id"],
            "base": preferred["base_url"].rstrip("/"), "key": preferred["api_key"],
            "model": target,
            "strategy": "cloud_first",
            "reason": f"云端优先，选用 {preferred['name']}",
            "route_id": (route or {}).get("id"),
            "fallback": json.loads((route or {}).get("fallback") or "[]"),
            "price_in": preferred["price_in"], "price_out": preferred["price_out"],
        }
    if not local_enabled:
        chosen = preferred or providers[0]
        target = model_map.get(local["model"], local["model"])
        if not body.model and not model_map.get(local["model"]):
            target = (_models_of(chosen) or [target])[0]
        return {
            "provider": chosen["name"], "provider_id": chosen["id"],
            "base": chosen["base_url"].rstrip("/"), "key": chosen["api_key"],
            "model": target,
            "strategy": "cloud_fallback",
            "reason": f"本地部署已关闭，自动改用 {chosen['name']}",
            "route_id": (route or {}).get("id"),
            "fallback": [],
            "price_in": chosen["price_in"], "price_out": chosen["price_out"],
        }
    return local
