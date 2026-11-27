"""聊天附件：安全落盘、正文提取、上下文拼接，以及视觉模型的图片输入。"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import UPLOAD_DIR
from ..db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)

MAX_BYTES = 20 * 1024 * 1024
MAX_TEXT = 60000
MAX_CONTEXT = 20000
OCR_MAX_PAGES = 15
OCR_MAX_IMAGES = 8
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff"}
TEXT_EXTS = {
    "txt", "md", "markdown", "csv", "json", "log", "py", "js", "ts", "tsx", "jsx",
    "html", "htm", "css", "xml", "yaml", "yml", "ini", "conf", "sql", "sh", "bat", "ps1",
}
DOC_EXTS = {"pdf", "docx", "xlsx", "xlsm", "xls", "pptx"}

# 视觉模型只看图，不需要 OCR；原图先缩到长边 1600，再压成 JPEG，兼顾截图文字和请求体积。
VISION_MAX_IMAGES = 4
VISION_MAX_SIDE = 1600
VISION_JPEG_QUALITY = 86
VISION_MAX_BYTES = 3 * 1024 * 1024

_OCR_ENGINE = None
_OCR_LOCK = threading.Lock()


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return ""


def _run_ocr(arr) -> str:
    global _OCR_ENGINE
    with _OCR_LOCK:
        if _OCR_ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR_ENGINE = RapidOCR()
        try:
            result, _ = _OCR_ENGINE(arr)
        except Exception as e:
            log.warning("OCR 执行失败: %s", e)
            return ""
    lines = []
    for item in result or []:
        if len(item) < 2:
            continue
        text = str(item[1]).strip()
        score = float(item[2]) if len(item) > 2 else 1.0
        if text and score >= 0.45:
            lines.append(text)
    return "\n".join(lines)


def _image_array(raw: bytes):
    from PIL import Image, ImageOps
    import numpy as np
    Image.MAX_IMAGE_PIXELS = 60_000_000
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)
    img = img.convert("RGB")
    if max(img.size) > 2200:
        img.thumbnail((2200, 2200), Image.Resampling.LANCZOS)
    return np.asarray(img)


def _ocr_image_text(raw: bytes) -> str:
    try:
        return _run_ocr(_image_array(raw))
    except Exception as e:
        log.warning("图片 OCR 失败: %s", e)
        return ""


def image_data_url(raw: bytes) -> str:
    """把已落盘的图片压成视觉模型能直接吃的数据 URL。

    优先保证截图里的文字可读：长边最多 1600，JPEG 质量 86；
    超过 3MB 时再降一档，避免一条消息带 4 张图把请求撑爆。
    """
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 60_000_000
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    if getattr(img, "n_frames", 1) > 1:
        img.seek(0)
    if img.mode in ("RGBA", "LA", "P"):
        base = Image.new("RGB", img.size, (255, 255, 255))
        base.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = base
    else:
        img = img.convert("RGB")
    if max(img.size) > VISION_MAX_SIDE:
        img.thumbnail((VISION_MAX_SIDE, VISION_MAX_SIDE), Image.Resampling.LANCZOS)
    quality = VISION_JPEG_QUALITY
    while True:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= VISION_MAX_BYTES or quality <= 60:
            break
        quality -= 8
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


async def vision_payload(rows: list[dict[str, Any]], max_images: int = VISION_MAX_IMAGES
                         ) -> tuple[list[dict], list[int]]:
    """转图并返回 (内容块, 已成功转成图片的附件 id)。

    id 用来告诉 context_block 只跳过这些图的 OCR；转图失败的图仍保留 OCR，
    避免第 5 张图或坏图被彻底丢掉。
    """
    parts: list[dict] = []
    used_ids: list[int] = []
    for row in rows:
        if len(parts) >= max_images:
            break
        if row.get("kind") != "image":
            continue
        stored = str(row.get("stored_name") or "")
        if not stored:
            continue
        path = UPLOAD_DIR / stored
        if not path.exists():
            continue
        try:
            raw = await asyncio.to_thread(path.read_bytes)
            url = await asyncio.to_thread(image_data_url, raw)
        except Exception as e:
            log.warning("图片转视觉输入失败 %s: %s", row.get("name"), e)
            continue
        parts.append({"type": "image_url", "image_url": {"url": url}})
        if row.get("id") is not None:
            used_ids.append(int(row["id"]))
    return parts, used_ids


async def vision_images(rows: list[dict[str, Any]], max_images: int = VISION_MAX_IMAGES) -> list[dict]:
    """把图片附件转成 OpenAI 兼容的 image_url 内容块；读不到就跳过。"""
    return (await vision_payload(rows, max_images))[0]


def _pdf_text(raw: bytes) -> tuple[str, int]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return "", 0
    pages = reader.pages
    parts = []
    for page in pages[:120]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts), len(pages)


def _ocr_pdf(raw: bytes) -> str:
    import pymupdf
    from PIL import Image
    import numpy as np
    doc = pymupdf.open(stream=raw, filetype="pdf")
    parts = []
    try:
        for idx in range(min(doc.page_count, OCR_MAX_PAGES)):
            try:
                page = doc[idx]
                pix = page.get_pixmap(dpi=160, colorspace=pymupdf.csRGB, alpha=False)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                if pix.n != 3:
                    arr = arr[:, :, :3]
                text = _run_ocr(arr)
                if text:
                    parts.append(text)
            except Exception as e:
                log.warning("扫描 PDF 第 %s 页 OCR 失败: %s", idx + 1, e)
    finally:
        doc.close()
    return "\n\n".join(parts)


def _docx_text(raw: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(raw))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    seen = set()
    images = 0
    for rel in doc.part.related_parts.values():
        ctype = str(getattr(rel, "content_type", "") or "")
        if not ctype.startswith("image/"):
            continue
        key = str(getattr(rel, "partname", ""))
        if key in seen:
            continue
        seen.add(key)
        blob = getattr(rel, "blob", b"")
        if not blob:
            continue
        text = _ocr_image_text(blob)
        if text:
            parts.append(f"[文档图片文字]\n{text}")
            images += 1
        if images >= OCR_MAX_IMAGES:
            break
    return "\n".join(parts)


def _xlsx_text(raw: bytes) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    parts = []
    used = 0
    try:
        for ws in wb.worksheets:
            head = f"# {ws.title}"
            parts.append(head)
            used += len(head)
            for row in ws.iter_rows(values_only=True):
                cells = [str(v) for v in row if v is not None]
                if not cells:
                    continue
                line = " | ".join(cells)
                parts.append(line)
                used += len(line) + 1
                if used >= MAX_TEXT:
                    return "\n".join(parts)
    finally:
        wb.close()
    return "\n".join(parts)


def _xls_text(raw: bytes) -> str:
    import xlrd
    book = xlrd.open_workbook(file_contents=raw)
    parts = []
    used = 0
    for sheet in book.sheets():
        head = f"# {sheet.name}"
        parts.append(head)
        used += len(head)
        for row in range(sheet.nrows):
            cells = [str(v) for v in sheet.row_values(row) if str(v).strip()]
            if not cells:
                continue
            line = " | ".join(cells)
            parts.append(line)
            used += len(line) + 1
            if used >= MAX_TEXT:
                return "\n".join(parts)
    return "\n".join(parts)


def _pptx_text(raw: bytes) -> str:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    prs = Presentation(io.BytesIO(raw))
    parts = []
    images = 0
    for idx, slide in enumerate(prs.slides, 1):
        parts.append(f"# 幻灯片 {idx}")
        for shape in slide.shapes:
            text = str(getattr(shape, "text", "") or "").strip()
            if text:
                parts.append(text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
            if getattr(shape, "shape_type", None) == MSO_SHAPE_TYPE.PICTURE:
                try:
                    blob = shape.image.blob
                except Exception:
                    blob = b""
                if blob and images < OCR_MAX_IMAGES:
                    ocr = _ocr_image_text(blob)
                    if ocr:
                        parts.append(f"[幻灯片图片文字]\n{ocr}")
                        images += 1
        try:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append("[备注]\n" + notes)
        except Exception:
            pass
    return "\n".join(parts)


def extract_text(name: str, suffix: str, raw: bytes) -> str:
    if suffix in IMAGE_EXTS:
        text = _ocr_image_text(raw)
        return re.sub(r"\r\n?", "\n", text or "").strip()[:MAX_TEXT]
    try:
        if suffix == "pdf":
            text, page_count = _pdf_text(raw)
            if page_count and len(text.strip()) < min(4000, page_count * 40):
                try:
                    ocr = _ocr_pdf(raw)
                except Exception as e:
                    log.warning("扫描 PDF OCR 跳过: %s", e)
                    ocr = ""
                if ocr:
                    text = (text + "\n\n" + ocr).strip()
        elif suffix == "docx":
            text = _docx_text(raw)
        elif suffix in ("xlsx", "xlsm"):
            text = _xlsx_text(raw)
        elif suffix == "xls":
            text = _xls_text(raw)
        elif suffix == "pptx":
            text = _pptx_text(raw)
        else:
            text = _decode(raw)
    except Exception as e:
        log.warning("文件解析失败 %s: %s", suffix, e)
        text = "" if suffix in DOC_EXTS else _decode(raw)
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    return text[:MAX_TEXT]


def kind_of(suffix: str) -> str:
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in DOC_EXTS:
        return "document"
    if suffix in TEXT_EXTS:
        return "text"
    return "file"


def supported(suffix: str) -> bool:
    return suffix in IMAGE_EXTS or suffix in TEXT_EXTS or suffix in DOC_EXTS


def public(row: dict[str, Any]) -> dict[str, Any]:
    text = str(row.get("text_content") or "")
    return {
        "id": int(row["id"]),
        "name": row.get("name") or "未命名",
        "mime": row.get("mime") or "",
        "size": int(row.get("size") or 0),
        "kind": row.get("kind") or "file",
        "chars": len(text),
        "preview": text[:180].replace("\n", " "),
        "parsed_at": float(row.get("parsed_at") or 0),
        "parse_ms": int(row.get("parse_ms") or 0),
        "parse_error": row.get("parse_error") or "",
        "url": f"/api/chat/files/{int(row['id'])}",
    }


def engine_status() -> dict[str, Any]:
    import importlib.util
    return {
        "engine": "RapidOCR",
        "installed": importlib.util.find_spec("rapidocr_onnxruntime") is not None,
        "pdf_pages": OCR_MAX_PAGES,
        "doc_images": OCR_MAX_IMAGES,
        "max_bytes": MAX_BYTES,
        "max_chars": MAX_TEXT,
        "images": sorted(IMAGE_EXTS),
        "docs": sorted(DOC_EXTS),
    }


async def save(user_id: int, filename: str, mime: str, raw: bytes) -> dict[str, Any]:
    name = Path(filename or "未命名").name[:180] or "未命名"
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
    if not supported(suffix):
        raise ValueError(f"暂不支持 .{suffix} 文件")
    if len(raw) > MAX_BYTES:
        raise ValueError("文件过大，单文件上限 20MB")
    started = time.time()
    text = await asyncio.to_thread(extract_text, name, suffix, raw)
    parse_ms = int((time.time() - started) * 1000)
    parse_error = "" if (text or "").strip() else "未提取到正文，可检查文件是否扫描版或图片是否清晰"
    stored = f"{user_id}-{uuid.uuid4().hex}.{suffix}"
    path = UPLOAD_DIR / stored
    path.write_bytes(raw)
    row_id = await execute(
        "INSERT INTO uploads(user_id,name,stored_name,mime,size,kind,text_content,created_at,"
        "parsed_at,parse_ms,parse_error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, name, stored, mime or "", len(raw), kind_of(suffix), text, time.time(),
         time.time(), parse_ms, parse_error))
    row = await fetch_one("SELECT * FROM uploads WHERE id=?", (row_id,))
    return public(row or {})


async def reparse(row: dict[str, Any]) -> dict[str, Any]:
    """重新读取已落盘的原件并提取正文；扫描件会重新走 OCR。"""
    name = str(row.get("name") or "未命名")
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else "txt"
    stored = str(row.get("stored_name") or "")
    path = UPLOAD_DIR / stored if stored else None
    started = time.time()
    if not path or not path.exists():
        error = "原文件已丢失，无法重新解析"
        await execute(
            "UPDATE uploads SET parsed_at=?,parse_ms=?,parse_error=? WHERE id=?",
            (time.time(), 0, error, int(row["id"])))
        return {"id": int(row["id"]), "ok": False, "chars": 0, "ms": 0, "error": error}
    fatal = False
    try:
        raw = await asyncio.to_thread(path.read_bytes)
        text = await asyncio.to_thread(extract_text, name, suffix, raw)
        error = "" if (text or "").strip() else "未提取到正文，可检查是否扫描件或图片是否清晰"
    except Exception as e:
        text = ""
        error = f"解析失败：{str(e)[:160]}"
        fatal = True
    cost = int((time.time() - started) * 1000)
    await execute(
        "UPDATE uploads SET text_content=?,parsed_at=?,parse_ms=?,parse_error=? WHERE id=?",
        ((text or "")[:MAX_TEXT], time.time(), cost, error, int(row["id"])))
    return {"id": int(row["id"]), "ok": not fatal, "chars": len((text or "").strip()),
            "ms": cost, "error": error}



async def get(user_id: int, file_id: int) -> dict[str, Any] | None:
    return await fetch_one(
        "SELECT * FROM uploads WHERE id=? AND user_id=?", (file_id, user_id))


async def load_many(user_id: int, ids: list[int]) -> list[dict[str, Any]]:
    clean = []
    for x in ids[:8]:
        try:
            n = int(x)
        except Exception:
            continue
        if n and n not in clean:
            clean.append(n)
    if not clean:
        return []
    placeholders = ",".join("?" for _ in clean)
    return await fetch_all(
        f"SELECT * FROM uploads WHERE user_id=? AND id IN ({placeholders}) ORDER BY id",
        (user_id, *clean))


def context_block(rows: list[dict[str, Any]], skip_images: bool = False,
                  skip_image_ids: set[int] | None = None) -> str:
    parts = []
    used = 0
    skip_ids = skip_image_ids or set()
    for row in rows:
        if row.get("kind") == "image" and (skip_images or int(row.get("id") or -1) in skip_ids):
            continue
        header = f"【附件：{row.get('name') or '未命名'}】"
        text = str(row.get("text_content") or "").strip()
        if text:
            body = text[:12000]
        elif row.get("kind") == "image":
            body = "（图片附件，已保存；未识别到可用文字。）"
        else:
            body = "（文件已上传，但未能提取正文。）"
        piece = header + "\n" + body
        if used + len(piece) > MAX_CONTEXT:
            break
        parts.append(piece)
        used += len(piece)
    return "\n\n".join(parts)


async def delete(user_id: int, file_id: int) -> bool:
    row = await get(user_id, file_id)
    if not row:
        return False
    path = UPLOAD_DIR / str(row["stored_name"])
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass
    await execute("DELETE FROM uploads WHERE id=?", (file_id,))
    return True
