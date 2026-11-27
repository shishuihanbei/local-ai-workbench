"""生成文件的站内预览：把 docx / pptx / xlsx / pdf / 文本转成只读 HTML。"""
from __future__ import annotations

import base64
import html
from pathlib import Path
from typing import Any

MAX_ROWS = 60
MAX_COLS = 24
MAX_SLIDES = 80
MAX_IMAGES = 30


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _shell(title: str, kind: str, body: str, download_url: str, embed: bool = False) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>预览 · {_e(title)}</title>
<style>
  :root {{ --brand:#4F6EF7; --brand2:#7B61FF; --ink:#172033; --muted:#6B7586; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#EEF1F7; color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }}
  header {{ position:sticky; top:0; z-index:2; display:flex; align-items:center; gap:12px;
    padding:12px 18px; background:rgba(255,255,255,.94); border-bottom:1px solid #DDE3EE;
    backdrop-filter:blur(10px); }}
  header .name {{ min-width:0; }}
  header b {{ display:block; font-size:14px; overflow:hidden; text-overflow:ellipsis;
    white-space:nowrap; max-width:55vw; }}
  header small {{ color:var(--muted); font-size:11.5px; }}
  header .sp {{ flex:1; }}
  header a {{ flex:none; text-decoration:none; color:#fff; background:var(--brand);
    padding:8px 14px; border-radius:9px; font-size:12.5px; font-weight:650; }}
  main {{ max-width:1120px; margin:0 auto; padding:26px 18px 60px; }}
  .doc {{ background:#fff; border:1px solid #E3E8F2; border-radius:16px;
    padding:46px 54px; box-shadow:0 18px 46px rgba(23,32,51,.08); line-height:1.85; }}
  .doc h1 {{ font-size:28px; line-height:1.35; margin:0 0 22px; }}
  .doc h2 {{ font-size:22px; margin:32px 0 12px; }}
  .doc h3 {{ font-size:18px; margin:24px 0 10px; }}
  .doc p {{ margin:10px 0; font-size:15px; }}
  .doc ul,.doc ol {{ margin:10px 0 10px 24px; padding:0; font-size:15px; }}
  .doc li {{ margin:5px 0; }}
  .doc table {{ border-collapse:collapse; width:100%; margin:16px 0; font-size:14px; }}
  .doc th,.doc td {{ border:1px solid #DFE5EF; padding:8px 10px; text-align:left; vertical-align:top; }}
  .doc th {{ background:#F4F7FD; font-weight:700; }}
  .doc img {{ max-width:100%; border-radius:10px; margin:12px 0; }}
  .slides {{ display:grid; gap:24px; }}
  .slide {{ position:relative; background:#fff; border:1px solid #DFE5F2; border-radius:14px;
    aspect-ratio:16/9; overflow:hidden; box-shadow:0 12px 32px rgba(23,32,51,.10);
    padding:42px 48px 34px; }}
  .slide:before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:7px;
    background:linear-gradient(180deg,var(--brand),var(--brand2)); }}
  .slide .no {{ position:absolute; right:18px; bottom:10px; color:#9AA4B5; font-size:11px; }}
  .slide h2 {{ font-size:21px; margin:0 0 12px; padding-bottom:9px;
    border-bottom:2px solid #EEF1F9; }}
  .slide ul {{ margin:0 0 0 19px; padding:0; font-size:14px; line-height:1.62; }}
  .slide li {{ margin:5px 0; }}
  .slide .pic {{ display:block; width:auto; max-width:36%; max-height:380px;
    object-fit:contain; border-radius:9px; margin:0; flex:none; }}
  .slide .pic.small {{ max-width:26%; max-height:200px; }}
  .grid {{ display:flex; gap:22px; align-items:flex-start; }}
  .grid .text {{ flex:1; min-width:0; }}
  .sheet {{ background:#fff; border:1px solid #DFE5F2; border-radius:14px; padding:16px 18px;
    margin-bottom:18px; overflow:auto; box-shadow:0 12px 30px rgba(23,32,51,.06); }}
  .sheet h2 {{ font-size:16px; margin:0 0 12px; }}
  table.data {{ border-collapse:collapse; font-size:12.5px; width:100%; }}
  table.data td {{ border:1px solid #E1E7F1; padding:6px 8px; white-space:pre-wrap;
    vertical-align:top; min-width:64px; }}
  table.data tr:first-child td {{ background:#F4F7FD; font-weight:700; }}
  .txt {{ white-space:pre-wrap; font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
    font-size:13.5px; line-height:1.7; margin:0; }}
  iframe {{ width:100%; height:calc(100vh - 58px); border:0; background:#fff; }}
  .tip {{ color:var(--muted); text-align:center; padding:60px 20px; }}
  .embed header {{ display:none; }}
</style></head><body{'' if not embed else ' class="embed"'}>
<header><div class="name"><b>{_e(title)}</b><small>{_e(kind.upper())} · 只读预览</small></div>
<span class="sp"></span><a href="{_e(download_url)}" download>下载原文件</a></header>
<main>{body}</main></body></html>"""


def _docx_html(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    parts: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = str(child.tag).rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            if style.lower().startswith("heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "2"
                level = min(max(int(level), 1), 3)
                parts.append(f"<h{level}>{_e(text)}</h{level}>")
            else:
                parts.append(f"<p>{_e(text)}</p>")
        elif tag == "tbl":
            tbl = Table(child, doc)
            rows = tbl.rows[:MAX_ROWS]
            if not rows:
                continue
            html_rows = []
            for i, row in enumerate(rows):
                cells = row.cells[:MAX_COLS]
                cell_tag = "th" if i == 0 else "td"
                html_rows.append("<tr>" + "".join(
                    f"<{cell_tag}>{_e(c.text)}</{cell_tag}>" for c in cells) + "</tr>")
            parts.append("<table>" + "".join(html_rows) + "</table>")
    body = "<div class='doc'>" + ("".join(parts) or "<p>（空白文档）</p>") + "</div>"
    return body


def _shape_pictures(slide) -> list[str]:
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    pics: list[str] = []
    for shape in slide.shapes:
        try:
            if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
                continue
            image = shape.image
            if len(image.blob) > 8 * 1024 * 1024:
                continue
            mime = image.content_type or "image/png"
            b64 = base64.b64encode(image.blob).decode("ascii")
            pics.append(f"<img class='pic{' small' if len(pics) else ''}' src='data:{mime};base64,{b64}'>")
        except Exception:
            continue
        if len(pics) >= MAX_IMAGES:
            break
    return pics


def _pptx_html(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    slides: list[str] = []
    for idx, slide in enumerate(prs.slides, 1):
        if idx > MAX_SLIDES:
            break
        heading = ""
        bullets: list[str] = []
        table_html = ""
        for shape in slide.shapes:
            try:
                if shape.has_table:
                    rows = list(shape.table.rows)[:MAX_ROWS]
                    trs = []
                    for r, row in enumerate(rows):
                        cells = list(row.cells)[:MAX_COLS]
                        trs.append("<tr>" + "".join(
                            f"<{'th' if r == 0 else 'td'}>{_e(c.text)}</{'th' if r == 0 else 'td'}>"
                            for c in cells) + "</tr>")
                    table_html = "<div class='sheet'><table class='data'>" + "".join(trs) + "</table></div>"
                elif shape.has_text_frame:
                    text = "\n".join(p.text for p in shape.text_frame.paragraphs if p.text).strip()
                    if not text:
                        continue
                    # 页码是单独的小文本框，不能当成正文项目符号
                    if text == str(idx) and (shape.top or 0) > 6 * 914400:
                        continue
                    if not heading:
                        heading = text.splitlines()[0].strip()
                        rest = text.splitlines()[1:]
                        bullets.extend(x.strip() for x in rest if x.strip())
                    else:
                        bullets.extend(x.strip() for x in text.splitlines() if x.strip())
            except Exception:
                continue
        pics = _shape_pictures(slide)
        body = "".join(f"<li>{_e(x)}</li>" for x in bullets[:10])
        text_block = (f"<h2>{_e(heading)}</h2>" if heading else "") + (
            f"<ul>{body}</ul>" if body else "")
        visual = "".join(pics[:2])
        inner = text_block
        if visual:
            inner = f"<div class='grid'><div class='text'>{text_block}</div>{visual}</div>"
        if table_html:
            inner += table_html
        if not inner.strip():
            inner = "<div class='tip'>此页没有可提取的文字</div>"
        slides.append(f"<section class='slide'>{inner}<span class='no'>{idx}</span></section>")
    if not slides:
        return "<div class='tip'>这份演示文稿没有页面</div>"
    return f"<div class='slides'>{''.join(slides)}</div>"


def _xlsx_html(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), data_only=True, read_only=True)
    sheets: list[str] = []
    for ws in wb.worksheets[:4]:
        rows: list[str] = []
        for r, row in enumerate(ws.iter_rows(max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True), 1):
            cells = "".join(f"<td>{_e('' if v is None else v)}</td>" for v in row)
            rows.append(f"<tr>{cells}</tr>")
        sheets.append(f"<div class='sheet'><h2>{_e(ws.title)}</h2>"
                      f"<table class='data'>{''.join(rows) or '<tr><td>（空白工作表）</td></tr>'}</table></div>")
    wb.close()
    return "".join(sheets) or "<div class='tip'>这份表格没有工作表</div>"


def _text_html(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return f"<div class='doc'><pre class='txt'>{_e(raw[:200000])}</pre></div>"


def html_for(path: Path, kind: str, name: str, download_url: str, embed: bool = False) -> str:
    kind = (kind or path.suffix.lstrip(".")).lower()
    if kind == "docx":
        body = _docx_html(path)
    elif kind == "pptx":
        body = _pptx_html(path)
    elif kind == "xlsx":
        body = _xlsx_html(path)
    elif kind == "pdf":
        body = f"<iframe src='{_e(download_url)}?inline=1' title='PDF 预览'></iframe>"
    elif kind in ("md", "txt", "csv"):
        body = _text_html(path)
    else:
        body = "<div class='tip'>这个格式暂不支持站内预览，请下载后用本地应用打开。</div>"
    return _shell(name, kind, body, download_url, embed)
