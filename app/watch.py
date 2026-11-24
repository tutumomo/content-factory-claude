"""Watched sources: the owner enters a site (or feed) once, the app scans it on a schedule.

Each scan finds the site's RSS/Atom feed (or, failing that, the article links on the page),
keeps only items it has not seen before, and hands them to the radar so they become idea
cards (kind "watch"). Items are marked seen only after the radar succeeds, so a failed model
call is retried next time. Times are the server's local time.
"""
from __future__ import annotations

import hashlib
import html
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import httpx

from . import llm, store

FREQS = ("daily", "weekdays", "weekly", "hours")
FREQ_LABEL = {"daily": "每天", "weekdays": "週一到週五", "weekly": "每週", "hours": "每隔幾小時"}
WEEKDAYS = "一二三四五六日"
SEEN_MAX = 1000
MAX_BYTES = 5_000_000
TICK = 30  # seconds between scheduler checks
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
FEED_TYPES = ("rss", "atom", "xml")

_lock = threading.RLock()


class WatchError(Exception):
    pass


# ---------- storage ----------

def _path():
    return store.DATA / "watch.json"


def _load() -> list[dict]:
    raw = store._read(_path(), {"sources": []})
    rows = raw.get("sources") if isinstance(raw, dict) else None
    return [s for s in (rows or []) if isinstance(s, dict) and s.get("id")]


def _save(rows: list[dict]) -> None:
    store._write(_path(), {"sources": rows})


