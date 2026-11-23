"""Watched sources: schedule maths, feed/link discovery, and a scan that only sends new items."""
from datetime import datetime

import pytest

from app import llm, pipeline, store, watch

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>T</title>
<item><title><![CDATA[模型 A 發布]]></title><link>https://hot.example/items/a</link>
<description><![CDATA[<p>摘要 A</p><p><a href="https://orig.example/a">閱讀原文</a></p>]]></description>
<guid>a</guid><pubDate>Mon, 23 Nov 2026 09:42:11 GMT</pubDate></item>
<item><title>產品 B 更新</title><link>https://hot.example/items/b</link><description>摘要 B</description><guid>b</guid></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>X</title>
<entry><title>Atom 一則</title><link rel="alternate" href="/posts/1"/><id>tag:1</id>
<summary>內容</summary><updated>2026-11-23T01:00:00Z</updated></entry></feed>"""


def ts(*a):
    return datetime(*a).timestamp()


def test_next_run_daily_today_or_tomorrow():
    s = {"freq": "daily", "time": "06:00"}
    assert watch.next_run(s, ts(2026, 11, 23, 5, 0)) == ts(2026, 11, 23, 6, 0)
    assert watch.next_run(s, ts(2026, 11, 23, 6, 0)) == ts(2026, 11, 24, 6, 0)


def test_next_run_weekdays_skips_weekend():
    s = {"freq": "weekdays", "time": "06:00"}
    # 2026-11-27 is a Friday
    assert watch.next_run(s, ts(2026, 11, 27, 7, 0)) == ts(2026, 11, 30, 6, 0)


def test_next_run_weekly_and_hours():
    assert watch.next_run({"freq": "weekly", "time": "08:30", "weekday": 2}, ts(2026, 11, 23, 9, 0)) \
        == ts(2026, 11, 25, 8, 30)
    assert watch.next_run({"freq": "hours", "every_hours": 3}, 1000.0) == 1000.0 + 3 * 3600


def test_parse_rss_keeps_original_link():
    items = watch.parse_feed(RSS, "https://hot.example/feed.xml")
    assert [i["title"] for i in items] == ["模型 A 發布", "產品 B 更新"]
    assert items[0]["original"] == "https://orig.example/a"
    assert items[0]["summary"].startswith("摘要 A")


def test_parse_atom_resolves_relative_link():
    items = watch.parse_feed(ATOM, "https://blog.example/feed")
    assert items[0]["link"] == "https://blog.example/posts/1"
    assert items[0]["key"] == "tag:1"


def test_page_links_same_site_only():
    page = ('<a href="/">首頁</a><a href="/news/1">這是一篇夠長的新聞標題</a>'
            '<a href="https://other.example/x">外站的一篇夠長文章標題</a><a href="/news/2">短</a>')
    got = watch.page_links(page, "https://site.example/")
    assert [g["link"] for g in got] == ["https://site.example/news/1"]


def test_normalize_rejects_bad_url():
    with pytest.raises(watch.WatchError):
        watch.normalize({"url": "aihot.news"})


def test_due_fires_once_and_skips_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA", tmp_path)
    a = watch.create({"url": "https://a.example/", "freq": "daily", "time": "06:00"})
    b = watch.create({"url": "https://b.example/", "enabled": False})
    later = a["next_run"] + 10
    assert watch.due(later) == [a["id"]]
    assert watch.due(later) == []  # already advanced to the next day
    assert b["id"] not in watch.due(later + 10 * 86400)


def test_run_sends_only_new_items(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA", tmp_path)
    src = watch.create({"url": "https://hot.example/", "max_items": 10})
    items = watch.parse_feed(RSS, "https://hot.example/feed.xml")
    monkeypatch.setattr(watch, "discover", lambda url, feed="": (items, "https://hot.example/feed.xml", "RSS"))
    sent = []
    monkeypatch.setattr(pipeline, "radar_rows", lambda text: sent.append(text) or [{"title": "卡片", "format": "short"}])
    watch.run(src["id"])
    assert "模型 A 發布" in sent[0] and "原文：https://orig.example/a" in sent[0]
    cards = [c for c in store.get_radar() if c["kind"] == "watch"]
    assert cards and cards[0]["source"] == "hot.example"
    assert watch.get(src["id"])["last_status"] == "ok"
    watch.run(src["id"])  # same feed again: nothing new, no model call
    assert len(sent) == 1
    assert watch.get(src["id"])["last_status"] == "empty"


def test_run_llm_failure_keeps_items_unseen(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA", tmp_path)
    src = watch.create({"url": "https://hot.example/"})
    items = watch.parse_feed(RSS, "https://hot.example/feed.xml")
    monkeypatch.setattr(watch, "discover", lambda url, feed="": (items, "", "RSS"))

    def boom(text):
        raise llm.LLMError("down")
    monkeypatch.setattr(pipeline, "radar_rows", boom)
    watch.run(src["id"])
    s = watch.get(src["id"])
    assert s["last_status"] == "error" and s["seen"] == []
