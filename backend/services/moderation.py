"""内容安全：敏感词检测、替换、拦截与命中记录。"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from ..config import load_config
from ..db import execute, fetch_all

ACTIONS = ("block", "replace", "warn")
ACTION_LABELS = {"block": "拦截", "replace": "替换", "warn": "仅告警"}

_cache: tuple[float, list[str]] = (0.0, [])


def invalidate() -> None:
    global _cache
    _cache = (0.0, [])


def normalize_action(value: str | None, default: str) -> str:
    value = (value or "").strip()
    return value if value in ACTIONS else default


def settings() -> dict[str, Any]:
    cfg = load_config()
    return {
        "enabled": bool(cfg.get("moderation_enabled")),
        "input_action": normalize_action(cfg.get("moderation_input_action"), "block"),
        "output_action": normalize_action(cfg.get("moderation_output_action"), "replace"),
        "replace_with": str(cfg.get("moderation_replace") or "***")[:20],
        "min_chars": max(1, min(int(cfg.get("moderation_min_chars") or 1), 20)),
    }


async def active_words() -> list[str]:
    """启用的词条，10 秒缓存；词库变更后调用 invalidate()。"""
    global _cache
    now = time.monotonic()
    if now - _cache[0] < 10:
        return _cache[1]
    rows = await fetch_all(
        "SELECT word FROM sensitive_words WHERE enabled=1 ORDER BY LENGTH(word) DESC, id")
    words = [str(r["word"] or "").strip() for r in rows if str(r["word"] or "").strip()]
    _cache = (now, words)
    return words


def _clean_words(words: list[str] | None, min_chars: int) -> list[str]:
    return [w for w in (words or []) if len(w) >= min_chars]


def detect(text: str, words: list[str], min_chars: int = 1) -> list[str]:
    if not text:
        return []
    lower = text.casefold()
    matched: list[str] = []
    for word in _clean_words(words, min_chars):
        if word.casefold() in lower:
            matched.append(word)
    return matched


def first_match_pos(text: str, words: list[str], min_chars: int = 1) -> int:
    lower = text.casefold()
    positions = [lower.find(w.casefold()) for w in _clean_words(words, min_chars)]
    positions = [p for p in positions if p >= 0]
    return min(positions) if positions else -1


_regex_cache: tuple[str, str] = ("", "")


def replace_words(text: str, words: list[str], replacement: str = "***") -> str:
    global _regex_cache
    if not text or not words:
        return text
    key = "\n".join(words)
    if _regex_cache[0] != key:
        ordered = sorted({w for w in words if w}, key=len, reverse=True)
        pattern = "|".join(re.escape(w) for w in ordered)
        _regex_cache = (key, pattern)
    if not _regex_cache[1]:
        return text
    return re.sub(_regex_cache[1], lambda _m: replacement, text, flags=re.IGNORECASE)


def snippet(text: str, words: list[str], limit: int = 220) -> str:
    pos = first_match_pos(text, words)
    if pos < 0:
        return " ".join(text.split())[:limit]
    start = max(0, pos - 60)
    end = min(len(text), pos + 160)
    piece = " ".join(text[start:end].split())
    return (("…" if start else "") + piece + ("…" if end < len(text) else ""))[:limit]


async def record_hit(*, user: dict, direction: str, action: str, words: list[str],
                     text: str, model: str = "", conversation_id: int | None = None) -> None:
    unique = list(dict.fromkeys(words))[:20]
    if not unique:
        return
    try:
        await execute(
            "INSERT INTO moderation_hits(user_id,username,direction,action,words,snippet,model,"
            "conversation_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (user.get("id"), user.get("username", ""), direction, action,
             json.dumps(unique, ensure_ascii=False), snippet(text, unique), model or "", conversation_id,
             time.time()))
    except Exception:
        pass


class StreamFilter:
    """流式输出过滤器：保留 maxlen-1 个字符的尾巴，避免敏感词跨 chunk 漏检。"""

    def __init__(self, *, action: str, words: list[str], replacement: str = "***",
                 min_chars: int = 1) -> None:
        self.action = action
        self.words = _clean_words(words, min_chars)
        self.replacement = replacement
        self.maxlen = max((len(w) for w in self.words), default=0)
        self.pending = ""
        self.matched: list[str] = []
        self.blocked = False

    def feed(self, text: str, final: bool = False) -> str:
        if self.blocked:
            return ""
        self.pending += text or ""
        if not self.words:
            out, self.pending = self.pending, ""
            return out
        found = detect(self.pending, self.words)
        for word in found:
            if word not in self.matched:
                self.matched.append(word)
        if self.action == "block" and found:
            self.blocked = True
            self.pending = ""
            return ""
        if self.action == "replace":
            self.pending = replace_words(self.pending, self.words, self.replacement)
        if final:
            out, self.pending = self.pending, ""
            return out
        keep = max(0, self.maxlen - 1)
        if len(self.pending) <= keep:
            return ""
        cut = len(self.pending) - keep
        out = self.pending[:cut]
        self.pending = self.pending[cut:]
        return out

    def flush(self) -> str:
        return self.feed("", final=True)


async def guard_input(text: str, *, user: dict, model: str = "",
                      conversation_id: int | None = None) -> dict[str, Any]:
    """返回 {text, matches, action, blocked}；replace 会改写 text。"""
    cfg = settings()
    if not cfg["enabled"]:
        return {"text": text, "matches": [], "action": "warn", "blocked": False}
    words = await active_words()
    matches = detect(text, words, cfg["min_chars"])
    if not matches:
        return {"text": text, "matches": [], "action": cfg["input_action"], "blocked": False}
    action = cfg["input_action"]
    await record_hit(user=user, direction="input", action=action, words=matches,
                     text=text, model=model, conversation_id=conversation_id)
    if action == "replace":
        text = replace_words(text, matches, cfg["replace_with"])
    return {"text": text, "matches": matches, "action": action,
            "blocked": action == "block"}


async def guard_output(text: str, *, user: dict, model: str = "",
                       conversation_id: int | None = None) -> dict[str, Any]:
    """非流式输出检测；block 时返回安全占位文本。"""
    cfg = settings()
    if not cfg["enabled"]:
        return {"text": text, "matches": [], "action": "warn", "blocked": False}
    words = await active_words()
    matches = detect(text, words, cfg["min_chars"])
    if not matches:
        return {"text": text, "matches": [], "action": cfg["output_action"], "blocked": False}
    action = cfg["output_action"]
    await record_hit(user=user, direction="output", action=action, words=matches,
                     text=text, model=model, conversation_id=conversation_id)
    if action == "block":
        text = "内容已被安全策略拦截。"
    elif action == "replace":
        text = replace_words(text, matches, cfg["replace_with"])
    return {"text": text, "matches": matches, "action": action, "blocked": action == "block"}
