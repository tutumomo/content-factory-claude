"""Read a YouTube link as a "page" for the radar and the sources stage.

YouTube answers a plain HTTP fetch with a consent or bot page, so the normal fetch_page path
finds no text. This module asks the yt-dlp Python module for the video's metadata (no video
download) and turns its subtitles into plain text. When yt-dlp cannot read the video and the
owner is signed in to Google (設定 → YouTube), it falls back to YouTube Data API v3
`videos.list` with that OAuth token: title, description and length only, no subtitles.

The result has the same shape as `pipeline.fetch_page`: ok / url / text / reason / attempts /
bytes, plus `note` (something the owner should know, e.g. "no subtitles") and `source`.
Nothing here writes a token, a client secret or a cookie into a log or an error message.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from . import store

EXTRACT_TIMEOUT_S = 20      # whole extract_info call; the scan goes on without it after this
SOCKET_TIMEOUT_S = 10       # each network read inside yt-dlp
SUB_TIMEOUT_S = 15          # each subtitle file download
API_TIMEOUT_S = 15
MIN_LIMIT = 6000            # a transcript is worth more room than one article excerpt
DESC_LIMIT = 1500
VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
# no downloadable subtitles (none, or YouTube answered 429): local speech-to-text on audio.cpp
ASR_DOWNLOAD_TIMEOUT_S = 300
ASR_CHUNK_S = 600           # audio.cpp gets the audio in 10-minute WAV pieces
ASR_DEFAULTS = {"asr_fallback": True, "asr_model": "qwen3-asr-1-7b-q8-0",
                "asr_max_minutes": 30, "asr_busy_wait_s": 300}

# preferred subtitle languages, best first (keys as yt-dlp reports them)
LANGS = ("zh-Hant", "zh-TW", "zh-HK", "zh", "zh-Hans", "zh-CN", "en", "en-US", "en-GB")
FORMATS = ("json3", "vtt", "srv3", "srv1", "ttml")
COOKIE_FILE_NAME = "youtube_cookies.txt"   # data/youtube_cookies.txt, Netscape format

_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
          "youtube-nocookie.com", "www.youtube-nocookie.com", "youtu.be", "www.youtu.be"}
# Real video ids are 11 characters, but a link on a YouTube host with a shorter or longer id is
# still a YouTube link: send it to yt-dlp, which names a truncated id, instead of the HTML fetch.
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class _Timeout(Exception):
    pass


# ---------- links ----------

def parse_url(url: str) -> dict | None:
    """{"id": video id or "", "list": playlist id or ""} for a YouTube link, else None."""
    try:
        u = urlparse(url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or host not in _HOSTS:
        return None
    q = parse_qs(u.query)
    vid = ""
    parts = [p for p in u.path.split("/") if p]
    if host.endswith("youtu.be"):
        vid = parts[0] if parts else ""
    elif parts and parts[0] in ("shorts", "live", "embed", "v", "e") and len(parts) > 1:
        vid = parts[1]
    elif parts[:1] == ["watch"] or not parts:
        vid = (q.get("v") or [""])[0]
    vid = vid if _ID.match(vid or "") else ""
    plist = (q.get("list") or [""])[0]
    if parts[:1] == ["playlist"] and plist:
        return {"id": "", "list": plist}
    if vid:
        return {"id": vid, "list": plist}
    return None


def is_youtube_url(url: str) -> bool:
    return parse_url(url) is not None


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------- yt-dlp ----------

class _QuietLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


def cookie_file() -> Path | None:
    """Netscape cookies.txt for videos that need a signed-in viewer, if the owner gave one."""
    cfg = store.get_settings().get("youtube") or {}
    p = Path(str(cfg.get("cookies_file") or "").strip() or (store.DATA / COOKIE_FILE_NAME)).expanduser()
    return p if p.is_file() else None


def _ydl_opts(**extra) -> dict:
    opts = {
        "quiet": True, "no_warnings": True, "noprogress": True, "logger": _QuietLogger(),
        "skip_download": True, "noplaylist": True, "socket_timeout": SOCKET_TIMEOUT_S,
        "extractor_retries": 1, "retries": 1, "cachedir": False,
    }
    ck = cookie_file()
    if ck:
        opts["cookiefile"] = str(ck)
    opts.update(extra)
    return opts


def _with_timeout(fn, timeout: float):
    """Run fn in a daemon thread; give up after timeout so a stuck extractor never blocks the scan."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - handed back to the caller
            box["error"] = e

    t = threading.Thread(target=run, daemon=True, name="yt-extract")
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise _Timeout()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _extract(url: str, **extra) -> dict:
    import yt_dlp
    with yt_dlp.YoutubeDL(_ydl_opts(**extra)) as ydl:
        return ydl.extract_info(url, download=False) or {}


