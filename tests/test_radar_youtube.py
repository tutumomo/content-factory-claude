"""YouTube links in the radar: yt-dlp metadata + subtitles, Data API fallback, clear errors.

Nothing here reaches YouTube: yt_dlp.YoutubeDL, the subtitle download and the Data API call are
all fakes.
"""
from __future__ import annotations

import copy
import json
import time

import httpx
import pytest
import yt_dlp

from app import pipeline, store, youtube, yt_page

VID = "6oM6gawZ-sQ"


# ---------- links ----------

@pytest.mark.parametrize("url,vid,plist", [
    (f"https://www.youtube.com/watch?v={VID}", VID, ""),
    (f"https://youtube.com/watch?v={VID}&pp=ygUEdGVzdA%3D%3D", VID, ""),
    (f"https://www.youtube.com/watch?feature=share&v={VID}&t=42s", VID, ""),
    (f"https://m.youtube.com/watch?v={VID}", VID, ""),
    (f"https://youtu.be/{VID}?si=abcdef", VID, ""),
    (f"https://www.youtube.com/shorts/{VID}", VID, ""),
    (f"https://www.youtube.com/live/{VID}?feature=shared", VID, ""),
    (f"https://www.youtube.com/embed/{VID}", VID, ""),
    (f"https://music.youtube.com/watch?v={VID}", VID, ""),
    (f"https://www.youtube.com/watch?v={VID}&list=PLabc123", VID, "PLabc123"),
    ("https://www.youtube.com/playlist?list=PLabc123", "", "PLabc123"),
    ("https://youtube.com/shorts/" + VID, VID, ""),
    ("https://youtube.com/live/" + VID, VID, ""),
    (f"https://m.youtube.com/shorts/{VID}?feature=share", VID, ""),
    # short / truncated ids still count as YouTube links, so yt-dlp can say the id is incomplete
    ("https://www.youtube.com/shorts/abc123", "abc123", ""),
    ("https://youtube.com/shorts/abc123", "abc123", ""),
    ("https://www.youtube.com/live/abc123", "abc123", ""),
    ("https://youtube.com/live/abc123?si=x", "abc123", ""),
    ("https://m.youtube.com/watch?v=abc123", "abc123", ""),
])
def test_youtube_links_are_recognised(url, vid, plist):
    assert yt_page.is_youtube_url(url)
    assert yt_page.parse_url(url) == {"id": vid, "list": plist}


@pytest.mark.parametrize("url", [
    "https://example.com/watch?v=6oM6gawZ-sQ",
    "https://notyoutube.com/watch?v=6oM6gawZ-sQ",
    "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/shorts/",
    "https://www.youtube.com/live/",
    "https://www.youtube.com/watch?v=",
    "https://www.youtube.com/shorts/abc!123",
    "https://aihot.news/",
    "ftp://youtu.be/6oM6gawZ-sQ",
])
def test_other_links_are_not_youtube(url):
    assert not yt_page.is_youtube_url(url)


# ---------- fakes ----------

@pytest.fixture(autouse=True)
def _no_asr(monkeypatch):
    """No speech-to-text unless a test asks for it (it would download audio and call audio.cpp)."""
    monkeypatch.setattr(yt_page, "asr_transcript", lambda *a, **k: ("", "", ""))


def info(**kw) -> dict:
    base = {"id": VID, "title": "測試影片標題", "channel": "測試頻道", "upload_date": "20261120",
            "duration": 754, "description": "這是影片說明。" * 10, "chapters": [
                {"start_time": 0, "title": "開場"}, {"start_time": 90, "title": "重點"}],
            "subtitles": {}, "automatic_captions": {}}
    base.update(kw)
    return base


def fake_ydl(monkeypatch, result=None, error: Exception | None = None, delay: float = 0, seen=None):
    class FakeYDL:
        def __init__(self, opts):
            if seen is not None:
                seen.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=True):
            assert download is False, "不可下載影片"
            if delay:
                time.sleep(delay)
            if error:
                raise error
            return copy.deepcopy(result(url) if callable(result) else result)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)


