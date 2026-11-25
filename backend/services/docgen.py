"""把模型输出的 Markdown 排成可下载的 Word / Excel / PPT / PDF / 文本文件。

生成结果保存在 data/exports，数据库只记录索引；下载走 /api/files/generated/{id}。
"""
from __future__ import annotations

import asyncio
import html
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import EXPORT_DIR
from ..db import execute, fetch_all
from . import retention

FORMATS: dict[str, dict[str, str]] = {
    "docx": {"label": "Word 文档", "ext": "docx", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "short": "W"},
    "xlsx": {"label": "Excel 表格", "ext": "xlsx", "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "short": "X"},
    "pptx": {"label": "PPT 演示文稿", "ext": "pptx", "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "short": "P"},
    "pdf": {"label": "PDF 文档", "ext": "pdf", "mime": "application/pdf", "short": "PDF"},
    "md": {"label": "Markdown 文档", "ext": "md", "mime": "text/markdown; charset=utf-8", "short": "MD"},
    "txt": {"label": "纯文本", "ext": "txt", "mime": "text/plain; charset=utf-8", "short": "TXT"},
}
ALIASES = {
    "word": "docx", "doc": "docx", "docx": "docx",
    "excel": "xlsx", "xls": "xlsx", "xlsx": "xlsx", "csv": "xlsx",
    "ppt": "pptx", "pptx": "pptx", "slides": "pptx",
    "pdf": "pdf", "md": "md", "markdown": "md", "txt": "txt", "text": "txt",
}
DETECT_ACTION = re.compile(r"(写|生成|做|制作|整理|输出|导出|上传|下载|排版|给我|帮我|来一份|出一份|转成|转换成|保存为)")
DETECT = [
    (re.compile(r"(?i)word|docx|\.doc(?:$|\W)"), "docx"),
    (re.compile(r"(?i)excel|xlsx|csv|电子表格|表格文件"), "xlsx"),
    (re.compile(r"(?i)\bppt\b|pptx|幻灯片|演示文稿|slides?"), "pptx"),
    (re.compile(r"(?i)pdf"), "pdf"),
    (re.compile(r"(?i)markdown|\.md(?:$|\W)"), "md"),
    (re.compile(r"(?i)纯文本|txt文件|\.txt(?:$|\W)"), "txt"),
]


def normalize_format(value: str | None) -> str | None:
    key = str(value or "").strip().lower().lstrip(".")
    return ALIASES.get(key)


def detect_format(text: str) -> str | None:
    value = str(text or "")
    if not DETECT_ACTION.search(value):
        return None
    for pattern, fmt in DETECT:
        if pattern.search(value):
            return fmt
    return None


def resolve_format(value: str | None, message: str) -> str | None:
    return normalize_format(value) or detect_format(message)


def label(fmt: str) -> str:
    return FORMATS.get(fmt, FORMATS["docx"])["label"]


def default_prompt_hint(fmt: str) -> str:
    common = (
        "这次要直接生成可下载文件，不是在聊天里贴正文。请只输出适合排版的文档内容，"
        "不要寒暄、不要说明“我可以帮你生成”、不要提文件操作，也不要用一个代码块包住整篇文档。"
        "内容必须完整、事实准确；不确定的信息标明“待核实”，不要编造政策、数据、图片或参考文献。"
    )
    if fmt == "docx":
        return common + (
            "用 Markdown 组织：第一行用 `# 文档标题`；正文用 `##`、`###` 分章节；"
            "要点用 `-`；对比或清单用 Markdown 表格；代码或示例用带语言标记的代码块。"
            "段落之间空一行。不要输出目录页码占位符，不要引用无法提供的图片。"
        )
    if fmt == "xlsx":
        return common + (
            "输出一个或多个 Markdown 表格：第一行是字段名，第二行是 `|---|---|` 分隔线，"
            "后面每行一条数据。表格前可用 `## 工作表名` 指定工作表。"
            "不要在表格外写大段说明；数字保持纯数字，单位和备注单独成列。"
        )
    if fmt == "pptx":
        return common + (
            "按幻灯片组织：第一行 `# 演示标题`；每页用 `## 页面标题`；页面内容用 `-` 短句，"
            "每页 3–6 条，每条不超过 40 字。需要对比时用 Markdown 表格。"
            "不要写大段连续文字，不要超过 12 页。"
        )
    if fmt == "pdf":
        return common + (
            "用 Markdown 组织成适合 A4 阅读的文档：`#` 标题、`##` 章节、短段落、列表和表格。"
            "避免超宽表格；代码用带语言标记的代码块。"
        )
    if fmt == "md":
        return common + "直接输出结构清晰的 Markdown 原文，保留标题、列表、表格和代码块。"
    return common + "直接输出结构清晰的纯文本，使用短段落、编号和分节标题，不使用 Markdown 符号。"


def prompt_hint(fmt: str) -> str:
    from . import prompts
    return prompts.get(f"format.{fmt}", default_prompt_hint(fmt))


@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    lang: str = ""
    ordered: bool = False
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


CJK = re.compile(r"[\u3400-\u9fff]")


def _join_lines(lines: list[str]) -> str:
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
        elif CJK.search(out[-1]) or CJK.search(line[0]):
            out += line
        else:
            out += " " + line
    return out


def _clean_inline(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_~`]+", "", text)
    return text.strip()


def parse_markdown(md: str) -> list[Block]:
    text = str(md or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    lines = text.split("\n")
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line.startswith("```"):
            lang = line[3:].strip().split()[0] if line[3:].strip() else ""
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(Block("code", "\n".join(buf).rstrip(), lang=lang))
            continue
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        if heading:
            blocks.append(Block("heading", heading.group(2).strip(), level=len(heading.group(1))))
            i += 1
            continue
        if re.match(r"^\s*(?:---+|___+|\*\*\*+)\s*$", line):
            blocks.append(Block("hr"))
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and re.match(
                r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$", lines[i + 1]):
            header = _split_row(line)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append(Block("table", rows=[header] + rows))
            continue
        if re.match(r"^\s*[-*+]\s+", line):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*+]\s+", "", lines[i]).strip())
                i += 1
            blocks.append(Block("list", items=items, ordered=False))
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]).strip())
                i += 1
            blocks.append(Block("list", items=items, ordered=True))
            continue
        if line.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            blocks.append(Block("quote", _join_lines(quote)))
            continue
        para: list[str] = []
        while i < len(lines):
            nxt = lines[i]
            if not nxt.strip():
                break
            if nxt.lstrip().startswith("```") or re.match(r"^#{1,4}\s+", nxt):
                break
            if re.match(r"^\s*(?:[-*+]\s+|\d+\.\s+|>|(?:---+|___+|\*\*\*+)\s*$)", nxt):
                break
            if "|" in nxt and i + 1 < len(lines) and re.match(
                    r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?\s*$", lines[i + 1]):
                break
            para.append(nxt)
            i += 1
        if para:
            blocks.append(Block("p", _join_lines(para)))
        else:
            i += 1
    return blocks


def _split_row(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [cell.strip() for cell in line.split("|")]


def title_from(markdown: str, fmt: str = "docx") -> str:
    for line in str(markdown or "").splitlines():
        m = re.match(r"^#{1,2}\s+(.+)$", line.strip())
        if m:
            title = _clean_inline(m.group(1))
            if title:
                return title[:80]
    for block in parse_markdown(markdown):
        if block.kind == "p" and block.text:
            return block.text[:80]
    return f"AI 生成{label(fmt)}"


def _filename(title: str, ext: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title or "").strip(" .")
    clean = re.sub(r"(?i)\.(docx?|xlsx?|pptx?|pdf|md|txt)$", "", clean).strip(" .")
    clean = re.sub(r"\s+", " ", clean)[:80]
    return f"{clean or 'AI生成文档'}.{ext}"


async def build(user_id: int, conversation_id: int | None, markdown: str,
                fmt: str, message_id: int = 0) -> dict[str, Any]:
    fmt = normalize_format(fmt) or "docx"
    title = title_from(markdown, fmt)
    fname = _filename(title, FORMATS[fmt]["ext"])
    stored = f"{uuid.uuid4().hex}.{FORMATS[fmt]['ext']}"
    path = EXPORT_DIR / stored
    await asyncio.to_thread(_render_file, fmt, path, title, markdown)
    size = path.stat().st_size if path.exists() else 0
    created = time.time()
    expires = retention.expires_at(created)
    file_id = await execute(
        "INSERT INTO generated_files(user_id,conversation_id,message_id,name,stored_name,mime,size,kind,"
        "created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, conversation_id, message_id or None, fname, stored,
         FORMATS[fmt]["mime"], size, fmt, created, expires))
    return public(file_id, fname, size, fmt, expires)


def public(file_id: int, name: str, size: int, fmt: str, expires: float = 0) -> dict[str, Any]:
    data = {
        "id": file_id,
        "name": name,
        "size": size,
        "kind": fmt,
        "label": label(fmt),
        "mime": FORMATS[fmt]["mime"],
        "short": FORMATS[fmt]["short"],
        "url": f"/api/files/generated/{file_id}",
    }
    data.update(retention.expiry_fields(expires))
    return data


def decorate_row(row: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """给工作台概览里的文件行补上到期和清理状态。"""
    row.update(retention.expiry_fields(row.get("expires_at"), row.get("deleted_at") or 0, now))
    return row


async def enrich_file_list(files: list[dict[str, Any]], user_id: int | None = None,
                           now: float | None = None) -> list[dict[str, Any]]:
    """消息里的文件对象可能是旧的，读取时按数据库最新状态补到期/清理字段。"""
    ids: list[int] = []
    for item in files:
        try:
            file_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            file_id = 0
        if file_id and file_id not in ids:
            ids.append(file_id)
    if not ids:
        return files
    placeholders = ",".join("?" for _ in ids)
    sql = ("SELECT id,expires_at,deleted_at FROM generated_files "
           f"WHERE id IN ({placeholders})")
    params: list[Any] = list(ids)
    if user_id is not None:
        sql += " AND user_id=?"
        params.append(int(user_id))
    rows = await fetch_all(sql, params)
    by_id = {int(r["id"]): r for r in rows}
    now = time.time() if now is None else float(now)
    for item in files:
        try:
            file_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            continue
        row = by_id.get(file_id)
        if row:
            item.update(retention.expiry_fields(row.get("expires_at"),
                                                row.get("deleted_at") or 0, now))
        else:
            item.update(retention.expiry_fields(0, 0, now))
            item["expired"] = True
    return files


def summary(file: dict[str, Any]) -> str:
    return f"已生成{file['label']}《{file['name']}》，点击下方文件卡片可直接下载。"


def _render_file(fmt: str, path: Path, title: str, markdown: str) -> None:
    if fmt == "docx":
        _render_docx(path, title, markdown)
    elif fmt == "xlsx":
        _render_xlsx(path, title, markdown)
    elif fmt == "pptx":
        _render_pptx(path, title, markdown)
    elif fmt == "pdf":
        _render_pdf(path, title, markdown)
    elif fmt == "md":
        path.write_text(_clean_markdown_for_file(title, markdown), "utf-8")
    else:
        path.write_text(_plain_text(markdown), "utf-8")


def _clean_markdown_for_file(title: str, md: str) -> str:
    body = str(md or "").strip()
    if not body.startswith("#"):
        body = f"# {title}\n\n{body}"
    return body + "\n"


def _plain_text(md: str) -> str:
    out: list[str] = []
    for block in parse_markdown(md):
        if block.kind == "heading":
            out.append(f"{'  ' * (block.level - 1)}{_clean_inline(block.text)}")
            out.append("")
        elif block.kind == "p":
            out.append(_clean_inline(block.text))
            out.append("")
        elif block.kind == "list":
            for n, item in enumerate(block.items, 1):
                out.append(f"{n}. {_clean_inline(item)}" if block.ordered else f"• {_clean_inline(item)}")
            out.append("")
        elif block.kind == "quote":
            out.append(f"> {_clean_inline(block.text)}")
            out.append("")
        elif block.kind == "code":
            out.append(block.text)
            out.append("")
        elif block.kind == "table":
            for row in block.rows:
                out.append(" | ".join(_clean_inline(c) for c in row))
            out.append("")
    return "\n".join(out).strip() + "\n"


# ------------------------------------------------------------------ Word

def _set_font(run, name: str = "宋体", size: float = 12, bold: bool | None = None,
              italic: bool | None = None, color: str | None = None) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    run.font.name = name
    run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)


def _shade_run(run, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    rpr = run._element.get_or_add_rPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    rpr.append(shd)


def _shade_cell(cell, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _add_hyperlink(paragraph, url: str, text: str, size: float = 12) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    try:
        part = paragraph.part
        r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)
        new_run = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        color = OxmlElement("w:color")
        color.set(qn("w:val"), "4F6EF7")
        rPr.append(color)
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        rPr.append(u)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(int(size * 2)))
        rPr.append(sz)
        new_run.append(rPr)
        t = OxmlElement("w:t")
        t.text = text
        new_run.append(t)
        hyperlink.append(new_run)
        paragraph._p.append(hyperlink)
    except Exception:
        run = paragraph.add_run(text)
        _set_font(run, size=size, color="4F6EF7")


INLINE_RE = re.compile(r"(\*\*.+?\*\*|\*[^*\n]+?\*|`[^`\n]+`|\[[^\]]+\]\([^)]+\))")


def _add_inline(paragraph, text: str, size: float = 12, base_font: str = "宋体",
                color: str | None = None) -> None:
    pos = 0
    for m in INLINE_RE.finditer(str(text or "")):
        if m.start() > pos:
            run = paragraph.add_run(str(text)[pos:m.start()])
            _set_font(run, base_font, size, color=color)
        token = m.group(0)
        if token.startswith("**") and token.endswith("**"):
            run = paragraph.add_run(token[2:-2])
            _set_font(run, base_font, size, bold=True, color=color)
        elif token.startswith("`") and token.endswith("`"):
            run = paragraph.add_run(token[1:-1])
            _set_font(run, "Consolas", size - 1, color="1F2937")
            _shade_run(run, "F1F3F7")
        elif token.startswith("[") and "](" in token:
            label_text, url = token[1:-1].split("](", 1)
            _add_hyperlink(paragraph, url, label_text, size)
        elif token.startswith("*") and token.endswith("*"):
            run = paragraph.add_run(token[1:-1])
            _set_font(run, base_font, size, italic=True, color=color)
        pos = m.end()
    if pos < len(str(text or "")):
        run = paragraph.add_run(str(text)[pos:])
        _set_font(run, base_font, size, color=color)


def _bottom_border(paragraph, color: str = "D9DFEC") -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "6")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    pPr.append(borders)