def _first_line(msg: str) -> str:
    line = next((x for x in str(msg).splitlines() if x.strip()), str(msg)).strip()
    line = re.sub(r"^ERROR:\s*", "", line)
    line = re.sub(r"^\[[\w:]+\]\s*[\w-]*:\s*", "", line)      # "[youtube] abc123: "
    line = re.sub(r"\s*Use --cookies.*$", "", line)            # CLI advice; see the cookie note instead
    return line[:200]


def classify_error(msg: str) -> tuple[str, str]:
    """(kind, owner-facing reason) for a yt-dlp error text."""
    low = str(msg).lower()
    if "incomplete youtube id" in low or "looks truncated" in low:
        return "truncated", "影片 ID 不完整（YouTube 影片 ID 是 11 碼），連結可能被截斷，請重新複製完整網址"
    if "private video" in low:
        return "private", "這支影片是私人影片，只有上傳者授權的帳號看得到"
    if "confirm your age" in low or "age-restricted" in low or "inappropriate for some users" in low:
        return "age", "這支影片有年齡限制，要用已登入 YouTube 的 cookies 才讀得到（" + COOKIE_HINT + "）"
    if "members-only" in low or "join this channel" in low or "available to this channel's members" in low:
        return "members", "這支影片是頻道會員限定，要用有會員資格帳號的 cookies 才讀得到（" + COOKIE_HINT + "）"
    if "sign in to confirm" in low or "not a bot" in low or "sign in" in low or "login required" in low:
        return "login", "YouTube 要求登入確認（Sign in to confirm），需要提供 YouTube cookies（" + COOKIE_HINT + "）"
    if "premieres in" in low or "live event will begin" in low or "this live event" in low:
        return "upcoming", "這支影片還沒開播／首播，目前沒有內容可讀"
    if ("video unavailable" in low or "video is unavailable" in low or "has been removed" in low or "no longer available" in low
            or "account associated with this video has been terminated" in low or "does not exist" in low):
        return "removed", "這支影片已刪除或無法觀看（Video unavailable）"
    if "not available in your country" in low or "geo" in low and "block" in low:
        return "geo", "這支影片在本機所在地區無法觀看"
    return "other", f"這支影片取不到中繼資料：{_first_line(msg)}"


COOKIE_HINT = f"匯出 Netscape 格式 cookies.txt 放到 data/{COOKIE_FILE_NAME}，或在 設定 → YouTube 填 cookies 檔路徑"


# ---------- subtitles ----------

def _pick_track(tracks: dict, auto: bool) -> tuple[str, dict] | None:
    """Best (lang, format entry) from a yt-dlp subtitles / automatic_captions dict."""
    if not tracks:
        return None
    order: list[str] = []
    if auto:   # the original-language auto captions beat machine translations
        order += [f"{l}-orig" for l in LANGS]
    order += list(LANGS)
    seen = set()
    for lang in order + sorted(tracks):
        if lang in seen or lang not in tracks:
            continue
        seen.add(lang)
        # past the preferred list: any manual track, but only original-language auto captions
        # (the rest of automatic_captions are machine translations into every language)
        if auto and lang not in order and not lang.endswith("-orig"):
            continue
        entries = [e for e in tracks.get(lang) or [] if isinstance(e, dict) and e.get("url")]
        for fmt in FORMATS:
            for e in entries:
                if e.get("ext") == fmt:
                    return lang, e
    return None


def _ts_line(line: str) -> bool:
    return "-->" in line or bool(re.match(r"^\d+$", line.strip()))


