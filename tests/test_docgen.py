"""文档生成：格式识别、真实文件渲染与下载路由。"""
from __future__ import annotations

import asyncio
import zipfile

from conftest import auth

SAMPLE = """# 二次方程教学计划

## 一、教学目标
通过本课学习，学生能够理解 **一元二次方程** 的定义，掌握配方法、公式法和因式分解法。

- 理解一般形式 `ax² + bx + c = 0`
- 掌握求根公式
- 能根据判别式判断根的情况

## 二、教学重点
| 项目 | 内容 | 处理方式 |
|---|---|---|
| 重点 | 求根公式 | 推导 + 例题 |
| 难点 | 配方法 | 分步演示 |

## 三、教学过程
1. 情境导入
2. 探究新知
3. 课堂练习

```python
a, b, c = 1, -3, 2
print(b ** 2 - 4 * a * c)
```
"""


def test_format_resolve():
    from backend.services import docgen
    assert docgen.resolve_format("word", "") == "docx"
    assert docgen.resolve_format("wps文字", "") == "docx"
    assert docgen.resolve_format("电子表格", "") == "xlsx"
    assert docgen.resolve_format("幻灯片", "") == "pptx"
    assert docgen.resolve_format(None, "帮我写一份教学计划，上传word格式") == "docx"
    assert docgen.resolve_format(None, "把数据整理成 excel 表格") == "xlsx"
    assert docgen.resolve_format(None, "初中二次方程生成一个ppt，内容要全") == "pptx"
    assert docgen.resolve_format(None, "做一份幻灯片，讲二次函数") == "pptx"
    assert docgen.resolve_format(None, "Word 文档怎么打开") is None
    assert docgen.resolve_format(None, "今天天气怎么样") is None


def test_all_file_formats_recognized_after_chinese():
    """中文后面紧跟英文格式名也要识别；转换句取最后的目标格式。"""
    from backend.services import docgen
    cases = [
        ("初中二次方程生成一个word，内容要全", "docx"),
        ("把成绩整理成excel表格", "xlsx"),
        ("做一个csv", "xlsx"),
        ("整理成wps文字", "docx"),
        ("做一份pdf讲义", "pdf"),
        ("生成markdown笔记", "md"),
        ("生成txt文件", "txt"),
        ("我要一份word", "docx"),
        ("需要excel", "xlsx"),
        ("用word格式", "docx"),
        ("用Excel做数据透视表", "xlsx"),
        ("word转excel", "xlsx"),
        ("excel转word", "docx"),
        ("pdf转word", "docx"),
        ("把word转成pdf", "pdf"),
    ]
    for text, fmt in cases:
        assert docgen.detect_format(text) == fmt, text
    for text in ("Word 文档怎么打开", "Excel 和 Word 有什么区别",
                 "PPT 和 Word 哪个好", "wordpress 怎么建站"):
        assert docgen.detect_format(text) is None, text


def test_title_from_uses_first_sentence():
    from backend.services.docgen import title_from

    assert title_from("# 二次方程教学计划\n\n正文") == "二次方程教学计划"
    assert title_from("工作台是我们的在线协作工具，主要功能包括：1. 提供统一编辑平台。") == "工作台是我们的在线协作工具"
    assert title_from("本地 AI 工作台的核心价值在于：数据不离开本机。") == "本地 AI 工作台的核心价值"
    long = "这是一段没有标题也没有标点而且明显超过二十八个字的正文内容需要被安全截断而不是整段塞进文件名"
    assert 0 < len(title_from(long)) <= 28


