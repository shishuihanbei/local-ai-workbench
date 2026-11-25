"""资料库：总库/个人库权限、开关、重复引用与模块隔离。"""
from __future__ import annotations

import asyncio
import io
import time

from backend.config import load_config, save_config
from backend.routers.chat import ChatBody, _build_context
from backend.services import attachments


def auth(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _make_user(client, admin_token: str, name: str) -> tuple[str, int]:
    h = auth(admin_token)
    r = client.post("/api/users", headers=h, json={
        "username": name, "password": "Pytest-pass-2026", "role": "user"})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={
        "username": name, "password": "Pytest-pass-2026"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    me = client.get("/api/auth/me", headers=auth(tok)).json()
    return tok, me["user"]["id"]


def _set_lib(enabled: bool) -> None:
    cfg = load_config()
    cfg["library_enabled"] = enabled
    save_config(cfg)


def test_library_defaults_off_and_admin_only_global(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok, _ = _make_user(client, admin_token, f"libdef{suffix}")
    _set_lib(False)
    try:
        d = client.get("/api/my/library", headers=auth(tok)).json()
        assert d["global_enabled"] is False
        assert d["personal_enabled"] is False
        assert d["use_global"] is False
        assert d["use_personal"] is True

        # 普通用户不能写总库，也不能删总库
        assert client.post("/api/library/text", headers=auth(tok),
                           data={"title": "越权", "content": "不应写入"}).status_code == 403
        r = client.post("/api/library/text", headers=auth(admin_token),
                        data={"title": "总库参数", "content": "总库参数：额定电流 16A。"})
        assert r.status_code == 200, r.text
        gid = r.json()["id"]
        assert r.json()["scope"] == "global"
        assert client.delete(f"/api/library/{gid}", headers=auth(tok)).status_code == 403
        assert client.delete(f"/api/my/library/{gid}", headers=auth(tok)).status_code == 404

        admin_all = client.get("/api/library", headers=auth(admin_token)).json()
        assert any(x["id"] == gid and x["module"] == "library" for x in admin_all["docs"])
    finally:
        _set_lib(False)


def test_personal_library_only_owner_can_delete(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok_a, _ = _make_user(client, admin_token, f"liba{suffix}")
    tok_b, _ = _make_user(client, admin_token, f"libb{suffix}")
    r = client.post("/api/my/library/text", headers=auth(tok_a),
                    data={"title": "接线说明", "content": "端子 1 接火线，端子 2 接零线。"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert r.json()["scope"] == "personal"

    mine = client.get("/api/my/library", headers=auth(tok_a)).json()
    assert mine["count"] == 1
    assert client.delete(f"/api/my/library/{doc_id}", headers=auth(tok_b)).status_code == 404
    # 管理员可以统一查看并删除个人资料
    detail = client.get(f"/api/library/doc/{doc_id}", headers=auth(admin_token)).json()
    assert detail["scope"] == "personal" and "端子 1" in detail["content"]
    assert client.delete(f"/api/library/{doc_id}", headers=auth(admin_token)).status_code == 200
    assert client.get("/api/my/library", headers=auth(tok_a)).json()["count"] == 0


def test_picker_and_chat_injection_are_repeatable(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok, uid = _make_user(client, admin_token, f"libchat{suffix}")
    r = client.post("/api/library/text", headers=auth(admin_token),
                    data={"title": "总库安全规程", "content": "检修前必须断电并挂牌上锁。"})
    assert r.status_code == 200, r.text
    gid = r.json()["id"]

    _set_lib(True)
    try:
        # 用户没勾总库时看不到
        assert client.get("/api/my/library/picker", headers=auth(tok)).json()["items"] == []

        assert client.post("/api/my/library/settings", headers=auth(tok),
                           json={"personal_enabled": True, "use_global": True}).status_code == 200
        picker = client.get("/api/my/library/picker", headers=auth(tok)).json()
        assert any(x["id"] == gid for x in picker["items"])

        cfg = {"system_prompt": "", "kb_enabled": False, "library_enabled": True,
               "library_max_chars": 12000, "library_max_docs": 10}
        body = ChatBody(message="检修前要做什么", library_docs=[gid])
        for expected in (1, 2):
            messages, _, meta = asyncio.run(
                _build_context({"id": uid}, body, cfg, att_rows=[]))
            assert any("检修前必须断电" in m.get("content", "") for m in messages)
            assert meta["library"]["items"][0]["id"] == gid
            rows = client.get("/api/library", headers=auth(admin_token)).json()["docs"]
            row = next(x for x in rows if x["id"] == gid)
            assert row["uses"] == expected

        # 管理员关闭总库后，即使用户勾选也不会带入
        _set_lib(False)
        cfg["library_enabled"] = False
        _, _, meta = asyncio.run(_build_context({"id": uid}, body, cfg, att_rows=[]))
        assert "library" not in meta
        assert client.get("/api/my/library/picker", headers=auth(tok)).json()["items"] == []
    finally:
        _set_lib(False)
        client.delete(f"/api/library/{gid}", headers=auth(admin_token))


def test_library_and_kb_are_separate_in_export(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    lib = client.post("/api/library/text", headers=auth(admin_token),
                      data={"title": f"资料库导出{suffix}", "content": "只在资料库里"}).json()
    kb = client.post("/api/kb/text", headers=auth(admin_token),
                     data={"title": f"知识库导出{suffix}", "content": "只在知识库里"}).json()
    try:
        lib_payload = client.get("/api/library/export", headers=auth(admin_token)).json()
        lib_titles = {x["title"] for x in lib_payload["docs"]}
        assert lib["title"] in lib_titles
        assert kb["title"] not in lib_titles
        assert lib_payload["format"] == "workbench-library-backup"

        kb_payload = client.get("/api/kb/export", headers=auth(admin_token)).json()
        kb_titles = {x["title"] for x in kb_payload["docs"]}
        assert kb["title"] in kb_titles
        assert lib["title"] not in kb_titles

        # 知识库检索不会被资料库文档污染
        hits = client.get("/api/kb/search", headers=auth(admin_token),
                          params={"q": "只在资料库里"}).json()["items"]
        assert all(x["doc_id"] != lib["id"] for x in hits)
    finally:
        client.delete(f"/api/library/{lib['id']}", headers=auth(admin_token))
        client.delete(f"/api/kb/{kb['id']}", headers=auth(admin_token))


def _pdf_bytes(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def _image_bytes(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (800, 220), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 44)
    except Exception:
        font = ImageFont.load_default()
    draw.text((30, 75), text, font=font, fill="black")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _scanned_pdf_bytes(text: str) -> bytes:
    import pymupdf
    png = _image_bytes(text)
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=220)
    page.insert_image(page.rect, stream=png)
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def test_library_upload_supports_word_pdf_excel(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok, _ = _make_user(client, admin_token, f"libdoc{suffix}")
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation

    docx = io.BytesIO()
    d = Document()
    d.add_paragraph("Word 正文 ABC123，应该能被提取。")
    d.save(docx)

    xlsx = io.BytesIO()
    wb = Workbook()
    wb.active.append(["Excel 单元格", "内容456"])
    wb.save(xlsx)

    pptx = io.BytesIO()
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "PPT 标题 XYZ789"
    slide.placeholders[1].text = "幻灯片正文，应该能被提取。"
    prs.save(pptx)

    cases = [
        (f"资料{suffix}.docx", docx.getvalue(), "ABC123",
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (f"表格{suffix}.xlsx", xlsx.getvalue(), "内容456",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        (f"幻灯片{suffix}.pptx", pptx.getvalue(), "XYZ789",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        (f"文档{suffix}.pdf", _pdf_bytes(f"PDF body {suffix}"), suffix,
         "application/pdf"),
    ]
    ids = []
    for name, raw, needle, mime in cases:
        r = client.post("/api/my/library/upload", headers=auth(tok),
                        files={"file": (name, raw, mime)})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["title"] == name
        got = client.get(f"/api/my/library/doc/{res['id']}", headers=auth(tok)).json()
        assert needle in got["content"], got
        ids.append(res["id"])
    assert len(ids) == 4
    sr = client.get("/api/my/library/search?q=ABC123", headers=auth(tok))
    assert sr.status_code == 200, sr.text
    assert any(f"资料{suffix}.docx" == x["title"] for x in sr.json()["items"])


def test_image_and_scanned_pdf_are_read_by_ocr(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok, _ = _make_user(client, admin_token, f"libocr{suffix}")
    marker = f"OCR IMAGE {suffix}"
    png = _image_bytes(marker)

    r = client.post("/api/chat/files", headers=auth(tok),
                    files={"file": (f"截图{suffix}.png", png, "image/png")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["chars"] > 0, data
    assert data["library"]["status"] == "added", data
    doc = client.get(f"/api/my/library/doc/{data['library']['doc_id']}", headers=auth(tok)).json()
    assert "OCR" in doc["content"] and suffix in doc["content"]

    scanned = _scanned_pdf_bytes(marker)
    r = client.post("/api/my/library/upload", headers=auth(tok),
                    files={"file": (f"扫描件{suffix}.pdf", scanned, "application/pdf")})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/my/library/doc/{r.json()['id']}", headers=auth(tok)).json()
    assert "OCR" in got["content"] and suffix in got["content"], got["content"]

    rows = [{"name": "截图.png", "kind": "image", "text_content": "图片 OCR 正文"}]
    assert "图片 OCR 正文" in attachments.context_block(rows)


def test_personal_library_search_is_account_scoped(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    ta, _ = _make_user(client, admin_token, f"libsa{suffix}")
    tb, _ = _make_user(client, admin_token, f"libsb{suffix}")
    for tok, tag in ((ta, "甲"), (tb, "乙")):
        r = client.post("/api/my/library/text", headers=auth(tok),
                        data={"title": f"检索{tag}{suffix}", "content": f"隔离词 {tag}{suffix} 正文"})
        assert r.status_code == 200, r.text
    ra = client.get("/api/my/library/search", headers=auth(ta), params={"q": "隔离词"})
    rb = client.get("/api/my/library/search", headers=auth(tb), params={"q": "隔离词"})
    assert ra.status_code == rb.status_code == 200
    ta_titles = {x["title"] for x in ra.json()["items"]}
    tb_titles = {x["title"] for x in rb.json()["items"]}
    assert f"检索甲{suffix}" in ta_titles and f"检索乙{suffix}" not in ta_titles
    assert f"检索乙{suffix}" in tb_titles and f"检索甲{suffix}" not in tb_titles


def test_library_folders_tags_and_organize(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok, _ = _make_user(client, admin_token, f"libtag{suffix}")
    r = client.post("/api/my/library/text", headers=auth(tok), data={
        "title": f"合同{suffix}", "content": "付款周期为 30 天。",
        "folder": "合同资料", "tags": "合同, 付款, 财务专用",
    })
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    assert r.json()["folder"] == "合同资料"
    assert r.json()["tags"] == "合同,付款,财务专用"

    mine = client.get("/api/my/library", headers=auth(tok)).json()
    assert mine["folders"] == [{"name": "合同资料", "count": 1}]
    assert {"name": "合同", "count": 1} in mine["tags"]
    row = next(x for x in mine["docs"] if x["id"] == doc_id)
    assert row["folder"] == "合同资料" and row["tags"] == "合同,付款,财务专用"

    # 标签即使不在标题和正文里也能被检索到
    sr = client.get("/api/my/library/search", headers=auth(tok), params={"q": "财务专用"})
    assert any(x["doc_id"] == doc_id for x in sr.json()["items"])

    r = client.patch(f"/api/my/library/{doc_id}", headers=auth(tok),
                     json={"title": f"采购合同{suffix}", "folder": "已签合同",
                           "tags": "合同; 已签"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["title"] == f"采购合同{suffix}"
    assert got["folder"] == "已签合同" and got["tags"] == "合同,已签"

    # 管理员也能整理用户的个人资料
    r = client.patch(f"/api/library/{doc_id}", headers=auth(admin_token),
                     json={"folder": "管理员归档", "tags": "归档"})
    assert r.status_code == 200, r.text
    assert r.json()["folder"] == "管理员归档" and r.json()["tags"] == "归档"

    backup = client.get("/api/library/export", headers=auth(admin_token))
    assert backup.status_code == 200
    payload = backup.json()
    item = next(x for x in payload["docs"] if x["title"] == f"采购合同{suffix}")
    assert item["folder"] == "管理员归档" and item["tags"] == "归档"


def test_chat_upload_is_added_to_personal_library(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    tok, _ = _make_user(client, admin_token, f"libup{suffix}")
    name = f"聊天上传{suffix}.txt"
    content = "这是聊天附件正文，上传后应自动进入个人资料库。"
    r = client.post("/api/chat/files", headers=auth(tok),
                    files={"file": (name, content.encode("utf-8"), "text/plain")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == name
    assert data["library"]["status"] == "added"

    docs = client.get("/api/my/library", headers=auth(tok)).json()["docs"]
    row = next((x for x in docs if x["title"] == name), None)
    assert row and row["source"] == "聊天上传"
    assert row["folder"] == "聊天上传"
    assert row["tags"] == "聊天上传"

    again = client.post("/api/chat/files", headers=auth(tok),
                        files={"file": (name, content.encode("utf-8"), "text/plain")})
    assert again.status_code == 200
    assert again.json()["library"]["status"] == "exists"
    docs = client.get("/api/my/library", headers=auth(tok)).json()["docs"]
    assert sum(1 for x in docs if x["title"] == name) == 1


def test_library_backup_restore_roundtrip(client, admin_token):
    suffix = str(int(time.time()))[-6:]
    title = f"资料库回填{suffix}"
    r = client.post("/api/library/text", headers=auth(admin_token),
                    data={"title": title, "content": "备份后删除，再从备份恢复。",
              "folder": "备份验收", "tags": "备份,恢复"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["id"]
    backup = client.get("/api/library/export", headers=auth(admin_token))
    assert backup.status_code == 200
    assert client.delete(f"/api/library/{doc_id}", headers=auth(admin_token)).status_code == 200
    restored = client.post("/api/library/restore", headers=auth(admin_token),
                           files={"file": ("library.json", backup.content, "application/json")})
    assert restored.status_code == 200, restored.text
    rows = client.get("/api/library", headers=auth(admin_token)).json()["docs"]
    restored_id = next((x["id"] for x in rows if x["title"] == title), None)
    assert restored_id is not None
    restored = next(x for x in rows if x["id"] == restored_id)
    assert restored["folder"] == "备份验收" and restored["tags"] == "备份,恢复"
    client.delete(f"/api/library/{restored_id}", headers=auth(admin_token))