def _dedupe(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln or (out and (ln == out[-1] or out[-1].endswith(ln))):
            continue
        # rolling auto captions repeat the previous line as a prefix of the next one
        if out and ln.startswith(out[-1]):
            out[-1] = ln
            continue
        out.append(ln)
    return out


def subtitle_text(raw: str, ext: str) -> str:
    """Plain text from a json3 / vtt / srv / ttml subtitle file: no timestamps, no repeats."""
    lines: list[str] = []
    if ext == "json3":
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        for ev in data.get("events") or []:
            seg = "".join(s.get("utf8", "") for s in ev.get("segs") or [] if isinstance(s, dict))
            lines += seg.split("\n")
    elif ext in ("srv3", "srv1", "ttml"):
        for m in re.finditer(r"(?s)<(?:p|text)\b[^>]*>(.*?)</(?:p|text)>", raw):
            lines.append(html.unescape(re.sub(r"<[^>]+>", "", m.group(1))))
    else:
        for ln in raw.splitlines():
            s = ln.strip()
            if not s or s.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "STYLE", "REGION")) or _ts_line(s):
                continue
            lines.append(html.unescape(re.sub(r"<[^>]+>", "", s)))
    return "\n".join(_dedupe(lines))


def _download_sub(entry: dict) -> str:
    r = httpx.get(entry["url"], timeout=SUB_TIMEOUT_S, follow_redirects=True)
    r.raise_for_status()
    return subtitle_text(r.text, entry.get("ext", "vtt"))


def transcript(info: dict) -> tuple[str, str]:
    """(text, label) from the best subtitle track: manual first, then automatic captions.

    Automatic captions must be in the video's own language (info["language"]): YouTube sometimes
    recognises a Chinese video as English and offers zh-* only as translations of that English
    track. Then no auto track is used and the caller falls back to local speech-to-text.
    """
    vlang = str(info.get("language") or "").split("-")[0].lower()
    for auto, key in ((False, "subtitles"), (True, "automatic_captions")):
        tracks = dict(info.get(key) or {})
        tracks.pop("live_chat", None)
        if auto and vlang:
            orig = {k for k in tracks if k.endswith("-orig")}
            if orig and not any(k.split("-")[0].lower() == vlang for k in orig):
                break   # the original-language track is the wrong language: every auto track is bad
            tracks = {k: v for k, v in tracks.items() if k.split("-")[0].lower() == vlang}
        for _ in range(2):   # one retry with the next track if a download fails
            pick = _pick_track(tracks, auto)
            if not pick:
                break
            lang, entry = pick
            try:
                text = _download_sub(entry)
            except (httpx.HTTPError, KeyError):
                tracks.pop(lang, None)
                continue
            if text.strip():
                return text, f"{'自動' if auto else '人工'}字幕（{lang.removesuffix('-orig')}）"
            tracks.pop(lang, None)
    return "", ""


# ---------- speech-to-text fallback (audio.cpp) ----------

def asr_cfg() -> dict:
    return {**ASR_DEFAULTS, **(store.get_settings().get("youtube") or {})}


def asr_cache(video_id: str) -> Path:
    return store.DATA / "yt_asr" / f"{re.sub(r'[^A-Za-z0-9_-]', '_', video_id)}.txt"


def _download_audio(url: str, workdir: Path) -> Path:
    import yt_dlp
    opts = _ydl_opts(skip_download=False, format="bestaudio/best",
                     outtmpl=str(workdir / "audio.%(ext)s"), retries=2)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    got = [p for p in workdir.glob("audio.*") if p.suffix not in (".part", ".ytdl")]
    if not got:
        raise RuntimeError("音軌下載失敗")
    return got[0]


def _wav_chunks(src: Path, workdir: Path) -> list[Path]:
    """16 kHz mono WAV pieces (audio.cpp takes WAV uploads only)."""
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "segment", "-segment_time", str(ASR_CHUNK_S), "-c:a", "pcm_s16le",
                        str(workdir / "chunk%03d.wav")], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("音軌轉 WAV 失敗：" + (r.stderr or "").strip()[-200:])
    return sorted(workdir.glob("chunk*.wav"))


