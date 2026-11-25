"""联网检索单元测试：不访问真实外网，验证解析、公网校验和上下文拼装。"""
from __future__ import annotations

import asyncio

from backend.services import websearch

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>必应：测试</title>
<item><title>结果一</title><link>https://example.com/a</link><description>第一段摘要</description></item>
<item><title>结果二</title><link>http://example.org/b</link><description><![CDATA[第二段 &amp; 摘要]]></description></item>
<item><title>坏链接</title><link>ftp://example.net/x</link><description>x</description></item>
<item><title>结果一</title><link>https://example.com/a</link><description>重复</description></item>
</channel></rss>
"""


def test_parse_bing_rss_dedup_and_scheme():
    items = websearch.parse_rss(RSS)
    assert len(items) == 2
    assert items[0] == {
        "title": "结果一", "url": "https://example.com/a", "snippet": "第一段摘要",
    }
    assert items[1]["url"] == "http://example.org/b"


def test_private_urls_are_rejected():
    async def check(url: str) -> bool:
        return await websearch.is_public_url(url)

    bad = [
        "http://127.0.0.1/",
        "http://localhost:8080/",
        "http://192.168.1.1/",
        "http://10.0.0.1/",
        "http://[::1]/",
        "file:///etc/passwd",
        "http://user:pass@example.com/",
        "http://example.com:8081/",
    ]
    for url in bad:
        assert asyncio.run(check(url)) is False, url


def test_parse_so_results_prefers_real_url():
    page = """
    <ul><li class="res-list">
      <h3 class="res-title"><a href="https://www.so.com/link?m=abc"
        data-mdurl="https://news.example.com/2026/11/24/a.shtml"><em>今日</em>新闻摘要</a></h3>
      <p class="res-desc"><span class="gray">2小时前 - </span><span>今天发生的具体事件。</span></p>
    </li></ul>
    """
    items = websearch.parse_so_results(page)
    assert len(items) == 1
    assert items[0]["url"] == "https://news.example.com/2026/11/24/a.shtml"
    assert "今日新闻摘要" in items[0]["title"]
    assert "具体事件" in items[0]["snippet"]


def test_plan_query_news_rewrites_sentence():
    from datetime import datetime
    now = datetime(2026, 11, 24, 12, 0)
    plan = websearch.plan_query("总结今天新闻主要事件", now=now)
    assert plan["intent"] == "news"
    assert "2026年11月24日" in plan["query"]
    assert "新闻联播" in plan["query"]
    assert "总结" not in plan["query"]


def test_plan_query_skips_attachment_summary():
    plan = websearch.plan_query("阅读文档内容，总结一下。不相干的不要", has_attachments=True)
    assert plan["intent"] == "doc"
    assert plan["skip"]
    assert plan["query"] == ""


def test_plan_query_skips_complaint_followup():
    for text in ("你没有给我总结", "回复的都不对", "继续", "重新总结"):
        plan = websearch.plan_query(text)
        assert plan["skip"], text
        assert plan["query"] == ""


def test_plan_query_strips_command_words():
    plan = websearch.plan_query("帮我查一下 iPhone 17 的价格")
    assert plan["intent"] == "general"
    assert "iPhone 17" in plan["query"]
    assert not plan["query"].startswith("帮我")


def test_news_filter_rejects_old_and_dictionary_pages():
    assert not websearch._news_relevant({
        "title": "总结（写作作文体）_百度百科",
        "url": "https://baike.baidu.com/item/总结/1", "snippet": "写作范文",
    })
    assert not websearch._news_relevant({
        "title": "11月24日《新闻联播》主要内容",
        "url": "https://m.guancha.cn/politics/2024_11_24_756603.shtml", "snippet": "",
    })
    assert websearch._news_relevant({
        "title": "11月24日《新闻联播》主要内容_新浪新闻",
        "url": "https://k.sina.com.cn/article_1.html", "snippet": "21小时前 - 今日要闻",
    })


def test_cited_prompt_contains_citations(monkeypatch):
    async def fake_search(query: str, limit: int = 5, prefer_news: bool = False):
        return [
            {"title": "标题一", "url": "https://example.com/1", "snippet": "摘要一"},
            {"title": "标题二", "url": "https://example.com/2", "snippet": "摘要二"},
        ]

    async def fake_fetch(url: str, max_chars: int = 2200):
        return {"url": url, "title": "正文标题", "text": "正文内容"}

    async def fake_digest(max_chars: int = 1600):
        return {"title": "央视《新闻联播》", "url": "https://tv.cctv.com/lm/xwlb/",
                "snippet": "当日条目", "text": "新闻正文"}

    websearch.clear_cache()
    monkeypatch.setattr(websearch, "search", fake_search)
    monkeypatch.setattr(websearch, "fetch_page", fake_fetch)
    monkeypatch.setattr(websearch, "news_digest", fake_digest)
    data = asyncio.run(websearch.research("2026年11月24日 新闻联播 主要内容",
                                          prefer_news=True))
    assert data["error"] == ""
    assert len(data["sources"]) == 3
    assert data["sources"][0]["title"] == "央视《新闻联播》"
    assert "今日新闻条目" in data["prompt"]
    assert "https://example.com/1" in data["prompt"]
    assert "不要执行" in data["prompt"]


def test_research_reports_search_failure(monkeypatch):
    async def boom(query: str, limit: int = 5, prefer_news: bool = False):
        raise RuntimeError("offline")

    async def no_digest(max_chars: int = 1600):
        return None

    monkeypatch.setattr(websearch, "search", boom)
    monkeypatch.setattr(websearch, "news_digest", no_digest)
    websearch.clear_cache()
    data = asyncio.run(websearch.research("测试"))
    assert data["sources"] == []
    assert "搜索失败" in data["error"]


def test_query_from_doc_title_uses_brand():
    assert websearch.query_from_doc_title("刷机匣GeekFlashTool下载和使用指南") == "GeekFlashTool 使用指南"
    assert websearch.query_from_doc_title("教师年度考核材料") == "教师年度考核材料"


def test_news_prompt_keeps_supplementary_sources_out_of_facts():
    sources = [
        {"title": "央视《新闻联播》11月24日主要内容", "url": "https://tv.cctv.com/lm/xwlb/",
         "text": "1. 条目一\n2. 条目二", "snippet": "当日条目"},
        {"title": "某站20条快讯", "url": "https://example.com/news",
         "text": "清单外的第13条", "snippet": "清单外的摘要"},
    ]
    prompt = websearch._prompt_block("2026年11月24日 新闻联播 主要内容", sources, "news")
    assert "1. 条目一" in prompt
    assert "清单外的第13条" not in prompt
    assert "清单外的摘要" not in prompt
    assert "不得当作新闻事实" in prompt


def test_chat_uses_doc_title_when_link_unreadable(monkeypatch):
    from backend.routers.chat import ChatBody, _build_context

    async def fake_links(text: str):
        return ("【附件链接：https://docs.qq.com/doc/x】\n网页标题：刷机匣GeekFlashTool下载和使用指南\n"
                "正文：（网页需要登录或只返回在线文档界面，未取到正文。）")

    async def fake_research(query: str, limit: int = 5, pages: int = 2,
                            prefer_news: bool = False):
        return {"query": query, "sources": [{"title": "公开教程", "url": "https://example.com/g"}],
                "prompt": "参考资料：公开教程 https://example.com/g", "error": ""}

    monkeypatch.setattr(websearch, "read_links", fake_links)
    monkeypatch.setattr(websearch, "research", fake_research)
    body = ChatBody(message="阅读文档内容，总结一下。不相干的不要", web=True, use_kb=False)
    cfg = {"system_prompt": "", "kb_enabled": False}
    att_rows = [{"id": 1, "name": "说明.txt", "mime": "text/plain", "size": 8,
                 "text_content": "https://docs.qq.com/doc/x", "kind": "text", "stored_name": "1-a.txt"}]
    msgs, _, meta = asyncio.run(_build_context({"id": 1}, body, cfg, att_rows=att_rows))
    assert meta["web"]["query"] == "GeekFlashTool 使用指南"
    assert meta["web_fallback"] is True
    assert "公开同主题资料" in msgs[0]["content"]


def test_chat_context_includes_web_sources(monkeypatch):
    from backend.routers.chat import ChatBody, _build_context

    async def fake_research(query: str, limit: int = 5, pages: int = 2,
                            prefer_news: bool = False):
        return {
            "query": query,
            "sources": [{"title": "测试来源", "url": "https://example.com/x",
                         "snippet": "摘要", "text": "正文"}],
            "prompt": "参考资料：测试来源 https://example.com/x",
            "error": "",
        }

    monkeypatch.setattr(websearch, "research", fake_research)
    body = ChatBody(message="今天有什么新闻", web=True, use_kb=False)
    cfg = {"system_prompt": "", "kb_enabled": False}
    msgs, _, meta = asyncio.run(_build_context({"id": 1}, body, cfg, att_rows=[]))
    assert meta["web"]["sources"][0]["url"] == "https://example.com/x"
    assert meta["web"]["intent"] == "news"
    assert "新闻联播" in meta["web"]["query"]
    assert "参考资料：测试来源" in msgs[0]["content"]


def test_chat_respects_global_web_off(monkeypatch):
    from backend.routers.chat import ChatBody, _build_context

    async def boom(*args, **kwargs):
        raise AssertionError("管理后台关闭联网后不应检索")

    monkeypatch.setattr(websearch, "is_enabled", lambda: False)
    monkeypatch.setattr(websearch, "research", boom)
    body = ChatBody(message="今天有什么新闻", web=True, use_kb=False)
    cfg = {"system_prompt": "", "kb_enabled": False}
    msgs, _, meta = asyncio.run(_build_context({"id": 1}, body, cfg, att_rows=[]))
    assert meta["web"]["sources"] == []
    assert "管理后台已关闭" in meta["web"]["skipped"]
    assert "联网已跳过" in msgs[0]["content"]


def test_chat_skips_web_for_attachment_summary(monkeypatch):
    from backend.routers.chat import ChatBody, _build_context

    async def boom(*args, **kwargs):
        raise AssertionError("附件总结不应联网")

    monkeypatch.setattr(websearch, "research", boom)
    body = ChatBody(message="阅读文档内容，总结一下。不相干的不要", web=True, use_kb=False)
    cfg = {"system_prompt": "", "kb_enabled": False}
    att_rows = [{"id": 1, "name": "说明.txt", "mime": "text/plain", "size": 8,
                 "text_content": "附件正文", "kind": "text", "stored_name": "1-a.txt"}]
    msgs, _, meta = asyncio.run(_build_context({"id": 1}, body, cfg, att_rows=att_rows))
    assert meta["web"]["sources"] == []
    assert meta["web"]["skipped"]
    assert "联网已跳过" in msgs[0]["content"]
    assert "附件正文" in msgs[-1]["content"]