def _add_page_number(paragraph) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = paragraph.add_run("第 ")
    _set_font(run, "宋体", 9, color="7A8294")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    paragraph._p.append(fld)
    run2 = paragraph.add_run(" 页")
    _set_font(run2, "宋体", 9, color="7A8294")


def _render_docx(path: Path, title: str, markdown: str) -> None:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.54)
    sec.bottom_margin = Cm(2.54)
    sec.left_margin = Cm(2.8)
    sec.right_margin = Cm(2.8)
    sec.header_distance = Cm(1.5)
    sec.footer_distance = Cm(1.5)

    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(0)

    # 页脚页码
    footer_p = sec.footer.paragraphs[0]
    footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number(footer_p)

    # 标题
    tp = doc.add_paragraph()
    tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tp.paragraph_format.space_before = Pt(6)
    tp.paragraph_format.space_after = Pt(18)
    _set_font(tp.add_run(title), "黑体", 22, bold=True, color="172033")

    blocks = parse_markdown(markdown)
    first_para = True
    for block in blocks:
        if block.kind == "heading":
            if block.level == 1 and _clean_inline(block.text) == title:
                continue
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14 if block.level <= 2 else 10)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.keep_with_next = True
            size = 16 if block.level == 1 else 14 if block.level == 2 else 13 if block.level == 3 else 12
            font = "黑体" if block.level <= 3 else "宋体"
            _set_font(p.add_run(_clean_inline(block.text)), font, size, bold=block.level >= 4)
            if block.level <= 2:
                _bottom_border(p)
        elif block.kind == "p":
            if first_para:
                first_para = False
                if len(block.text) < 180 and re.match(r"^(好的|当然|以下是|下面是|这是一份|根据你的要求)", block.text):
                    continue
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(24)
            p.paragraph_format.space_after = Pt(6)
            _add_inline(p, block.text)
        elif block.kind == "list":
            for n, item in enumerate(block.items, 1):
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Pt(24)
                p.paragraph_format.first_line_indent = Pt(-12)
                p.paragraph_format.space_after = Pt(3)
                prefix = f"{n}. " if block.ordered else "• "
                _set_font(p.add_run(prefix), "宋体", 12, color="4F6EF7")
                _add_inline(p, item)
        elif block.kind == "quote":
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(24)
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            _set_font(p.add_run("“"), "宋体", 12, color="4F6EF7")
            _add_inline(p, block.text, color="5A6478")
            _set_font(p.add_run("”"), "宋体", 12, color="4F6EF7")
        elif block.kind == "code":
            table = doc.add_table(rows=1, cols=1)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            cell = table.cell(0, 0)
            _shade_cell(cell, "F5F7FA")
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(4)
            lines = block.text.split("\n")
            run = p.add_run()
            _set_font(run, "Consolas", 9, color="1F2937")
            for idx, line in enumerate(lines):
                run.add_text(line)
                if idx < len(lines) - 1:
                    run.add_break()
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif block.kind == "table":
            if not block.rows:
                continue
            rows = block.rows
            cols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=cols)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = True
            for r, row in enumerate(rows):
                for c in range(cols):
                    cell = table.cell(r, c)
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    p = cell.paragraphs[0]
                    p.paragraph_format.line_spacing = 1.15
                    p.paragraph_format.space_before = Pt(2)
                    p.paragraph_format.space_after = Pt(2)
                    value = row[c] if c < len(row) else ""
                    _add_inline(p, value, size=10.5, base_font="宋体")
                    if r == 0:
                        _shade_cell(cell, "E8EEFF")
                        for run in p.runs:
                            run.font.bold = True
                            run.font.color.rgb = RGBColor.from_string("1E2A55")
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif block.kind == "hr":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            _bottom_border(p)

    doc.core_properties.title = title
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.save(str(path))