def asr_transcript(video_id: str, duration: float | None = None, live: bool = False) -> tuple[str, str, str]:
    """(text, label, note). Downloads the audio only, transcribes it on the local audio.cpp server
    and caches the text in data/yt_asr/<id>.txt, so the radar and the sources stage pay once."""
    cfg = asr_cfg()
    model = str(cfg.get("asr_model") or "").strip()
    label = f"語音轉文字（{model}）"
    if not cfg.get("asr_fallback", True) or not model:
        return "", "", ""
    cache = asr_cache(video_id)
    if cache.is_file() and cache.stat().st_size:
        return cache.read_text("utf-8"), label, "沒有可下載字幕，用本機語音轉文字（快取）"
    if live:
        return "", "", "直播影片不做語音轉文字"
    max_min = float(cfg.get("asr_max_minutes") or 0)
    if duration and max_min and float(duration) > max_min * 60:
        return "", "", f"影片超過 {max_min:g} 分鐘，不做語音轉文字（設定 youtube.asr_max_minutes）"
    from . import media   # lazy: media pulls in the TTS stack
    base = (store.get_settings().get("tts") or {}).get("base_url", "http://127.0.0.1:8090").rstrip("/")
    work = Path(tempfile.mkdtemp(prefix="yt-asr-", dir=str(store.DATA / "tmp") if (store.DATA / "tmp").is_dir() else None))
    try:
        audio = _with_timeout(lambda: _download_audio(watch_url(video_id), work), ASR_DOWNLOAD_TIMEOUT_S)
        texts = []
        for ch in _wav_chunks(audio, work):
            with ch.open("rb") as fh:
                r = media._post_busy_retry(base + "/v1/audio/transcriptions",
                                           wait_total=float(cfg.get("asr_busy_wait_s") or 300),
                                           data={"model": model}, files={"file": (ch.name, fh, "audio/wav")},
                                           timeout=900)
            if r.status_code == 503:
                return "", "", "audio.cpp 一直忙碌，這次沒做語音轉文字"
            r.raise_for_status()
            texts.append(str((r.json() or {}).get("text") or "").strip())
        text = "\n".join(t for t in texts if t)
    except _Timeout:
        return "", "", f"音軌下載超過 {ASR_DOWNLOAD_TIMEOUT_S} 秒，沒做語音轉文字"
    except (httpx.HTTPError, ValueError) as e:
        return "", "", f"語音轉文字失敗（{type(e).__name__}），audio.cpp 是否開著？"
    except Exception as e:  # noqa: BLE001 - yt-dlp / ffmpeg errors: the metadata still goes through
        return "", "", f"語音轉文字失敗：{_first_line(str(e))[:120]}"
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if text:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, "utf-8")
        return text, label, "沒有可下載字幕，改用本機語音轉文字"
    return "", "", "語音轉文字沒有結果"


# ---------- text ----------

