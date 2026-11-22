"""One voice dropdown: /api/tts/voices proxy, /api/tts/test, the field media.tts sends,
settings migration from the deprecated tts.ref_voice, and the 繁轉簡 toggle.

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


def _server(task: str = "clon", voices=("speaker-a", "vivian", "speaker-b"), models: str = "index-tts2.5"):
    """Route /v1/models to one row with `task`, everything else to the voice list."""
    calls = {"models": 0, "voices": 0}

    def fake_get(url, **kw):
        if url.endswith("/v1/models"):
            calls["models"] += 1
            return _Resp(payload={"data": [{"id": models, "task": task}]})
        calls["voices"] += 1
        assert kw.get("params") == {"model": models}
        return _Resp(payload={"voices": list(voices)})

    return fake_get, calls


@pytest.fixture(autouse=True)
def _clean_settings():
    """Every test starts from the shipped defaults, then restores whatever was there."""
    before = store.get_settings()
    yield
    store.save_settings(before)


# ---------- GET /api/tts/voices ----------

def test_voices_proxy_returns_library_for_clon(client, monkeypatch):
    fake_get, calls = _server(task="clon")
    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    set_settings(client, tts={"base_url": "http://127.0.0.1:8090", "model": "index-tts2.5"})
    r = client.get("/api/tts/voices?model=index-tts2.5")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert body["kind"] == "library"
    assert body["task"] == "clon"
    assert body["voices"] == ["speaker-a", "speaker-b"]  # builtin preset names are not library voices
    assert calls == {"models": 1, "voices": 1}


def test_voices_proxy_returns_builtin_for_customvoice(client, monkeypatch):
    fake_get, calls = _server(task="tts", models="qwen3-tts-1.7b-customvoice")
    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    body = client.get("/api/tts/voices?model=qwen3-tts-1.7b-customvoice").json()
    assert body["kind"] == "builtin"
    assert "vivian" in body["voices"]
    assert body["error"] is None
    assert calls["voices"] == 0  # audio.cpp returns the same library for every model; don't ask


def test_voices_proxy_reports_server_down(client, monkeypatch):
    def fake_get(url, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    r = client.get("/api/tts/voices?model=index-tts2.5")
    assert r.status_code == 200
    body = r.json()
    assert body["voices"] == []
    assert "讀不到" in body["error"]


def test_voices_proxy_reports_empty_library(client, monkeypatch):
    fake_get, _ = _server(voices=())
    monkeypatch.setattr(media, "httpx", _FakeHttpx(get=fake_get))
    body = client.get("/api/tts/voices?model=index-tts2.5").json()
    assert body["voices"] == []
    assert "沒有回傳任何參考聲音" in body["error"]


# ---------- POST /api/tts/test ----------

def test_test_endpoint_returns_wav(client, monkeypatch):
    body_seen = {}

    def fake_post(url, **kw):
        body_seen.update(kw.get("json") or {})
        return _Resp(status_code=200, content=b"RIFF" + b"\0" * 64)

    monkeypatch.setattr(media, "httpx", _FakeHttpx(post=fake_post))
    r = client.post("/api/tts/test", json={"text": "測試一句", "tts": {"model": "index-tts2.5", "voice": "speaker-a"}})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content.startswith(b"RIFF")
    assert body_seen["voice"] == "speaker-a"
    assert body_seen["input"] == "测试一句"  # default convert_simplified=True


def test_test_endpoint_surfaces_audio_cpp_error(client, monkeypatch):
    raw = '{"error":{"message":"IndexTTS2 request requires --voice-ref or voice.speaker.audio"}}'
    monkeypatch.setattr(media, "httpx", _FakeHttpx(post=lambda url, **kw: _Resp(status_code=500, content=raw.encode())))
    r = client.post("/api/tts/test", json={"tts": {"model": "index-tts2.5"}})
    assert r.status_code == 502
    assert "IndexTTS2 request requires --voice-ref" in r.json()["detail"]


# ---------- settings migration: one voice field ----------

def _write_settings(tts: dict) -> None:
    s = store.get_settings()
    s["tts"] = {**s["tts"], **tts}
    (store.DATA / "settings.json").write_text(json.dumps(s, ensure_ascii=False))


def test_old_settings_only_voice(client):
    _write_settings({"voice": "vivian", "ref_voice": ""})
    assert store.get_settings()["tts"]["voice"] == "vivian"


def test_old_settings_only_ref_voice_becomes_voice(client):
    _write_settings({"voice": "", "ref_voice": "speaker-a"})
    assert store.get_settings()["tts"]["voice"] == "speaker-a"


def test_old_settings_both_keep_voice(client):
    _write_settings({"voice": "speaker-b", "ref_voice": "speaker-a"})
    tts = store.get_settings()["tts"]
    assert tts["voice"] == "speaker-b"  # the unified field wins; the deprecated one is untouched
    assert tts["ref_voice"] == "speaker-a"


def test_old_settings_without_ref_voice_still_load(client):
    s = store.get_settings()
    del s["tts"]["ref_voice"]
    (store.DATA / "settings.json").write_text(json.dumps(s, ensure_ascii=False))
    raw = json.loads((store.DATA / "settings.json").read_text())
    assert "ref_voice" not in raw["tts"]
    assert store.get_settings()["tts"]["ref_voice"] == ""


# ---------- what media.tts sends ----------

def _capture_tts_request(monkeypatch) -> dict:
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw.get("json") or {})
        return _Resp(status_code=200, content=b"RIFF" + b"\0" * 64)

    monkeypatch.setattr(media, "_post_busy_retry", fake_post)
    return seen


def test_media_tts_sends_voice_for_clon(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "speaker-a", "ref_voice": ""})
    seen = _capture_tts_request(monkeypatch)
    out = media.tts("測試一句", tmp_path / "a.wav")
    assert out.exists()
    assert seen["voice"] == "speaker-a"
    assert seen["model"] == "index-tts2.5"


def test_media_tts_uses_deprecated_ref_voice_when_voice_empty(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "", "ref_voice": "speaker-a"})
    seen = _capture_tts_request(monkeypatch)
    media.tts("測試一句", tmp_path / "a2.wav")
    assert seen["voice"] == "speaker-a"


def test_media_tts_without_voice_sends_no_voice(client, monkeypatch, tmp_path):
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

    set_settings(client, tts={"voice": "speaker-a"})
    assert media.tts_health()["needs_voice_ref"] is False


# ---------- 繁轉簡 toggle ----------

ZH = "臺灣的軟體發展與網路資訊"
ZH_SIMPLIFIED = "台湾的软件发展与网络信息"


def test_convert_simplified_on_converts_request_input(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "speaker-a",
                              "language": "chinese", "convert_simplified": True})
    seen = _capture_tts_request(monkeypatch)
    media.tts(ZH, tmp_path / "zh.wav")
    assert seen["input"] == ZH_SIMPLIFIED


def test_convert_simplified_off_keeps_traditional(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "speaker-a",
                              "language": "chinese", "convert_simplified": False})
    seen = _capture_tts_request(monkeypatch)
    media.tts(ZH, tmp_path / "zh2.wav")
    assert seen["input"] == ZH


def test_convert_simplified_skipped_for_non_chinese(client, monkeypatch, tmp_path):
    set_settings(client, tts={"model": "index-tts2.5", "voice": "speaker-a",
                              "language": "english", "convert_simplified": True})
    seen = _capture_tts_request(monkeypatch)
    media.tts(ZH, tmp_path / "zh3.wav")
    assert seen["input"] == ZH


def test_test_endpoint_honours_convert_toggle(client, monkeypatch):
    body_seen = {}

    def fake_post(url, **kw):
        body_seen.update(kw.get("json") or {})
        return _Resp(status_code=200, content=b"RIFF" + b"\0" * 64)

    monkeypatch.setattr(media, "httpx", _FakeHttpx(post=fake_post))
    base = {"model": "index-tts2.5", "voice": "speaker-a", "language": "chinese"}
    client.post("/api/tts/test", json={"text": ZH, "tts": {**base, "convert_simplified": True}})
    assert body_seen["input"] == ZH_SIMPLIFIED
    client.post("/api/tts/test", json={"text": ZH, "tts": {**base, "convert_simplified": False}})
    assert body_seen["input"] == ZH


def test_settings_key_names_match_ui_and_media():
    """The toggle the modal writes must be the key media reads (guards against A/B rename drift)."""
    assert "convert_simplified" in store.DEFAULT_SETTINGS["tts"]
    js = (store.ROOT / "static" / "modals.js").read_text(encoding="utf-8")
    assert 'id="t-convert_simplified"' in js
    assert 's.tts.convert_simplified = $("#t-convert_simplified", root).checked' in js