# ------------------------------------------------------------------ Excel

def _render_xlsx(path: Path, title: str, markdown: str) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    blocks = parse_markdown(markdown)
    tables: list[tuple[str, list[list[str]]]] = []
    last_heading = ""
    for block in blocks:
        if block.kind == "heading":
            last_heading = block.text
        elif block.kind == "table" and block.rows:
            tables.append((last_heading or f"表格{len(tables) + 1}", block.rows))
    if not tables:
        # 没有表格时按正文整理成单列，仍然保持可复制、可筛选。
        lines = []
        for block in blocks:
            if block.kind == "heading":
                lines.append(block.text)
            elif block.kind == "p":
                lines.append(block.text)
            elif block.kind == "list":
                lines.extend(block.items)
        tables.append((title, [["内容"], *[[x] for x in lines]]))

    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="4F6EF7")
    header_font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="微软雅黑", size=10.5, color="172033")
    stripe_fill = PatternFill("solid", fgColor="F5F7FD")
    thin = Side(style="thin", color="D9DFEC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    used_names: set[str] = set()
    for idx, (heading, rows) in enumerate(tables, 1):
        base = re.sub(r"[\[\]:*?/\\]", "", _clean_inline(heading) or f"表格{idx}")[:28] or f"表格{idx}"
        name = base
        n = 2
        while name in used_names:
            name = f"{base[:26]}_{n}"
            n += 1
        used_names.add(name)
        ws = wb.create_sheet(name)
        cols = max(len(r) for r in rows)
        # 标题行
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, cols))
        ws.cell(row=1, column=1, value=heading or title)
        ws.cell(row=1, column=1).font = Font(name="微软雅黑", size=14, bold=True, color="172033")
        ws.cell(row=1, column=1).alignment = Alignment(vertical="center")
        ws.row_dimensions[1].height = 28
        # 表头
        for c, value in enumerate(rows[0], 1):
            cell = ws.cell(row=2, column=c, value=_clean_inline(value))
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border
        ws.row_dimensions[2].height = 24
        for r, row in enumerate(rows[1:], 3):
            for c in range(1, cols + 1):
                raw = _clean_inline(row[c - 1]) if c - 1 < len(row) else ""
                value: Any = raw
                if re.fullmatch(r"-?\d+(?:\.\d+)?", str(raw).strip()):
                    value = float(raw) if "." in str(raw) else int(raw)
                cell = ws.cell(row=r, column=c, value=value)
                cell.font = body_font
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if r % 2 == 1:
                    cell.fill = stripe_fill
        for c in range(1, cols + 1):
            width = 10
            for r in range(2, min(len(rows) + 2, 80)):
                value = ws.cell(row=r, column=c).value
                s = str(value or "")
                width = max(width, min(42, sum(2 if CJK.search(ch) else 1 for ch in s) + 2))
            ws.column_dimensions[get_column_letter(c)].width = width
        ws.freeze_panes = "A3"
        ws.auto_filter.ref = f"A2:{get_column_letter(cols)}{len(rows) + 1}"
        ws.sheet_view.showGridLines = False
        if cols > 6:
            ws.page_setup.orientation = "landscape"
    wb.save(str(path))