class Resp:
    def __init__(self, text: str = "", status: int = 200, data=None):
        self.text = text if data is None else json.dumps(data)
        self.status_code = status
        self._data = data

    def json(self):
        return self._data if self._data is not None else json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", "https://example.invalid/")
            raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(self.status_code, request=req))


def fake_http(monkeypatch, routes: dict, calls=None):
    def get(url, **kw):
        if calls is not None:
            calls.append((url, kw))
        for prefix, resp in routes.items():
            if url.startswith(prefix):
                return resp(url, kw) if callable(resp) else resp
        raise AssertionError(f"不該連到 {url}")

    monkeypatch.setattr(yt_page.httpx, "get", get)


def no_google(monkeypatch):
    def nope():
        raise youtube.YouTubeError("還沒登入")
    monkeypatch.setattr(youtube, "_access_token", nope)


VTT = """WEBVTT
Kind: captions
Language: zh-Hant

00:00:00.000 --> 00:00:02.000 align:start position:0%
大家好<00:00:01.000><c>，今天聊</c>

00:00:02.000 --> 00:00:04.000
大家好，今天聊
大家好，今天聊新的開源模型

00:00:04.000 --> 00:00:06.000
它在本機就能跑
"""

JSON3 = {"events": [{"tStartMs": 0, "segs": [{"utf8": "hello everyone"}]},
                    {"tStartMs": 900, "segs": [{"utf8": "\n"}]},
                    {"tStartMs": 1000, "segs": [{"utf8": "today we test "}, {"utf8": "a new model"}]}]}


# ---------- subtitles ----------

def test_manual_zh_hant_subtitles_become_the_page_text(monkeypatch):
    seen = []
    fake_ydl(monkeypatch, info(subtitles={
        "en": [{"ext": "vtt", "url": "https://subs.invalid/en.vtt"}],
        "zh-Hant": [{"ext": "srv3", "url": "https://subs.invalid/zh.srv3"},
                    {"ext": "vtt", "url": "https://subs.invalid/zh.vtt"}],
    }), seen=seen)
    calls = []
    fake_http(monkeypatch, {"https://subs.invalid/zh.vtt": Resp(VTT)}, calls)
    res = pipeline.fetch_page(f"https://youtu.be/{VID}", 3000)
    assert res["ok"] is True
    assert res["source"] == "yt-dlp"
    assert res["subtitle"] == "人工字幕（zh-Hant）"
    assert res["note"] == ""
    text = res["text"]
    assert "標題：測試影片標題" in text and "頻道：測試頻道" in text
    assert "發布日期：2026-11-20" in text and "片長：12:34" in text
    assert "大家好，今天聊新的開源模型" in text and "它在本機就能跑" in text
    assert "-->" not in text and "<c>" not in text
    assert text.count("大家好") == 1          # rolling repeats collapsed
    assert "1:30 重點" in text
    assert [c[0] for c in calls] == ["https://subs.invalid/zh.vtt"]
    opts = seen[0]
    assert opts["skip_download"] is True and opts["socket_timeout"] == yt_page.SOCKET_TIMEOUT_S
    assert "cookiefile" not in opts


def test_radar_scores_a_youtube_link(monkeypatch):
    fake_ydl(monkeypatch, info(subtitles={"zh-TW": [{"ext": "vtt", "url": "https://subs.invalid/a.vtt"}]}))
    fake_http(monkeypatch, {"https://subs.invalid/": Resp(VTT)})
    states, saved, got = [], [], {}
    monkeypatch.setattr(pipeline.store, "save_radar_state", lambda s: states.append(s))
    monkeypatch.setattr(pipeline.store, "get_settings", lambda: copy.deepcopy(store.DEFAULT_SETTINGS))
    monkeypatch.setattr(pipeline.store, "get_radar", lambda: [])
    monkeypatch.setattr(pipeline.store, "save_radar", lambda items: saved.append(items))

    def scored(text, lo, hi, cfg):
        got["text"] = text
        return [{"title": "開源模型本機跑", "score": 80}]

    monkeypatch.setattr(pipeline.editorial, "radar_scored", scored)
    pipeline.run_radar(f"https://www.youtube.com/watch?v={VID}&pp=abc")
    assert "它在本機就能跑" in got["text"]
    assert "抓取失敗" not in got["text"]
    assert states[-1]["status"] == "ok" and states[-1]["added"] == 1
    assert saved and saved[0][0]["title"] == "開源模型本機跑"


