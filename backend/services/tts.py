"""语音合成（Edge TTS），生成 mp3 供前端播放。"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from ..config import AUDIO_DIR, load_config

VOICES = [
    # (分组, 值, 名称)
    ("普通话 · 女声", "zh-CN-XiaoxiaoNeural", "晓晓 · 自然亲切"),
    ("普通话 · 女声", "zh-CN-XiaoyiNeural", "晓伊 · 温柔"),
    ("普通话 · 女声", "zh-CN-XiaochenNeural", "晓辰 · 知性"),
    ("普通话 · 女声", "zh-CN-XiaohanNeural", "晓涵 · 沉稳"),
    ("普通话 · 女声", "zh-CN-XiaomengNeural", "晓梦 · 活泼"),
    ("普通话 · 女声", "zh-CN-XiaomoNeural", "晓墨 · 情感丰富"),
    ("普通话 · 女声", "zh-CN-XiaoruiNeural", "晓睿 · 大气"),
    ("普通话 · 女声", "zh-CN-XiaoxuanNeural", "晓萱 · 干练"),
    ("普通话 · 女声", "zh-CN-XiaoyanNeural", "晓颜 · 柔美"),
    ("普通话 · 男声", "zh-CN-YunxiNeural", "云希 · 阳光少年"),
    ("普通话 · 男声", "zh-CN-YunjianNeural", "云健 · 播音解说"),
    ("普通话 · 男声", "zh-CN-YunyangNeural", "云扬 · 新闻播报"),
    ("普通话 · 男声", "zh-CN-YunxiaNeural", "云夏 · 少年音"),
    ("普通话 · 男声", "zh-CN-YunzeNeural", "云泽 · 成熟稳重"),
    ("方言 · 港台", "zh-HK-HiuMaanNeural", "晓曼 · 粤语女声"),
    ("方言 · 港台", "zh-HK-WanLungNeural", "云龙 · 粤语男声"),
    ("方言 · 港台", "zh-TW-HsiaoChenNeural", "晓臻 · 台湾腔女声"),
    ("方言 · 东北", "zh-CN-liaoning-XiaobeiNeural", "晓北 · 东北话女声"),
    ("方言 · 陕西", "zh-CN-shaanxi-XiaoniNeural", "晓妮 · 陕西话女声"),
    ("多语言", "en-US-AvaMultilingualNeural", "Ava · 多语言女声"),
    ("多语言", "en-US-AndrewMultilingualNeural", "Andrew · 多语言男声"),
]

AUDIO_TTL = 3600


async def synthesize(text: str, voice: str | None = None) -> dict:
    import edge_tts
    cfg = load_config()
    voice = voice or cfg.get("tts_voice") or VOICES[0][1]
    text = (text or "").strip()
    if not text:
        raise ValueError("文本为空")
    text = text[:2000]
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.mp3"
    path = AUDIO_DIR / name
    communicate = edge_tts.Communicate(text, voice=voice)
    await asyncio.wait_for(communicate.save(str(path)), timeout=30)
    size = path.stat().st_size
    if size < 1024:
        path.unlink(missing_ok=True)
        raise RuntimeError("合成结果异常（空文件）")
    duration = 0.0
    try:
        import mutagen.mp3
        duration = float(mutagen.mp3.MP3(str(path)).info.length)
    except Exception:
        duration = round(size / 24000, 1)
    _cleanup()
    return {"file": name, "url": f"/api/tts/audio/{name}", "duration": round(duration, 2),
            "voice": voice, "bytes": size}


def _cleanup() -> None:
    now = time.time()
    for p in AUDIO_DIR.glob("*.mp3"):
        try:
            if now - p.stat().st_mtime > AUDIO_TTL:
                p.unlink()
        except Exception:
            pass


def audio_path(name: str) -> Path | None:
    if not name.endswith(".mp3") or "/" in name or "\\" in name:
        return None
    p = AUDIO_DIR / name
    return p if p.exists() else None