# ------------------------------------------------------------------ PPT

def _render_pptx(path: Path, title: str, markdown: str) -> None:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    brand = RGBColor(0x4F, 0x6E, 0xF7)
    brand2 = RGBColor(0x7B, 0x61, 0xFF)
    ink = RGBColor(0x17, 0x20, 0x33)
    muted = RGBColor(0x6B, 0x75, 0x86)

    def add_cover(text: str) -> None:
        slide = prs.slides.add_slide(blank)
        bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0xF5, 0xF7, 0xFF)
        bg.line.fill.background()
        bar = slide.shapes.add_shape(1, 0, 0, Inches(0.22), prs.slide_height)
        bar.fill.solid()
        bar.fill.fore_color.rgb = brand
        bar.line.fill.background()
        box = slide.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(11.6), Inches(2.2))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = text
        p.font.name = "微软雅黑"
        p.font.size = Pt(40)
        p.font.bold = True
        p.font.color.rgb = ink
        accent = slide.shapes.add_shape(1, Inches(0.85), Inches(4.32), Inches(2.2), Inches(0.06))
        accent.fill.solid()
        accent.fill.fore_color.rgb = brand2
        accent.line.fill.background()

    def add_slide(heading: str, bullets: list[str], table: list[list[str]] | None = None) -> None:
        slide = prs.slides.add_slide(blank)
        top = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.12))
        top.fill.solid()
        top.fill.fore_color.rgb = brand
        top.line.fill.background()
        tb = slide.shapes.add_textbox(Inches(0.7), Inches(0.45), Inches(12), Inches(0.9))
        p = tb.text_frame.paragraphs[0]
        p.text = heading
        p.font.name = "微软雅黑"
        p.font.size = Pt(26)
        p.font.bold = True
        p.font.color.rgb = ink
        line = slide.shapes.add_shape(1, Inches(0.72), Inches(1.28), Inches(0.9), Inches(0.05))
        line.fill.solid()
        line.fill.fore_color.rgb = brand2
        line.line.fill.background()
        if table:
            rows = min(len(table), 9)
            cols = min(max(len(r) for r in table), 6)
            shape = slide.shapes.add_table(rows, cols, Inches(0.8), Inches(1.65), Inches(11.7), Inches(4.6))
            t = shape.table
            for r in range(rows):
                t.rows[r].height = Inches(0.42)
                for c in range(cols):
                    cell = t.cell(r, c)
                    cell.text = table[r][c] if c < len(table[r]) else ""
                    for para in cell.text_frame.paragraphs:
                        para.font.name = "微软雅黑"
                        para.font.size = Pt(12)
                        if r == 0:
                            para.font.bold = True
                            para.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            return
        box = slide.shapes.add_textbox(Inches(0.8), Inches(1.55), Inches(11.7), Inches(5.1))
        tf = box.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.TOP
        for i, text in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = "• " + text
            p.font.name = "微软雅黑"
            p.font.size = Pt(17)
            p.font.color.rgb = ink
            p.space_after = Pt(8)
            p.line_spacing = 1.25

    blocks = parse_markdown(markdown)
    deck_title = title
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for block in blocks:
        if block.kind == "heading" and block.level <= 2:
            if not sections and _clean_inline(block.text) == title.strip():
                deck_title = _clean_inline(block.text)
                continue
            current = {"title": _clean_inline(block.text), "bullets": [], "table": None}
            sections.append(current)
        elif block.kind in ("p", "list", "quote", "code"):
            if current is None:
                current = {"title": deck_title, "bullets": [], "table": None}
                sections.append(current)
            if block.kind == "list":
                current["bullets"].extend(_clean_inline(x) for x in block.items if x.strip())
            elif block.kind == "p" and block.text:
                current["bullets"].append(_clean_inline(block.text))
            elif block.kind == "quote" and block.text:
                current["bullets"].append("“" + _clean_inline(block.text) + "”")
            elif block.kind == "code" and block.text:
                current["bullets"].append(block.text.replace("\n", " / "))
        elif block.kind == "table" and current is not None:
            current["table"] = block.rows
    if not sections:
        sections = [{"title": deck_title, "bullets": [x for x in _plain_text(markdown).splitlines() if x.strip()][:8], "table": None}]
    add_cover(deck_title)
    for sec in sections:
        heading = sec["title"]
        bullets = sec["bullets"] or []
        table = sec["table"]
        if not bullets and not table:
            continue
        if table:
            add_slide(heading, [], table)
            continue
        chunks = [bullets[i:i + 7] for i in range(0, len(bullets), 7)] or [[]]
        for n, chunk in enumerate(chunks):
            add_slide(heading if n == 0 else heading + "（续）", chunk)

    # 页码
    for idx, slide in enumerate(prs.slides, 1):
        if idx == 1:
            continue
        box = slide.shapes.add_textbox(Inches(12.2), Inches(7.05), Inches(0.8), Inches(0.3))
        p = box.text_frame.paragraphs[0]
        p.text = str(idx)
        p.alignment = PP_ALIGN.RIGHT
        p.font.name = "Arial"
        p.font.size = Pt(10)
        p.font.color.rgb = muted
    prs.core_properties.title = deck_title
    prs.core_properties.author = ""
    prs.core_properties.last_modified_by = ""
    prs.save(str(path))