def test_auto_english_captions_are_used_and_labelled(monkeypatch):
    fake_ydl(monkeypatch, info(automatic_captions={
        "zh-Hant": [{"ext": "json3", "url": "https://subs.invalid/tr-zh.json3"}],   # machine translation
        "en-orig": [{"ext": "json3", "url": "https://subs.invalid/en.json3"}],
        "en": [{"ext": "json3", "url": "https://subs.invalid/en-tr.json3"}],
    }))
    fake_http(monkeypatch, {"https://subs.invalid/en.json3": Resp(data=JSON3)})
    res = yt_page.fetch(f"https://www.youtube.com/watch?v={VID}")
    assert res["ok"] is True
    assert res["subtitle"] == "自動字幕（en）"
    assert "字幕來源：自動字幕（en）" in res["text"]
    assert "hello everyone\ntoday we test a new model" in res["text"]


def test_auto_captions_fall_back_to_the_next_track_when_one_fails(monkeypatch):
    fake_ydl(monkeypatch, info(automatic_captions={
        "zh-Hant": [{"ext": "json3", "url": "https://subs.invalid/zh.json3"}],
        "en": [{"ext": "json3", "url": "https://subs.invalid/en.json3"}],
    }))
    fake_http(monkeypatch, {"https://subs.invalid/zh.json3": Resp("", 429),
                            "https://subs.invalid/en.json3": Resp(data=JSON3)})
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert res["subtitle"] == "自動字幕（en）"


def test_no_subtitles_uses_the_description_and_says_so(monkeypatch):
    fake_ydl(monkeypatch, info())
    fake_http(monkeypatch, {})
    res = yt_page.fetch(f"https://www.youtube.com/shorts/{VID}")
    assert res["ok"] is True
    assert res["note"] == "這支影片沒有字幕，只用說明文字"
    assert "這是影片說明。" in res["text"]
    assert "字幕來源：沒有字幕，只用說明文字" in res["text"]
    assert "## 逐字稿" not in res["text"]


def test_radar_message_mentions_missing_subtitles(monkeypatch):
    fake_ydl(monkeypatch, info())
    fake_http(monkeypatch, {})
    states = []
    monkeypatch.setattr(pipeline.store, "save_radar_state", lambda s: states.append(s))
    monkeypatch.setattr(pipeline.store, "get_settings", lambda: copy.deepcopy(store.DEFAULT_SETTINGS))
    monkeypatch.setattr(pipeline.store, "get_radar", lambda: [])
    monkeypatch.setattr(pipeline.store, "save_radar", lambda items: None)
    monkeypatch.setattr(pipeline.editorial, "radar_scored", lambda *a, **k: [{"title": "x"}])
    pipeline.run_radar(f"https://youtu.be/{VID}")
    assert states[-1]["status"] == "ok"
    assert "這支影片沒有字幕，只用說明文字" in states[-1]["message"]


def test_playlist_link_reads_its_first_video(monkeypatch):
    seen_urls = []

    def result(url):
        seen_urls.append(url)
        if "playlist" in url:
            return {"_type": "playlist", "entries": [{"id": VID, "title": "第一支"}, {"id": "zzzzzzzzzzz"}]}
        return info()

    fake_ydl(monkeypatch, result)
    fake_http(monkeypatch, {})
    res = yt_page.fetch("https://www.youtube.com/playlist?list=PLabc123")
    assert res["ok"] is True
    assert seen_urls[-1] == yt_page.watch_url(VID)


def test_cookie_file_is_passed_when_present(monkeypatch, tmp_path):
    ck = tmp_path / "cookies.txt"
    ck.write_text("# Netscape HTTP Cookie File\n")
    s = copy.deepcopy(store.DEFAULT_SETTINGS)
    s["youtube"]["cookies_file"] = str(ck)
    monkeypatch.setattr(yt_page.store, "get_settings", lambda: s)
    seen = []
    fake_ydl(monkeypatch, info(), seen=seen)
    fake_http(monkeypatch, {})
    yt_page.fetch(f"https://youtu.be/{VID}")
    assert seen[0]["cookiefile"] == str(ck)


