"""Radar fetch failures must be explicit, retried once, and visible to the owner."""
from __future__ import annotations

import copy

import httpx
import pytest

from app import editorial, main, pipeline, store


class Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://example.invalid/")
            raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(self.status_code, request=req))


def html_page(body: str, title: str = "測試標題", script: str = "") -> str:
    return f"<html><head><title>{title}</title><script>{script}</script></head><body>{body}</body></html>"


def test_fetch_page_normal_html_returns_text(monkeypatch):
    raw = html_page("正文內容" * 100)
    monkeypatch.setattr(pipeline.httpx, "get", lambda *a, **k: Resp(raw))
    res = pipeline.fetch_page("https://example.com/post", attempts=1)
    assert res["ok"] is True
    assert "測試標題" in res["text"]
    assert "正文內容" in res["text"]
    assert res["attempts"] == 1


def test_fetch_text_returns_failure_marker_for_challenge(monkeypatch):
    raw = "<html><script>var EO_Bot_Ssid='abc';</script><body>請稍候</body></html>"
    monkeypatch.setattr(pipeline.httpx, "get", lambda *a, **k: Resp(raw))
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    text = pipeline.fetch_text("https://aihot.news/")
    assert text.startswith("（抓取失敗：")
    assert "反爬" in text


def test_fetch_page_retries_with_a_different_ua(monkeypatch):
    calls = []
    challenge = "<html><script>EO_Bot_Ssid</script></html>"
    good = html_page("足夠的正文" * 100)
    responses = [Resp(challenge), Resp(good)]

    def fake_get(url, **kwargs):
        calls.append(kwargs["headers"]["User-Agent"])
        return responses[len(calls) - 1]

    sleeps = []
    monkeypatch.setattr(pipeline.httpx, "get", fake_get)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: sleeps.append(s))
    res = pipeline.fetch_page("https://aihot.news/", attempts=2)
    assert res["ok"] is True
    assert res["attempts"] == 2
    assert len(calls) == 2
    assert calls[0] != calls[1]
    assert sleeps == [0.8]


def test_js_rendered_page_says_so(monkeypatch):
    raw = "<html><body><div id='app'></div><script>" + "x" * 6000 + "</script></body></html>"
    monkeypatch.setattr(pipeline.httpx, "get", lambda *a, **k: Resp(raw))
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
    res = pipeline.fetch_page("https://example.com/spa", attempts=1)
    assert res["ok"] is False
    assert "JS" in res["reason"]
    assert "具體文章" in res["reason"]


def test_all_seeds_fail_records_state_and_writes_no_cards(monkeypatch):
    states, saved = [], []
    monkeypatch.setattr(pipeline, "fetch_page", lambda url, limit=3000: {
        "ok": False, "url": url, "text": "", "reason": "反爬挑戰", "attempts": 2, "bytes": 988,
    })
    monkeypatch.setattr(pipeline.store, "save_radar_state", lambda s: states.append(s))
    monkeypatch.setattr(pipeline.store, "save_radar", lambda items: saved.append(items))
    pipeline.run_radar("https://aihot.news/")
    assert saved == []
    assert states[-1]["status"] == "error"
    assert "請改貼具體文章" in states[-1]["message"]
    assert states[-1]["failed_urls"][0]["url"] == "https://aihot.news/"


def test_no_candidates_marks_empty_not_success(monkeypatch):
    states = []
    monkeypatch.setattr(pipeline, "fetch_page", lambda url, limit=3000: {
        "ok": True, "url": url, "text": "正文" * 300, "reason": "", "attempts": 1, "bytes": 1200,
    })
    monkeypatch.setattr(pipeline.store, "save_radar_state", lambda s: states.append(s))
    monkeypatch.setattr(pipeline.store, "get_settings", lambda: copy.deepcopy(store.DEFAULT_SETTINGS))
    monkeypatch.setattr(pipeline.editorial, "radar_scored", lambda *a, **k: [])
    monkeypatch.setattr(pipeline.store, "save_radar", lambda items: pytest.fail("不該寫卡片"))
    pipeline.run_radar("https://example.com/post")
    assert states[-1]["status"] == "empty"
    assert states[-1]["added"] == 0


def test_extract_candidates_empty_input_does_not_raise():
    def empty(task, sys, pr):
        assert task == "radar_candidates"
        return {"candidates": []}

    assert editorial.extract_candidates("", 12, empty) == []


def test_sources_endpoint_is_not_shadowed(client, monkeypatch):
    monkeypatch.setattr(main.sources, "overview", lambda probe_all=True: {"visuals": {"ok": True}})
    r = client.get("/api/sources")
    assert r.status_code == 200, r.text
    assert "visuals" in r.json()


def test_radar_state_endpoint(client):
    r = client.get("/api/radar/state")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