# ------------------------------------------------------------------ PDF

PDF_INLINE = re.compile(r"(\*\*.+?\*\*|\*[^*\n]+?\*|`[^`\n]+`|\[[^\]]+\]\([^)]+\))")


def _pdf_inline(text: str) -> str:
    escaped = html.escape(str(text or ""))
    out = []
    pos = 0
    for m in PDF_INLINE.finditer(escaped):
        out.append(escaped[pos:m.start()])
        token = m.group(0)
        if token.startswith("**") and token.endswith("**"):
            out.append(f"<b>{token[2:-2]}</b>")
        elif token.startswith("`") and token.endswith("`"):
            out.append(f"<code>{token[1:-1]}</code>")
        elif token.startswith("[") and "](" in token:
            label_text, url = token[1:-1].split("](", 1)
            out.append(f'<a href="{html.escape(url)}">{label_text}</a>')
        elif token.startswith("*") and token.endswith("*"):
            out.append(f"<i>{token[1:-1]}</i>")
        pos = m.end()
    out.append(escaped[pos:])
    return "".join(out)


def _markdown_to_pdf_html(title: str, markdown: str) -> str:
    parts = []
    for block in parse_markdown(markdown):
        if block.kind == "heading":
            if block.level == 1 and block.text.strip() == title.strip():
                continue
            n = min(4, block.level + 1)
            parts.append(f"<h{n}>{_pdf_inline(block.text)}</h{n}>")
        elif block.kind == "p":
            parts.append(f"<p>{_pdf_inline(block.text)}</p>")
        elif block.kind == "list":
            tag = "ol" if block.ordered else "ul"
            items = "".join(f"<li>{_pdf_inline(x)}</li>" for x in block.items)
            parts.append(f"<{tag}>{items}</{tag}>")
        elif block.kind == "quote":
            parts.append(f"<blockquote>{_pdf_inline(block.text)}</blockquote>")
        elif block.kind == "code":
            parts.append(f"<pre>{html.escape(block.text)}</pre>")
        elif block.kind == "table":
            rows = []
            for r, row in enumerate(block.rows):
                cells = "".join(
                    f"<{'th' if r == 0 else 'td'}>{_pdf_inline(c)}</{'th' if r == 0 else 'td'}>"
                    for c in row)
                rows.append(f"<tr>{cells}</tr>")
            parts.append(f"<table>{''.join(rows)}</table>")
        elif block.kind == "hr":
            parts.append("<hr>")
    return (
        "<html><body>"
        f"<h1 class='title'>{html.escape(title)}</h1>"
        + "".join(parts) + "</body></html>"
    )