# ---------- errors ----------

@pytest.mark.parametrize("err,kind,words", [
    ("ERROR: [youtube] 6oM6gawZ-sQ: Private video. Sign in if you've been granted access to this video",
     "private", "私人影片"),
    ("ERROR: [youtube] 6oM6gawZ-sQ: Video unavailable. This video has been removed by the uploader",
     "removed", "已刪除"),
    ("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable", "removed", "已刪除"),
    ("ERROR: [youtube] 6oM6gawZ-sQ: Sign in to confirm your age. This video may be inappropriate for some users.",
     "age", "年齡限制"),
    ("ERROR: [youtube] 6oM6gawZ-sQ: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies",
     "login", "cookies"),
    ("ERROR: [youtube] 6oM6gawZ-sQ: Join this channel to get access to members-only content",
     "members", "會員限定"),
    ("ERROR: [youtube:truncated_id] abc123: Incomplete YouTube ID abc123. URL https://www.youtube.com/watch?v=abc123 looks truncated.",
     "truncated", "影片 ID 不完整"),
    ("ERROR: [youtube] 6oM6gawZ-sQ: Unable to extract player response; please report this issue",
     "other", "這支影片取不到中繼資料：Unable to extract player response"),
])
def test_yt_dlp_errors_are_named(monkeypatch, err, kind, words):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError(err))
    no_google(monkeypatch)
    res = pipeline.fetch_page(f"https://www.youtube.com/watch?v={VID}", 3000)
    assert res["ok"] is False
    assert res["kind"] == kind
    assert words in res["reason"]
    assert "反爬" not in res["reason"]
    assert "ERROR:" not in res["reason"] and "[youtube]" not in res["reason"]


def test_login_error_explains_how_to_give_cookies(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError("ERROR: [youtube] x: Sign in to confirm you’re not a bot"))
    no_google(monkeypatch)
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert "Sign in to confirm" in res["reason"]
    assert "youtube_cookies.txt" in res["reason"] and "Netscape" in res["reason"]
    assert "跳過 YouTube Data API 備援" in res["note"]


def test_timeout_does_not_hang_the_scan(monkeypatch):
    monkeypatch.setattr(yt_page, "EXTRACT_TIMEOUT_S", 0.3)
    fake_ydl(monkeypatch, info(), delay=3)
    no_google(monkeypatch)
    t0 = time.time()
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert time.time() - t0 < 2
    assert res["ok"] is False and res["kind"] == "timeout"
    assert "沒有回應" in res["reason"]


def test_radar_youtube_failure_does_not_say_anti_bot_or_article(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError("ERROR: [youtube] x: Private video"))
    no_google(monkeypatch)
    states = []
    monkeypatch.setattr(pipeline.store, "save_radar_state", lambda s: states.append(s))
    monkeypatch.setattr(pipeline.store, "save_radar", lambda items: pytest.fail("不該寫卡片"))
    pipeline.run_radar(f"https://www.youtube.com/watch?v={VID}")
    msg = states[-1]["message"]
    assert states[-1]["status"] == "error"
    assert "私人影片" in msg
    assert "反爬" not in msg and "具體文章網址" not in msg


# ---------- Data API fallback ----------

API_ITEM = {"items": [{"id": VID, "snippet": {"title": "API 標題", "channelTitle": "API 頻道",
                                              "publishedAt": "2026-11-20T08:00:00Z",
                                              "description": "API 說明文字"},
                       "contentDetails": {"duration": "PT1H2M3S"}}]}


