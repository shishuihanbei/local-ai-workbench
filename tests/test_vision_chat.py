"""图片直传视觉模型：命名识别、压缩、消息 content parts、历史图片预算。"""
from __future__ import annotations

import asyncio
import base64
import io

from PIL import Image


def _png(w: int = 2400, h: int = 1200) -> bytes:
    im = Image.new("RGB", (w, h), "white")
    for x in range(0, w, 80):
        im.paste((20, 40, 120), (x, 0, x + 40, h))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_vision_model_names():
    from backend.services.platform_models import is_vision_model

    yes = [
        "qwen2.5vl:3b", "qwen3-vl-8b", "llava-v1.6-7b", "minicpm-v-2.6",
        "internvl2-8b", "pixtral-12b", "moondream2", "llama-3.2-vision:11b",
        "phi-4-multimodal-instruct", "gemma3:4b", "smolvlm-500m", "ovis2-8b",
    ]
    no = [
        "deepseek-r1:7b", "qwen2.5:0.5b", "text-embedding-nomic", "gemma3:1b",
        "llama-3.2-3b-instruct", "qwen2.5-7b-instruct",
    ]
    for name in yes:
        assert is_vision_model(name), name
    for name in no:
        assert not is_vision_model(name), name


def test_image_data_url_stays_small_and_jpeg():
    from backend.services.attachments import VISION_MAX_SIDE, image_data_url

    url = image_data_url(_png())
    assert url.startswith("data:image/jpeg;base64,")
    raw = base64.b64decode(url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw))
    assert img.format == "JPEG"
    assert max(img.size) <= VISION_MAX_SIDE
    assert len(raw) < 3 * 1024 * 1024


def test_context_block_can_skip_image_ocr():
    from backend.services import attachments

    rows = [
        {"name": "shot.png", "kind": "image", "text_content": "截图 OCR 文字"},
        {"name": "note.txt", "kind": "text", "text_content": "文档正文"},
    ]
    assert "截图 OCR 文字" in attachments.context_block(rows)
    block = attachments.context_block(rows, skip_images=True)
    assert "截图 OCR 文字" not in block
    assert "文档正文" in block


def test_context_block_skips_only_converted_images():
    from backend.services import attachments

    rows = [
        {"id": 1, "name": "a.png", "kind": "image", "text_content": "第一张 OCR"},
        {"id": 2, "name": "b.png", "kind": "image", "text_content": "第二张 OCR"},
        {"id": 3, "name": "c.png", "kind": "image", "text_content": "第五张 OCR"},
    ]
    block = attachments.context_block(rows, skip_image_ids={1, 2})
    assert "第一张 OCR" not in block
    assert "第二张 OCR" not in block
    assert "第五张 OCR" in block


def test_build_context_sends_current_image_parts(monkeypatch):
    from backend.routers import chat

    called = {}

    def fake_context(rows, skip_images=False, skip_image_ids=None):
        called["skip_images"] = skip_images
        called["skip_ids"] = skip_image_ids
        return "" if skip_image_ids else "文档 OCR"

    async def fake_images(rows, max_images=4):
        if not rows:
            return [], []
        return [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}], [1]

    async def fake_memory(user_id, message):
        return {}

    monkeypatch.setattr(chat.attachments, "context_block", fake_context)
    monkeypatch.setattr(chat.attachments, "vision_payload", fake_images)
    monkeypatch.setattr(chat.memory, "context", fake_memory)
    body = chat.ChatBody(model="qwen2.5vl:3b", message="看图",
                         attachments=[1], vision=True)
    msgs, _, meta = asyncio.run(chat._build_context(
        {"id": 1}, body, {}, att_rows=[
            {"id": 1, "name": "shot.png", "kind": "image", "size": 100}]
    ))
    user = msgs[-1]
    assert user["role"] == "user"
    assert isinstance(user["content"], list)
    assert user["content"][0] == {"type": "text", "text": "看图"}
    assert user["content"][1]["type"] == "image_url"
    assert called["skip_ids"] == {1}
    assert meta["vision_images"] == 1


def test_build_context_text_model_keeps_ocr(monkeypatch):
    from backend.routers import chat

    called = {}

    def fake_context(rows, skip_images=False, skip_image_ids=None):
        called["skip_images"] = skip_images
        return "【附件：shot.png】\n截图里的字"

    async def fake_memory(user_id, message):
        return {}

    monkeypatch.setattr(chat.attachments, "context_block", fake_context)
    monkeypatch.setattr(chat.memory, "context", fake_memory)
    body = chat.ChatBody(model="deepseek-r1:7b", message="看图",
                         attachments=[1], vision=False)
    msgs, _, _ = asyncio.run(chat._build_context(
        {"id": 1}, body, {}, att_rows=[
            {"id": 1, "name": "shot.png", "kind": "image", "size": 100}]
    ))
    user = msgs[-1]
    assert isinstance(user["content"], str)
    assert "截图里的字" in user["content"]
    assert called["skip_images"] is False


def test_history_replays_limited_images(monkeypatch):
    from backend.routers import chat

    async def fake_fetch_all(sql, params=()):
        return [
            {"role": "user", "content": "第一张", "meta": '{"attachments":[{"id":1}]}'},
            {"role": "assistant", "content": "收到", "meta": ""},
            {"role": "user", "content": "第二张", "meta": '{"attachments":[{"id":2}]}'},
            {"role": "assistant", "content": "收到", "meta": ""},
            {"role": "user", "content": "第三张", "meta": '{"attachments":[{"id":3}]}'},
        ]

    async def fake_images(rows, max_images=4):
        if not rows:
            return [], []
        return [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}], [int(rows[0]["id"])]

    async def fake_memory(user_id, message):
        return {}

    async def fake_load_many(uid, ids):
        if not ids:
            return []
        return [{"id": int(ids[0]), "name": "x.png", "kind": "image", "size": 10}]

    monkeypatch.setattr(chat, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(chat.attachments, "vision_payload", fake_images)
    monkeypatch.setattr(chat.attachments, "load_many", fake_load_many)
    monkeypatch.setattr(chat.memory, "context", fake_memory)
    body = chat.ChatBody(model="qwen2.5vl:3b", message="接着说",
                         conversation_id=7, vision=True)
    msgs, _, _ = asyncio.run(chat._build_context({"id": 1}, body, {}))
    image_msgs = [m for m in msgs if isinstance(m["content"], list)]
    assert len(image_msgs) == 2


def test_frontend_has_vision_switch_and_preview():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "frontend"
    models_js = (root / "models.js").read_text(encoding="utf-8")
    gen_js = (root / "generation.js").read_text(encoding="utf-8")
    att_js = (root / "attachments.js").read_text(encoding="utf-8")
    msg_js = (root / "messages.js").read_text(encoding="utf-8")
    assert '"text", "code", "vision"' in models_js.replace("'", '"')
    assert "vision: !!model.vision" in gen_js
    assert "preferVisionModel" in att_js
    assert "attachVisionHint" in att_js
    assert "msg-images" in msg_js
    assert "openImagePreview" in msg_js