def _render_pdf(path: Path, title: str, markdown: str) -> None:
    import pymupdf
    body = _markdown_to_pdf_html(title, markdown)
    css = """
      body { font-family: 'china-s'; font-size: 11pt; line-height: 1.75; color: #1f2937; }
      h1.title { font-size: 22pt; margin: 0 0 18pt 0; color: #172033; }
      h2 { font-size: 15pt; color: #172033; margin: 16pt 0 6pt 0; }
      h3 { font-size: 13pt; color: #172033; margin: 13pt 0 5pt 0; }
      h4 { font-size: 11.5pt; color: #172033; margin: 10pt 0 4pt 0; }
      p { margin: 0 0 7pt 0; }
      ul, ol { margin: 4pt 0 8pt 0; padding-left: 18pt; }
      li { margin: 2pt 0; }
      blockquote { margin: 8pt 0; padding: 4pt 8pt; color: #5a6478; background: #f5f7fd; }
      code { font-family: 'china-s'; font-size: 9pt; color: #1f2937; }
      pre { font-size: 8.5pt; line-height: 1.45; background: #f5f7fa; padding: 7pt; margin: 8pt 0; }
      table { width: 100%; border-collapse: collapse; margin: 8pt 0; font-size: 9pt; }
      th, td { border: 1px solid #d9dfec; padding: 4pt; vertical-align: top; }
      th { background: #e8eeff; font-weight: bold; }
      hr { border: 0; border-top: 1px solid #d9dfec; margin: 10pt 0; }
      a { color: #4f6ef7; }
    """
    story = pymupdf.Story(html=body, user_css=css, em=11)
    src = path.with_name(path.stem + ".src.pdf")
    writer = pymupdf.DocumentWriter(str(src))
    page_w, page_h = 595, 842

    def rectfn(rect_num, filled):
        return (pymupdf.Rect(0, 0, page_w, page_h),
                pymupdf.Rect(52, 48, page_w - 52, page_h - 52),
                pymupdf.Matrix(1, 0, 0, 1, 0, 0))

    story.write(writer, rectfn)
    writer.close()
    doc = pymupdf.open(str(src))
    for idx, page in enumerate(doc, 1):
        page.insert_text((page_w / 2 - 8, page_h - 28), str(idx), fontsize=9,
                         color=(0.54, 0.56, 0.62))
    doc.subset_fonts()
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    try:
        src.unlink()
    except OSError:
        pass