def test_data_api_fills_in_when_yt_dlp_fails(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError("ERROR: [youtube] x: Sign in to confirm you’re not a bot"))
    monkeypatch.setattr(youtube, "_access_token", lambda: "tok-SECRET")
    calls = []
    fake_http(monkeypatch, {yt_page.VIDEOS_API: Resp(data=API_ITEM)}, calls)
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert res["ok"] is True and res["source"] == "youtube-data-api"
    assert "標題：API 標題" in res["text"] and "片長：1:02:03" in res["text"]
    assert "API 說明文字" in res["text"]
    assert "只有說明文字" in res["note"] and "沒有字幕" in res["note"]
    url, kw = calls[0]
    assert kw["params"] == {"part": "snippet,contentDetails", "id": VID}
    assert kw["headers"]["Authorization"] == "Bearer tok-SECRET"
    assert "tok-SECRET" not in json.dumps(res, ensure_ascii=False)


def test_data_api_is_skipped_without_a_google_login(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError("ERROR: [youtube] x: Unable to extract"))
    no_google(monkeypatch)
    fake_http(monkeypatch, {})   # any HTTP call would fail the test
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert res["ok"] is False
    assert res["reason"].startswith("這支影片取不到中繼資料：")
    assert "跳過 YouTube Data API 備援" in res["note"]


def test_data_api_errors_never_leak_the_token(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError("ERROR: [youtube] x: Unable to extract"))
    monkeypatch.setattr(youtube, "_access_token", lambda: "tok-SECRET")
    fake_http(monkeypatch, {yt_page.VIDEOS_API: Resp(status=403, data={"error": {
        "message": "Request had insufficient authentication scopes.",
        "errors": [{"reason": "insufficientPermissions"}]}})})
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert res["ok"] is False
    assert "重新登入" in res["note"]
    assert "tok-SECRET" not in json.dumps(res, ensure_ascii=False)


def test_private_video_does_not_try_the_api(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError("ERROR: [youtube] x: Private video"))
    monkeypatch.setattr(youtube, "_access_token", lambda: pytest.fail("私人影片不用再問 API"))
    res = yt_page.fetch(f"https://youtu.be/{VID}")
    assert res["kind"] == "private"


@pytest.mark.parametrize("url,vid", [
    (f"https://www.youtube.com/shorts/{VID}", VID),
    (f"https://youtube.com/shorts/{VID}", VID),
    (f"https://www.youtube.com/live/{VID}", VID),
    (f"https://youtube.com/live/{VID}", VID),
    ("https://www.youtube.com/shorts/abc123", "abc123"),
    ("https://youtube.com/live/abc123", "abc123"),
])
def test_shorts_and_live_go_to_yt_dlp_not_html(monkeypatch, url, vid):
    monkeypatch.setattr(pipeline.httpx, "get", lambda *a, **k: pytest.fail("不該走一般 HTML 抓取"))
    asked = []
    fake_ydl(monkeypatch, lambda u: (asked.append(u), info(id=vid))[1])
    fake_http(monkeypatch, {})
    res = pipeline.fetch_page(url, 3000)
    assert res["ok"] is True and res["source"] == "yt-dlp"
    assert asked == [yt_page.watch_url(vid)]


def test_truncated_id_says_so_and_skips_the_api(monkeypatch):
    fake_ydl(monkeypatch, error=yt_dlp.utils.DownloadError(
        "ERROR: [youtube:truncated_id] abc123: Incomplete YouTube ID abc123. URL looks truncated."))
    monkeypatch.setattr(youtube, "_access_token", lambda: pytest.fail("ID 不完整不用再問 API"))
    res = pipeline.fetch_page("https://www.youtube.com/shorts/abc123", 3000)
    assert res["ok"] is False and res["kind"] == "truncated"
    assert "11 碼" in res["reason"] and "反爬" not in res["reason"]


# ---------- web pages unchanged ----------

def test_non_youtube_links_still_use_http(monkeypatch):
    monkeypatch.setattr(yt_page, "fetch", lambda *a, **k: pytest.fail("不該走 YouTube"))
    body = "<html><head><title>T</title></head><body>" + "正文" * 200 + "</body></html>"

    class R:
        text = body
        content = body.encode()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(pipeline.httpx, "get", lambda *a, **k: R())
    res = pipeline.fetch_page("https://example.com/post", attempts=1)
    assert res["ok"] is True and "正文" in res["text"]