def test_build_all_formats(client, admin_token):
    from docx import Document
    from openpyxl import load_workbook
    from pptx import Presentation
    import pymupdf
    from backend.services import docgen

    async def build(fmt):
        return await docgen.build(1, 1, SAMPLE, fmt)

    rows = {fmt: asyncio.run(build(fmt)) for fmt in ("docx", "xlsx", "pptx", "pdf", "md", "txt")}
    for row in rows.values():
        assert row["id"] > 0
        assert row["size"] > 0
        assert row["url"] == f"/api/files/generated/{row['id']}"

    from backend.config import EXPORT_DIR
    docx_path = EXPORT_DIR / next(p.name for p in EXPORT_DIR.iterdir() if p.suffix == ".docx")
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "二次方程教学计划" in xml and "教学目标" in xml and "求根公式" in xml
    assert "本地 AI 工作台" not in xml and "生成于" not in xml
    doc = Document(str(docx_path))
    assert abs(doc.sections[0].page_width.cm - 21) < 0.2
    assert doc.sections[0].left_margin.cm > 2

    xlsx_path = EXPORT_DIR / next(p.name for p in EXPORT_DIR.iterdir() if p.suffix == ".xlsx")
    wb = load_workbook(xlsx_path)
    assert len(wb.sheetnames) >= 1
    ws = wb[wb.sheetnames[0]]
    assert ws["A1"].value
    assert "项目" in [ws.cell(row=2, column=i).value for i in range(1, 4)]

    pptx_path = EXPORT_DIR / next(p.name for p in EXPORT_DIR.iterdir() if p.suffix == ".pptx")
    prs = Presentation(str(pptx_path))
    assert len(prs.slides) >= 3
    texts = "\n".join(shape.text for slide in prs.slides for shape in slide.shapes if hasattr(shape, "text"))
    assert "二次方程教学计划" in texts
    assert "本地 AI 工作台" not in texts and "生成于" not in texts

    pdf_path = EXPORT_DIR / next(p.name for p in EXPORT_DIR.iterdir() if p.suffix == ".pdf")
    pdf = pymupdf.open(str(pdf_path))
    assert pdf.page_count >= 1
    text = pdf[0].get_text()
    assert "二次方程教学计划" in text and "一、教学目标" in text
    assert "本地 AI 工作台" not in text and "生成于" not in text
    pdf.close()


def test_preview_every_format(client, admin_token):
    from backend.services import docgen

    async def build(fmt):
        return await docgen.build(1, 1, SAMPLE, fmt)

    for fmt in ("docx", "pptx", "xlsx", "pdf", "md"):
        made = asyncio.run(build(fmt))
        res = client.get(made["preview_url"], headers=auth(admin_token))
        assert res.status_code == 200, (fmt, res.text[:300])
        assert res.headers["content-type"].startswith("text/html")
        assert "二次方程教学计划" in res.text
        assert "下载原文件" in res.text
        assert "只读预览" in res.text
    # 预览是 HTML，不把压缩包当网页吐出来
    made = asyncio.run(build("docx"))
    res = client.get(made["preview_url"], headers=auth(admin_token))
    assert "<!doctype html>" in res.text.lower()
    assert "PK" not in res.text[:20]
    # PDF 预览用 inline，不触发下载
    made = asyncio.run(build("pdf"))
    raw = client.get(made["url"] + "?inline=1", headers=auth(admin_token))
    assert raw.status_code == 200
    assert "inline" in raw.headers.get("content-disposition", "")
    assert "attachment" not in raw.headers.get("content-disposition", "")


def test_download_generated_requires_owner(client, admin_token):
    from backend.services import docgen
    made = asyncio.run(docgen.build(1, 1, SAMPLE, "docx"))
    url = made["url"]

    saved = dict(client.cookies)
    client.cookies.clear()
    assert client.get(url).status_code == 401
    client.cookies.update(saved)
    res = client.get(url, headers=auth(admin_token))
    assert res.status_code == 200
    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert "attachment" in res.headers.get("content-disposition", "")
    assert res.content[:2] == b"PK"

    other = client.get("/api/files/generated/999999", headers=auth(admin_token))
    assert other.status_code == 404