def _clamp(v, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _hhmm(v) -> str:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(v or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return "06:00"
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def normalize(data: dict, old: dict | None = None) -> dict:
    """Schedule fields of a source, cleaned; url must be http(s)."""
    src = {**(old or {}), **{k: v for k, v in data.items() if v is not None}}
    url = str(src.get("url") or "").strip()
    if not re.match(r"https?://[^\s/]+", url):
        raise WatchError("請輸入 http:// 或 https:// 開頭的網址")
    src["url"] = url
    src["name"] = str(src.get("name") or "").strip()[:60] or (urlparse(url).hostname or url)
    src["freq"] = src.get("freq") if src.get("freq") in FREQS else "daily"
    src["time"] = _hhmm(src.get("time"))
    src["weekday"] = _clamp(src.get("weekday"), 0, 6, 0)
    src["every_hours"] = _clamp(src.get("every_hours"), 1, 168, 6)
    src["max_items"] = _clamp(src.get("max_items"), 1, 30, 10)
    src["enabled"] = bool(src.get("enabled", True))
    return src


def next_run(src: dict, after: float) -> float:
    """First scheduled moment strictly after `after` (local time)."""
    if src.get("freq") == "hours":
        return after + _clamp(src.get("every_hours"), 1, 168, 6) * 3600
    hh, mm = (int(x) for x in _hhmm(src.get("time")).split(":"))
    now = datetime.fromtimestamp(after)
    cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= now:
        cand += timedelta(days=1)
    for _ in range(8):
        wd = cand.weekday()
        if src.get("freq") == "weekdays" and wd >= 5:
            cand += timedelta(days=1)
        elif src.get("freq") == "weekly" and wd != _clamp(src.get("weekday"), 0, 6, 0):
            cand += timedelta(days=1)
        else:
            break
    return cand.timestamp()


def describe(src: dict) -> str:
    f = src.get("freq")
    if f == "hours":
        return f"每 {src.get('every_hours', 6)} 小時"
    if f == "weekly":
        return f"每週{WEEKDAYS[_clamp(src.get('weekday'), 0, 6, 0)]} {src.get('time')}"
    return f"{FREQ_LABEL.get(f, '每天')} {src.get('time')}"


def public(src: dict) -> dict:
    out = {k: v for k, v in src.items() if k != "seen"}
    out["seen_count"] = len(src.get("seen") or [])
    out["schedule_label"] = describe(src)
    return out


def list_sources() -> list[dict]:
    with _lock:
        return [public(s) for s in _load()]


def get(sid: str) -> dict | None:
    with _lock:
        return next((s for s in _load() if s["id"] == sid), None)


def create(data: dict) -> dict:
    with _lock:
        rows = _load()
        src = normalize(data)
        if any(s["url"] == src["url"] for s in rows):
            raise WatchError("這個來源已經在訂閱清單裡")
        now = time.time()
        src.update({"id": f"w-{uuid.uuid4().hex[:8]}", "created": now, "seen": [],
                    "last_run": None, "last_status": None, "last_message": "", "last_added": 0,
                    "feed_url": "", "next_run": next_run(src, now)})
        rows.append(src)
        _save(rows)
        return public(src)


def update(sid: str, patch: dict) -> dict:
    with _lock:
        rows = _load()
        for i, s in enumerate(rows):
            if s["id"] == sid:
                keep = {k: s.get(k) for k in ("id", "created", "seen", "last_run", "last_status",
                                               "last_message", "last_added", "feed_url")}
                if patch.get("url") and patch["url"] != s["url"]:
                    keep.update(seen=[], feed_url="")  # a different site starts fresh
                src = {**normalize(patch, s), **keep}
                src["next_run"] = next_run(src, time.time())
                rows[i] = src
                _save(rows)
                return public(src)
    raise WatchError("找不到這個訂閱來源")


def delete(sid: str) -> bool:
    with _lock:
        rows = _load()
        kept = [s for s in rows if s["id"] != sid]
        _save(kept)
        return len(kept) != len(rows)


def reset_running(note: str) -> None:
    """Any source still marked running when a restart happened: it is not running any more."""
    with _lock:
        rows = _load()
        hit = [r for r in rows if r.get("last_status") == "running"]
        for r in hit:
            r["last_status"] = "error"
            r["last_message"] = note
        if hit:
            _save(rows)


def mark(sid: str, status: str, message: str = "", **extra) -> None:
    with _lock:
        rows = _load()
        for s in rows:
            if s["id"] == sid:
                s.update(last_status=status, last_message=message, **extra)
                if status not in ("queued", "running"):
                    s["last_run"] = time.time()
        _save(rows)


# ---------- fetching ----------

def _get(url: str) -> httpx.Response:
    r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": UA})
    r.raise_for_status()
    if len(r.content) > MAX_BYTES:
        raise WatchError(f"回應太大（{len(r.content) // 1024} KB）")
    return r


def _text(fragment: str, limit: int = 600) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", fragment or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return html.unescape(re.sub(r"\s+", " ", t)).strip()[:limit]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(el, *names: str):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _ctext(el, *names: str) -> str:
    c = _child(el, *names)
    return (c.text or "").strip() if c is not None else ""


def _is_feed(r: httpx.Response) -> bool:
    ct = r.headers.get("content-type", "").lower()
    head = r.text[:400].lstrip().lower()
    return any(x in ct for x in FEED_TYPES) or head.startswith("<?xml") or head.startswith(("<rss", "<feed"))


def parse_feed(xml_text: str, base: str) -> list[dict]:
    """RSS 2.0 / RSS 1.0 / Atom items → [{key, title, link, original, summary, published}]."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        raise WatchError(f"RSS 解析失敗：{e}") from e
    host = urlparse(base).hostname or ""
    items = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        link = _ctext(el, "link")
        if not link:  # Atom: <link rel="alternate" href="...">
            for c in el:
                if _local(c.tag) == "link" and c.get("rel", "alternate") == "alternate" and c.get("href"):
                    link = c.get("href")
                    break
        link = urljoin(base, link) if link else ""
        raw = _ctext(el, "description", "summary", "encoded", "content")
        title = _text(_ctext(el, "title"), 200)
        # aggregator items often point at their own page; keep the original article too
        original = ""
        for href in re.findall(r'href="(https?://[^"]+)"', raw or ""):
            h = urlparse(href).hostname or ""
            if h and h != host and h != (urlparse(link).hostname or ""):
                original = html.unescape(href)
                break
        key = _ctext(el, "guid", "id") or link or title
        if not title and not link:
            continue
        items.append({"key": key, "title": title or link, "link": link, "original": original,
                      "summary": _text(raw), "published": _ctext(el, "pubdate", "published", "updated", "date")})
    return items


def _feed_link(page: str, base: str) -> str:
    for tag in re.findall(r"(?is)<link\b[^>]*>", page):
        if re.search(r'rel=["\']?alternate', tag, re.I) and re.search(r"(rss|atom)\+xml", tag, re.I):
            m = re.search(r'href=["\']([^"\']+)', tag, re.I)
            if m:
                return urljoin(base, html.unescape(m.group(1)))
    return ""


def page_links(page: str, base: str, limit: int = 40) -> list[dict]:
    """Article-looking links on a listing page: same site, not the home page, with real link text."""
    host = urlparse(base).hostname or ""
    body = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", page)
    seen, out = set(), []
    for href, inner in re.findall(r'(?is)<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', body):
        url = urljoin(base, html.unescape(href.strip()))
        p = urlparse(url)
        title = _text(inner, 200)
        if p.scheme not in ("http", "https") or p.hostname != host or p.path in ("", "/"):
            continue
        if len(title) < 8 or url in seen:
            continue
        seen.add(url)
        out.append({"key": url, "title": title, "link": url, "original": "", "summary": "", "published": ""})
        if len(out) >= limit:
            break
    return out


def discover(url: str, feed_url: str = "") -> tuple[list[dict], str, str]:
    """Return (items, feed_url_used, how) for a watched URL."""
    if feed_url:
        try:
            r = _get(feed_url)
            if _is_feed(r):
                return parse_feed(r.text, feed_url), feed_url, "RSS"
        except (httpx.HTTPError, WatchError):
            pass  # fall back to rediscovering from the page
    try:
        r = _get(url)
    except httpx.HTTPError as e:
        raise WatchError(f"抓不到網頁（{type(e).__name__}: {e}）") from e
    if _is_feed(r):
        return parse_feed(r.text, url), url, "RSS"
    found = _feed_link(r.text, str(r.url))
    if found:
        try:
            fr = _get(found)
            if _is_feed(fr):
                return parse_feed(fr.text, found), found, "RSS"
        except (httpx.HTTPError, WatchError):
            pass
    return page_links(r.text, str(r.url)), "", "網頁連結"


def seeds(src: dict, items: list[dict]) -> str:
    blocks = [f"# 訂閱來源：{src['name']}（{src['url']}）\n以下是這次掃描到的新文章，每則附連結與摘要。"]
    for it in items:
        lines = [f"## {it['title']}", f"連結：{it['link']}"]
        if it.get("original"):
            lines.append(f"原文：{it['original']}")
        if it.get("published"):
            lines.append(f"發布：{it['published']}")
        if it.get("summary"):
            lines.append(it["summary"])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)[:16000]


def _key(it: dict) -> str:
    return hashlib.sha1(str(it.get("key") or it.get("link")).encode("utf-8")).hexdigest()[:16]


# ---------- running ----------

def run(sid: str) -> None:
    from . import pipeline  # late import: pipeline imports this module lazily too
    src = get(sid)
    if not src:
        return
    mark(sid, "running", "正在抓取來源…")
    try:
        items, feed_url, how = discover(src["url"], src.get("feed_url") or "")
    except WatchError as e:
        mark(sid, "error", str(e), last_added=0)
        return
    if not items:
        mark(sid, "error", "找不到 RSS，也找不到文章連結（網頁可能由 JS 產生）。請改填 RSS 網址或具體分類頁。",
             last_added=0, feed_url=feed_url)
        return
    seen = set(src.get("seen") or [])
    fresh = [it for it in items if _key(it) not in seen][: src.get("max_items", 10)]
    if not fresh:
        mark(sid, "empty", f"{how}共 {len(items)} 則，都掃過了，沒有新文章。", last_added=0, feed_url=feed_url)
        return
    mark(sid, "running", f"{how}找到 {len(fresh)} 則新文章，交給雷達評分…", feed_url=feed_url)
    try:
        rows = pipeline.radar_rows(seeds(src, fresh))
    except llm.LLMError as e:
        mark(sid, "error", f"模型呼叫失敗（{type(e).__name__}）：{e}；下次會重試這些文章。", last_added=0)
        return
    if rows:
        pipeline.add_radar_cards(rows, kind="watch", source=src["name"])
    with _lock:  # mark seen only after the radar ran, so a failure retries next time
        all_rows = _load()
        for s in all_rows:
            if s["id"] == sid:
                s["seen"] = ([_key(it) for it in fresh] + list(s.get("seen") or []))[:SEEN_MAX]
        _save(all_rows)
    msg = f"{how} {len(fresh)} 則新文章 → 新增 {len(rows)} 張卡片。" if rows else \
        f"{how} {len(fresh)} 則新文章，模型沒有抽出值得做的題目。"
    mark(sid, "ok" if rows else "empty", msg, last_added=len(rows))


def run_now(sid: str) -> bool:
    from . import pipeline
    if not get(sid):
        raise WatchError("找不到這個訂閱來源")
    mark(sid, "queued", "已排入佇列…")
    return pipeline.enqueue("watch", sid)


def due(now: float | None = None) -> list[str]:
    """Advance the schedule of every due source and return their ids (each fires once)."""
    now = now or time.time()
    out = []
    with _lock:
        rows = _load()
        changed = False
        for s in rows:
            if not s.get("enabled", True):
                continue
            nr = s.get("next_run")
            if nr is None:
                s["next_run"] = next_run(s, now)
                changed = True
            elif now >= nr:
                s["next_run"] = next_run(s, now)  # missed runs while the server was down fire only once
                changed = True
                out.append(s["id"])
        if changed:
            _save(rows)
    return out


def _loop() -> None:
    from . import pipeline
    while True:
        try:
            for sid in due():
                mark(sid, "queued", "排程時間到，已排入佇列…")
                pipeline.enqueue("watch", sid)
        except Exception:  # noqa: BLE001 — the scheduler must never die
            pass
        time.sleep(TICK)


def start_scheduler() -> None:
    """Called at startup: re-queue scans a restart interrupted, then start the clock."""
    from . import pipeline
    for s in list_sources():
        if s.get("last_status") in ("queued", "running"):
            mark(s["id"], "queued", "伺服器重啟，重新排入佇列…")
            pipeline.enqueue("watch", s["id"])
    threading.Thread(target=_loop, daemon=True, name="cf-watch").start()