def _hms(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _date(d: str) -> str:
    d = str(d or "")
    if re.match(r"^\d{8}$", d):
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d[:10]


def _body(meta: dict, transcript_text: str, label: str, limit: int) -> str:
    head = [f"標題：{meta.get('title') or ''}"]
    for k, name in (("channel", "頻道"), ("published", "發布日期"), ("duration", "片長")):
        if meta.get(k):
            head.append(f"{name}：{meta[k]}")
    head.append(f"字幕來源：{label or '沒有字幕，只用說明文字'}")
    parts = ["\n".join(head)]
    desc = (meta.get("description") or "").strip()
    if desc:
        parts.append("## 影片說明\n" + (desc[:DESC_LIMIT] + ("…" if len(desc) > DESC_LIMIT else "")))
    chapters = meta.get("chapters") or []
    if chapters:
        parts.append("## 章節\n" + "\n".join(f"{_hms(c.get('start_time'))} {c.get('title', '')}".strip()
                                            for c in chapters[:40] if isinstance(c, dict)))
    if transcript_text:
        parts.append("## 逐字稿\n" + transcript_text)
    return "\n\n".join(parts)[:limit]


def _meta_from_info(info: dict) -> dict:
    return {
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "published": _date(info.get("upload_date") or info.get("release_date") or ""),
        "duration": _hms(info.get("duration")) if info.get("duration") else "",
        "description": info.get("description") or "",
        "chapters": info.get("chapters") or [],
    }


# ---------- Data API fallback (signed-in Google account) ----------

def _iso_duration(d: str) -> str:
    m = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", d or "")
    if not m:
        return ""
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return _hms(days * 86400 + h * 3600 + mi * 60 + s)


def api_metadata(video_id: str) -> tuple[dict | None, str]:
    """(meta, why-not) from videos.list with the 設定 → YouTube sign-in. Never raises."""
    from . import youtube
    try:
        token = youtube._access_token()
    except youtube.YouTubeError:
        return None, "沒有可用的 Google 登入（設定 → YouTube），跳過 YouTube Data API 備援"
    except Exception as e:  # noqa: BLE001 - refresh failed for another reason; never show the payload
        return None, f"Google 權杖更新失敗（{type(e).__name__}），跳過 YouTube Data API 備援"
    try:
        r = httpx.get(VIDEOS_API, params={"part": "snippet,contentDetails", "id": video_id},
                      headers={"Authorization": f"Bearer {token}"}, timeout=API_TIMEOUT_S)
    except httpx.HTTPError as e:
        return None, f"YouTube Data API 連不上（{type(e).__name__}）"
    if r.status_code != 200:
        reason = ""
        try:
            reason = (r.json()["error"].get("errors") or [{}])[0].get("reason", "")
        except (ValueError, KeyError, TypeError, AttributeError):
            pass
        if r.status_code in (401, 403) and reason in ("insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT", ""):
            return None, (f"YouTube Data API 拒絕（HTTP {r.status_code}{'，' + reason if reason else ''}）："
                          "請到 設定 → YouTube 重新登入 Google 帳號，授權「檢視 YouTube 帳戶」範圍")
        return None, f"YouTube Data API 失敗（HTTP {r.status_code}{'，' + reason if reason else ''}）"
    items = (r.json() or {}).get("items") or []
    if not items:
        return None, "YouTube Data API 也找不到這支影片（可能已刪除或設為私人）"
    sn, cd = items[0].get("snippet") or {}, items[0].get("contentDetails") or {}
    return {
        "title": sn.get("title") or "",
        "channel": sn.get("channelTitle") or "",
        "published": _date(sn.get("publishedAt") or ""),
        "duration": _iso_duration(cd.get("duration") or ""),
        "description": sn.get("description") or "",
        "chapters": [],
    }, ""


# ---------- entry point ----------

def _fail(url: str, reason: str, kind: str, note: str = "") -> dict:
    return {"ok": False, "url": url, "text": "", "reason": reason, "attempts": 1, "bytes": 0,
            "kind": kind, "note": note, "source": "youtube"}


def fetch(url: str, limit: int = 6000) -> dict:
    """Read a YouTube link like fetch_page does: metadata + subtitles as the page text."""
    limit = max(limit, MIN_LIMIT)
    ref = parse_url(url)
    if not ref:
        return _fail(url, "不是 YouTube 影片連結", "other")
    vid = ref["id"]
    info: dict | None = None
    err_kind, err_reason = "", ""
    try:
        if not vid:   # playlist link: read its first video
            flat = _with_timeout(lambda: _extract(url, extract_flat="in_playlist", playlistend=1,
                                                  noplaylist=False), EXTRACT_TIMEOUT_S)
            first = next((e for e in (flat.get("entries") or []) if isinstance(e, dict) and e.get("id")), None)
            if not first:
                return _fail(url, "這個播放清單是空的，或讀不到第一支影片", "other")
            vid = first["id"]
        info = _with_timeout(lambda: _extract(watch_url(vid)), EXTRACT_TIMEOUT_S)
    except _Timeout:
        err_kind, err_reason = "timeout", f"讀取 YouTube 影片資訊超過 {EXTRACT_TIMEOUT_S} 秒沒有回應，已跳過"
    except ImportError:
        err_kind, err_reason = "other", "沒有 yt-dlp：請先 .venv/bin/python -m pip install -r requirements.txt"
    except Exception as e:  # noqa: BLE001 - yt_dlp.utils.DownloadError and friends
        err_kind, err_reason = classify_error(str(e))

    if info:
        meta = _meta_from_info(info)
        try:
            text, label = transcript(info)
        except Exception:  # noqa: BLE001 - a broken subtitle never sinks the metadata
            text, label = "", ""
        note = ""
        if not text:
            text, label, note = asr_transcript(info.get("id") or vid, info.get("duration"),
                                               live=bool(info.get("is_live")))
            note = note if text else ("這支影片沒有字幕，只用說明文字" + (f"（{note}）" if note else ""))
        body = _body(meta, text, label, limit)
        return {"ok": True, "url": url, "text": body, "reason": "", "attempts": 1,
                "bytes": len(body.encode("utf-8")), "kind": "ok", "note": note,
                "source": "yt-dlp", "subtitle": label, "transcript_chars": len(text)}

    if vid and err_kind not in ("private", "upcoming", "truncated"):
        meta, why = api_metadata(vid)
        if meta:
            body = _body(meta, "", "", limit)
            note = f"yt-dlp 讀不到（{err_reason}），改用 YouTube Data API：只有說明文字，沒有字幕"
            return {"ok": True, "url": url, "text": body, "reason": "", "attempts": 2,
                    "bytes": len(body.encode("utf-8")), "kind": "api", "note": note,
                    "source": "youtube-data-api", "subtitle": "", "transcript_chars": 0}
        return _fail(url, err_reason, err_kind, note=why)
    return _fail(url, err_reason, err_kind)