def test_generated_table_and_list(client, admin_token):
    from backend.db import fetch_all, fetch_one
    row = asyncio.run(fetch_one(
        "SELECT version,name FROM schema_migrations ORDER BY version DESC LIMIT 1"))
    assert row["version"] == 24 and row["name"] == "task_agent_fields"
    columns = {r["name"] for r in asyncio.run(fetch_all("PRAGMA table_info(generated_files)"))}
    assert {"expires_at", "deleted_at"} <= columns
    res = client.get("/api/files/generated", headers=auth(admin_token))
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) >= 1
    assert data["days"] == 30 and data["warn_days"] == 3
    item = data["items"][0]
    assert item["expires_at"] > 0
    assert item["expires_text"]
    assert item["expired"] is False


def test_expiry_warning_fields():
    import time
    from backend.services import retention
    now = time.time()
    soon = retention.expiry_fields(now + 2.5 * 86400, 0, now)
    assert soon["expiring_soon"] is True and soon["expired"] is False
    assert soon["days_left"] == 3 and soon["warn_days"] == 3
    safe = retention.expiry_fields(now + 20 * 86400, 0, now)
    assert safe["expiring_soon"] is False and safe["expired"] is False
    cleaned = retention.expiry_fields(now - 86400, now, now)
    assert cleaned["cleaned"] is True and cleaned["expired"] is True


def test_generated_files_have_expiry(client, admin_token):
    from backend.services import docgen
    made = asyncio.run(docgen.build(1, 1, SAMPLE, "docx"))
    assert made["expires_at"] > 0
    assert made["expires_text"]
    assert made["days_left"] in (29, 30)
    assert made["expired"] is False


def test_retention_settings_and_cleanup(client, admin_token):
    import time
    import uuid
    from backend.config import EXPORT_DIR
    from backend.db import execute, fetch_one
    from backend.services import docgen

    got = client.get("/api/system/file-retention", headers=auth(admin_token))
    assert got.status_code == 200
    assert got.json()["days"] == 30

    changed = client.put("/api/system/file-retention", json={"days": 7},
                         headers=auth(admin_token))
    assert changed.status_code == 200
    assert changed.json()["days"] == 7
    bad = client.put("/api/system/file-retention", json={"days": 0},
                     headers=auth(admin_token))
    assert bad.status_code == 400
    restored = client.put("/api/system/file-retention", json={"days": 30},
                          headers=auth(admin_token))
    assert restored.json()["days"] == 30

    stored = f"{uuid.uuid4().hex}.docx"
    path = EXPORT_DIR / stored
    path.write_bytes(b"expired-test-file")
    expired_id = asyncio.run(execute(
        "INSERT INTO generated_files(user_id,conversation_id,message_id,name,stored_name,mime,size,kind,"
        "created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (1, None, None, "过期测试.docx", stored,
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         path.stat().st_size, "docx", time.time() - 40 * 86400, time.time() - 86400)))
    before = client.get("/api/files/generated", headers=auth(admin_token)).json()
    assert all(item["id"] != expired_id for item in before["items"])
    res = client.get(f"/api/files/generated/{expired_id}", headers=auth(admin_token))
    assert res.status_code == 410

    cleaned = client.post("/api/system/file-retention/cleanup", headers=auth(admin_token))
    assert cleaned.status_code == 200
    assert cleaned.json()["result"]["removed"] >= 1
    assert not path.exists()
    row = asyncio.run(fetch_one(
        "SELECT deleted_at,expires_at FROM generated_files WHERE id=?", (expired_id,)))
    assert row["deleted_at"] > 0 and row["expires_at"] > 0
    after = client.get(f"/api/files/generated/{expired_id}", headers=auth(admin_token))
    assert after.status_code == 410
    assert "自动清理" in after.json()["detail"]

    items = [{"id": expired_id, "name": "过期测试.docx", "size": 1, "kind": "docx"}]
    asyncio.run(docgen.enrich_file_list(items, 1))
    assert items[0]["cleaned"] is True and items[0]["expired"] is True
    assert items[0]["deleted_text"]


