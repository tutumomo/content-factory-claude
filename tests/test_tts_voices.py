"""參考聲音 dropdown: /api/tts/voices proxy, /api/tts/test endpoint, and the field media.tts sends.

Run:  .venv/bin/python -m pytest tests/test_tts_voices.py -q
"""
from __future__ import annotations

import json

import httpx
import pytest

from app import media, store

from .conftest import set_settings


class _Resp:
    def __init__(self, status_code: int = 200, payload=None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.text = content.decode("utf-8", "replace")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("GET", "http://x"), response=None)


class _FakeHttpx:
    """Stands in for the `httpx` module inside media.py only, so TestClient keeps the real one."""

    HTTPError = httpx.HTTPError

    def __init__(self, get=None, post=None):
        self._get, self._post = get, post

    def get(self, *a, **kw):
        return self._get(*a, **kw)

    def post(self, *a, **kw):
        return self._post(*a, **kw)


@pytest.fixture(autouse=True)
def _clean_settings():
    """Every test starts from the shipped defaults, then restores whatever was there."""
    before = store.get_settings()
    yield
    store.save_settings(before)


# ---------- GET /api/tts/voices ----------

def test_voices_proxy_returns_library(client, monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen["url"], seen["params"] = url, kw.get("params")
        return _Resp(payload={"voices": ["speaker-a", "vivian", "speaker-b"]})

    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    set_settings(client, tts={"base_url": "http://127.0.0.1:8090", "model": "index-tts2.5"})
    r = client.get("/api/tts/voices?model=index-tts2.5")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["voices"] == ["speaker-a", "speaker-b"]  # builtin preset names are not library voices
    assert body["model"] == "index-tts2.5"
    assert seen["url"].endswith("/v1/audio/voices")
    assert seen["params"] == {"model": "index-tts2.5"}


def test_voices_proxy_reports_server_down(client, monkeypatch):
    def fake_get(url, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    r = client.get("/api/tts/voices")
    assert r.status_code == 200
    body = r.json()
    assert body["voices"] == []
    assert "讀不到" in body["error"]


def test_voices_proxy_reports_empty_library(client, monkeypatch):
    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=lambda url, **kw: _Resp(payload={"voices": []})))
    body = client.get("/api/tts/voices").json()
    assert body["voices"] == []
    assert "沒有回傳任何參考聲音" in body["error"]


# ---------- POST /api/tts/test ----------

def test_test_endpoint_returns_wav(client, monkeypatch):
    body_seen = {}

    def fake_post(url, **kw):
        body_seen.update(kw.get("json") or {})
        return _Resp(status_code=200, content=b"RIFF" + b"\0" * 64)

    monkeypatch.setattr(media, "httpx", _FakeHttpx(post=fake_post))
    r = client.post("/api/tts/test", json={"text": "測試一句", "tts": {"model": "index-tts2.5", "ref_voice": "speaker-a"}})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content.startswith(b"RIFF")
    assert body_seen["voice"] == "speaker-a"
    assert body_seen["input"] == "測試一句"


def test_test_endpoint_surfaces_audio_cpp_error(client, monkeypatch):
    raw = '{"error":{"message":"IndexTTS2 request requires --voice-ref or voice.speaker.audio"}}'
    monkeypatch.setattr(media, "httpx", _FakeHttpx(post=lambda url, **kw: _Resp(status_code=500, content=raw.encode())))
    r = client.post("/api/tts/test", json={"tts": {"model": "index-tts2.5"}})
    assert r.status_code == 502
    assert "IndexTTS2 request requires --voice-ref" in r.json()["detail"]


# ---------- settings compatibility and the narration request ----------

def test_old_settings_without_ref_voice_still_load(client):
    s = client.get("/api/settings").json()
    del s["tts"]["ref_voice"]
    (store.DATA / "settings.json").write_text(json.dumps(s, ensure_ascii=False))
    raw = json.loads((store.DATA / "settings.json").read_text())
    assert "ref_voice" not in raw["tts"]
    assert store.get_settings()["tts"]["ref_voice"] == ""


def _capture_tts_request(monkeypatch) -> dict:
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw.get("json") or {})
        return _Resp(status_code=200, content=b"RIFF" + b"\0" * 64)

    monkeypatch.setattr(media, "_post_busy_retry", fake_post)
    return seen


def test_media_tts_sends_ref_voice(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "vivian", "ref_voice": "speaker-a"})
    seen = _capture_tts_request(monkeypatch)
    out = media.tts("測試一句", tmp_path / "a.wav")
    assert out.exists()
    assert seen["voice"] == "speaker-a"  # reference voice wins over the builtin voice
    assert seen["model"] == "index-tts2.5"


def test_media_tts_without_ref_voice_keeps_old_body(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "", "ref_voice": ""})
    seen = _capture_tts_request(monkeypatch)
    media.tts("測試一句", tmp_path / "b.wav")
    assert "voice" not in seen


def test_health_flags_missing_reference_voice(client, monkeypatch):
    def fake_get(url, **kw):
        if url.endswith("/v1/models"):
            return _Resp(payload={"data": [{"id": "index-tts2.5", "task": "clon"}]})
        return _Resp(payload={"voices": []})

    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    set_settings(client, tts={"model": "index-tts2.5", "voice": "", "voice_ref": "", "ref_voice": ""})
    h = media.tts_health()
    assert h["task"] == "clon"
    assert h["needs_voice_ref"] is True
    assert "參考聲音" in h["detail"]

    set_settings(client, tts={"ref_voice": "speaker-a"})
    assert media.tts_health()["needs_voice_ref"] is False
