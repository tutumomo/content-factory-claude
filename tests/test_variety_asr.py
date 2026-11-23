"""Stock-footage variety (no repeats, several shots per scene, Remotion plays footage),
the YouTube speech-to-text fallback and the reference-video shot list.

No network: provider searches, downloads, yt-dlp and audio.cpp are fakes.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from app import media, pipeline, store, stock, video, video_analysis, yt_page


def clip(path: Path, seconds: float = 4.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc2=size=320x180:rate=30:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
                   check=True)
    return path


def rows(n: int) -> list[dict]:
    return [{"provider": "pexels", "id": i, "url": f"https://example.invalid/{i}.mp4", "height": 1080,
             "duration": 20, "author": "a", "page": "", "license": "L"} for i in range(n)]


@pytest.fixture
def ledger():
    p = store.DATA / stock.USAGE_FILE
    p.unlink(missing_ok=True)
    yield p
    p.unlink(missing_ok=True)


# ---------- stock ranking / ledger ----------

def test_rank_drops_used_and_puts_recent_last():
    r = stock.rank(rows(6), exclude={"pexels:0"}, recent={"pexels:1", "pexels:2"}, seed="s")
    keys = [stock.clip_key(x) for x in r]
    assert "pexels:0" not in keys
    assert set(keys[-2:]) == {"pexels:1", "pexels:2"}


def test_rank_order_depends_on_seed():
    a = [stock.clip_key(x) for x in stock.rank(rows(10), set(), set(), seed="ep1-0")]
    b = [stock.clip_key(x) for x in stock.rank(rows(10), set(), set(), seed="ep2-0")]
    assert sorted(a) == sorted(b) and a != b


def test_ledger_round_trip(ledger):
    stock.mark_used(["pexels:7", ""], "ep-a")
    assert stock.recent_keys(days=30) == {"pexels:7"}
    assert stock.recent_keys(days=30, skip_episode="ep-a") == set()   # re-assembling the same episode
    d = json.loads(ledger.read_text())
    d["pexels:7"][0] = time.time() - 40 * 86400
    ledger.write_text(json.dumps(d))
    assert stock.recent_keys(days=30) == set()


def test_fetch_returns_distinct_shots(monkeypatch, tmp_path):
    monkeypatch.setattr(stock, "search", lambda q, v=False: rows(5))
    monkeypatch.setattr(stock, "_download", lambda c: tmp_path / f"{c['id']}.mp4")
    got = stock.fetch("desk", n=3, exclude={"pexels:0"}, seed="x")
    keys = [s["key"] for s in got["shots"]]
    assert len(keys) == 3 and len(set(keys)) == 3 and "pexels:0" not in keys
    assert got["path"] == got["shots"][0]["path"]


def test_fetch_none_when_everything_excluded(monkeypatch):
    monkeypatch.setattr(stock, "search", lambda q, v=False: rows(2))
    assert stock.fetch("desk", exclude={"pexels:0", "pexels:1"}) is None


# ---------- montage / Remotion ----------

def test_montage_cuts_to_exact_length(tmp_path):
    a, b = clip(tmp_path / "a.mp4", 6), clip(tmp_path / "b.mp4", 2)
    out = media.montage([{"path": a, "duration": 6}, {"path": b, "duration": 2}], 5.0,
                        tmp_path / "m.mp4", (320, 180), seed="t")
    info = media.probe(out)
    assert abs(float(info["format"]["duration"]) - 5.0) < 0.15
    assert not [s for s in info["streams"] if s["codec_type"] == "audio"]


def test_build_props_passes_scene_videos():
    sc = [{"headline": "a"}, {"headline": "b"}]
    p = video.build_props(sc, [], (1280, 720), [2.0, 2.0], imgs=["p00.jpg", "p01.jpg"], videos=["s00.mp4", ""])
    assert p["scenes"][0]["video"] == "s00.mp4" and p["scenes"][1]["video"] == ""
    assert p["scenes"][1]["img"] == "p01.jpg"


def test_shot_seconds_prefers_style_card(monkeypatch):
    monkeypatch.setattr(store, "get_style", lambda sid=None: {"visual_notes": {"avg_shot_seconds": 3.2}})
    assert pipeline._shot_seconds({}, {"stock_shot_seconds": 6}) == 3.2
    monkeypatch.setattr(store, "get_style", lambda sid=None: {"visual_notes": {"avg_shot_seconds": 0.4}})
    assert pipeline._shot_seconds({}, {}) == 2.5
    monkeypatch.setattr(store, "get_style", lambda sid=None: None)
    assert pipeline._shot_seconds({}, {"stock_shot_seconds": 6}) == 6


# ---------- YouTube speech-to-text fallback ----------

class _Resp:
    def __init__(self, status, data):
        self.status_code, self._d = status, data

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _fake_audio(monkeypatch, tmp_path):
    def dl(url, work):
        out = work / "audio.m4a"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=330:duration=1.5", "-c:a", "aac", str(out)], check=True)
        return out
    monkeypatch.setattr(yt_page, "_download_audio", dl)


def test_asr_transcribes_and_caches(monkeypatch, tmp_path):
    _fake_audio(monkeypatch, tmp_path)
    calls = []

    def post(url, wait_total=0, **kw):
        calls.append((url, kw["data"]["model"], kw["files"]["file"][2]))
        return _Resp(200, {"text": "大家好，這是轉出來的逐字稿。"})
    monkeypatch.setattr(media, "_post_busy_retry", post)
    yt_page.asr_cache("vidASR00001").unlink(missing_ok=True)
    text, label, note = yt_page.asr_transcript("vidASR00001", 90)
    assert "逐字稿" in text and "qwen3-asr" in label and "語音轉文字" in note
    assert calls and calls[0][0].endswith("/v1/audio/transcriptions") and calls[0][2] == "audio/wav"
    # second read comes from data/yt_asr, no audio.cpp call
    text2, _, note2 = yt_page.asr_transcript("vidASR00001", 90)
    assert text2 == text and "快取" in note2 and len(calls) == 1
    yt_page.asr_cache("vidASR00001").unlink(missing_ok=True)


def test_asr_skips_long_and_live_and_disabled(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("不該下載")
    monkeypatch.setattr(yt_page, "_download_audio", boom)
    assert "超過" in yt_page.asr_transcript("vidLong0001", 3 * 3600)[2]
    assert "直播" in yt_page.asr_transcript("vidLive0001", 60, live=True)[2]
    monkeypatch.setattr(yt_page, "asr_cfg", lambda: {**yt_page.ASR_DEFAULTS, "asr_fallback": False})
    assert yt_page.asr_transcript("vidOff00001", 60) == ("", "", "")


def test_asr_busy_server_is_a_note_not_a_crash(monkeypatch, tmp_path):
    _fake_audio(monkeypatch, tmp_path)
    monkeypatch.setattr(media, "_post_busy_retry", lambda url, wait_total=0, **kw: _Resp(503, {}))
    text, _, note = yt_page.asr_transcript("vidBusy0001", 60)
    assert text == "" and "忙碌" in note


def test_fetch_uses_asr_when_no_subtitles(monkeypatch):
    info = {"id": "vidFetch001", "title": "T", "duration": 60, "subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr(yt_page, "_with_timeout", lambda fn, t: info)
    monkeypatch.setattr(yt_page, "asr_transcript",
                        lambda vid, dur, live=False: ("轉錄內容", "語音轉文字（m）", "沒有可下載字幕，改用本機語音轉文字"))
    res = yt_page.fetch("https://www.youtube.com/watch?v=vidFetch001")
    assert res["ok"] and "轉錄內容" in res["text"] and res["subtitle"] == "語音轉文字（m）"
    assert "語音轉文字" in res["note"]


# ---------- reference video shot list ----------

def test_analyze_writes_shot_list(monkeypatch, tmp_path):
    src = clip(tmp_path / "ref.mp4", 3)
    st = {"duration": 3.0, "resolution": "320x180", "fps": "30/1", "cuts": 2, "avg_shot": 1.0,
          "cut_density_per_min": 40.0, "longest_shot": 1.2, "shortest_shot": 0.8, "mean_db": -20,
          "cut_times": [1.0, 2.2]}
    monkeypatch.setattr(video_analysis, "stats", lambda p: dict(st))
    monkeypatch.setattr(video_analysis.llm, "complete_json", lambda *a, **k: {"name": "參考"})
    seen = {}
    monkeypatch.setattr(video_analysis.prompts, "style_from_video",
                        lambda s, h: (seen.setdefault("stats", s), "p") and ("sys", "p"))
    monkeypatch.setattr(video_analysis.store, "create_style", lambda c, activate=False: {**c, "id": "style-t"})
    res = video_analysis.analyze(str(src))
    text = (store.DATA / res["shotlist"]).read_text("utf-8")
    assert "| 1 | 1.0 |" in text and "| 2 | 1.2 |" in text and "| 3 | 0.8 |" in text
    assert "cut_times" not in json.loads(seen["stats"])   # the LLM gets the summary, not every cut


# ---------- auto captions in the wrong language ----------

def _track(lang):
    return [{"ext": "vtt", "url": f"https://example.invalid/{lang}.vtt"}]


def test_auto_captions_in_other_language_are_skipped(monkeypatch):
    monkeypatch.setattr(yt_page, "_download_sub", lambda e: "text from " + e["url"])
    info = {"language": "zh-Hant", "subtitles": {},
            "automatic_captions": {"en-orig": _track("en-orig"), "en": _track("en"),
                                   "zh-Hant": _track("zh-Hant"), "zh-Hans": _track("zh-Hans")}}
    assert yt_page.transcript(info) == ("", "")


def test_auto_captions_in_video_language_are_used(monkeypatch):
    monkeypatch.setattr(yt_page, "_download_sub", lambda e: "text from " + e["url"])
    info = {"language": "zh-Hant", "subtitles": {},
            "automatic_captions": {"zh-Hant-orig": _track("zh-Hant-orig"), "en": _track("en")}}
    text, label = yt_page.transcript(info)
    assert "zh-Hant-orig" in text and "zh-Hant" in label


def test_manual_subtitles_ignore_video_language(monkeypatch):
    monkeypatch.setattr(yt_page, "_download_sub", lambda e: "text from " + e["url"])
    info = {"language": "zh-Hant", "subtitles": {"en": _track("en")}, "automatic_captions": {}}
    assert "en.vtt" in yt_page.transcript(info)[0]


# ---------- script shape: opening roadmap, closing pitfall ----------

def test_script_prompt_asks_for_roadmap_and_pitfall():
    from app import prompts
    sysp, _ = prompts.script({"topic": "t", "format": "long", "style_id": None}, {}, "", None)
    assert "路線圖" in sysp and "踩坑" in sysp
