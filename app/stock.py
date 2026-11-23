"""Free stock B-roll: Pexels and Pixabay video search with a disk cache and credits.

Keys come from environment variables (names in settings, values never stored). Every download
gets a cache file named after the source URL hash, so a re-assemble costs no network. Sources
are recorded per episode in assets/sources.json for the publish description.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx

from . import store

PEXELS_API = "https://api.pexels.com/videos/search"
PIXABAY_API = "https://pixabay.com/api/videos/"
MIN_SECONDS = 3.0
PER_PAGE = 15                # candidates per provider and query; more choice = fewer repeats
USAGE_FILE = "stock_usage.json"   # data/stock_usage.json: {"pexels:123": [unix time, episode id], ...}
USAGE_MAX = 2000
_usage_lock = threading.Lock()


class StockError(RuntimeError):
    pass


def cfg() -> dict:
    return store.get_settings().get("visuals") or {}


def cache_dir() -> Path:
    d = store.DATA / "stock"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _keys() -> dict[str, str]:
    c = cfg()
    return {
        "pexels": os.environ.get(c.get("pexels_key_env") or "PEXELS_API_KEY", "").strip(),
        "pixabay": os.environ.get(c.get("pixabay_key_env") or "PIXABAY_API_KEY", "").strip(),
    }


def status() -> dict:
    keys = _keys()
    cached = len(list(cache_dir().glob("*.*")))
    enabled = (cfg().get("source") or "slides") in ("stock", "mix")
    return {"enabled": enabled, "keys_set": {k: bool(v) for k, v in keys.items()},
            "providers": [k for k, v in keys.items() if v], "cached": cached,
            "detail": ("就緒" if any(keys.values()) else
                       "沒有金鑰：請在環境變數設定 PEXELS_API_KEY 或 PIXABAY_API_KEY")}


def _orientation(vertical: bool) -> str:
    return "portrait" if vertical else "landscape"


def _pexels(query: str, vertical: bool, key: str) -> list[dict]:
    r = httpx.get(PEXELS_API, params={"query": query, "orientation": _orientation(vertical),
                                      "per_page": PER_PAGE, "size": "medium"},
                  headers={"Authorization": key}, timeout=20)
    r.raise_for_status()
    out = []
    for v in r.json().get("videos", []):
        if float(v.get("duration") or 0) < MIN_SECONDS:
            continue
        files = [f for f in v.get("video_files") or [] if f.get("link") and f.get("width")]
        if not files:
            continue
        files.sort(key=lambda f: (f.get("width", 0) < 720, -f.get("width", 0)))
        f = files[0]
        out.append({"provider": "pexels", "id": v.get("id"), "url": f["link"], "width": f.get("width"),
                    "height": f.get("height"), "duration": v.get("duration"),
                    "author": (v.get("user") or {}).get("name") or "",
                    "page": v.get("url") or "", "license": "Pexels License（免費商用、免標註）"})
    return out


def _pixabay(query: str, vertical: bool, key: str) -> list[dict]:
    r = httpx.get(PIXABAY_API, params={"key": key, "q": query, "video_type": "film", "per_page": PER_PAGE,
                                       "safesearch": "true"}, timeout=20)
    r.raise_for_status()
    out = []
    for v in r.json().get("hits", []):
        if float(v.get("duration") or 0) < MIN_SECONDS:
            continue
        vids = v.get("videos") or {}
        pick = vids.get("large") or vids.get("medium") or vids.get("small")
        if not pick or not pick.get("url"):
            continue
        w, h = pick.get("width") or 0, pick.get("height") or 0
        if vertical != (h > w):
            continue
        out.append({"provider": "pixabay", "id": v.get("id"), "url": pick["url"], "width": w,
                    "height": h, "duration": v.get("duration"), "author": v.get("user") or "",
                    "page": v.get("pageURL") or "", "license": "Pixabay Content License（免費商用、免標註）"})
    return out


def search(query: str, vertical: bool = False) -> list[dict]:
    """Candidates from every provider whose key is set, best-fit first."""
    query = (query or "").strip()
    if not query:
        return []
    keys = _keys()
    rows: list[dict] = []
    for name, fn in (("pexels", _pexels), ("pixabay", _pixabay)):
        if not keys.get(name):
            continue
        try:
            rows += fn(query, vertical, keys[name])
        except (httpx.HTTPError, ValueError):
            continue
    target_h = 1920 if vertical else 1080
    rows.sort(key=lambda r: (abs((r.get("height") or 0) - target_h), -float(r.get("duration") or 0)))
    return rows


def clip_key(row: dict) -> str:
    """Stable id of one stock clip across searches: provider + provider's video id."""
    return f"{row.get('provider')}:{row.get('id')}"


# ---------- usage ledger: clips used in recent episodes rank last ----------

def _usage_path() -> Path:
    return store.DATA / USAGE_FILE


def usage() -> dict:
    try:
        d = json.loads(_usage_path().read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def recent_keys(days: float | None = None, skip_episode: str = "") -> set[str]:
    """Clips another episode used in the last `days` days (settings visuals.stock_recent_days, 30)."""
    if days is None:
        days = float(cfg().get("stock_recent_days", 30) or 0)
    if days <= 0:
        return set()
    cut = time.time() - days * 86400
    out = set()
    for k, v in usage().items():
        if isinstance(v, list) and len(v) >= 2 and float(v[0] or 0) >= cut and v[1] != skip_episode:
            out.add(k)
    return out


def mark_used(keys, episode: str) -> None:
    keys = [k for k in keys if k]
    if not keys:
        return
    with _usage_lock:
        d = usage()
        now = time.time()
        for k in keys:
            d[k] = [round(now), episode]
        if len(d) > USAGE_MAX:   # forget the oldest
            d = dict(sorted(d.items(), key=lambda kv: kv[1][0] if isinstance(kv[1], list) else 0)[-USAGE_MAX:])
        tmp = _usage_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), "utf-8")
        tmp.replace(_usage_path())


def rank(rows: list[dict], exclude: set[str], recent: set[str], seed: str = "") -> list[dict]:
    """Unused-in-this-episode only; clips other recent episodes used go last; a good size fit beats a
    poor one; among equals the order is shuffled per seed so similar queries do not land on one clip."""
    def jitter(r: dict) -> str:
        return hashlib.sha1(f"{seed}|{clip_key(r)}".encode()).hexdigest()
    keep = [r for r in rows if clip_key(r) not in exclude]
    # rows arrive sorted by fit; keep that as a coarse band (top half / rest) and shuffle inside it
    band = {clip_key(r): (0 if i < max(3, len(keep) // 2) else 1) for i, r in enumerate(keep)}
    return sorted(keep, key=lambda r: (clip_key(r) in recent, band[clip_key(r)], jitter(r)))


def _download(cand: dict) -> Path | None:
    h = hashlib.sha1(cand["url"].encode()).hexdigest()[:16]
    ext = ".mp4" if ".mp4" in cand["url"].lower() else Path(cand["url"]).suffix or ".mp4"
    path = cache_dir() / f"{h}{ext}"
    if path.exists() and path.stat().st_size > 10000:
        return path
    try:
        with httpx.stream("GET", cand["url"], timeout=120, follow_redirects=True) as r:
            r.raise_for_status()
            tmp = path.with_suffix(".part")
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk)
            tmp.replace(path)
    except httpx.HTTPError:
        return None
    return path


def fetch(query: str, vertical: bool = False, n: int = 1, exclude: set[str] | None = None,
          recent: set[str] | None = None, seed: str = "") -> dict | None:
    """Download up to `n` different clips for one scene.

    Returns the first clip as {path, provider, id, key, author, page, license, duration, query}
    plus "shots": every downloaded clip (the first included), for a multi-shot scene.
    `exclude` = clips this episode already used (never picked again); `recent` = clips other recent
    episodes used (picked only when nothing else is left).
    """
    exclude = set(exclude or ())
    shots: list[dict] = []
    tries = 0
    for cand in rank(search(query, vertical), exclude, set(recent or ()), seed):
        if len(shots) >= max(1, n) or tries >= max(3, n + 2):
            break
        tries += 1
        path = _download(cand)
        if not path:
            continue
        shots.append({"path": path, "provider": cand["provider"], "id": cand.get("id"),
                      "key": clip_key(cand), "author": cand.get("author", ""),
                      "page": cand.get("page", ""), "license": cand.get("license", ""),
                      "duration": float(cand.get("duration") or 0), "query": query})
    if not shots:
        return None
    return {**shots[0], "shots": shots}


def scene_query(scene: dict) -> str:
    q = (scene.get("stock_query") or "").strip()
    if q:
        return q
    visual = (scene.get("visual") or "").strip()
    return " ".join(visual.split()[:4])


def credits(sources: list[dict]) -> str:
    rows = []
    for s in sources:
        who = s.get("author") or s.get("provider")
        rows.append(f"- {who}（{s.get('provider')}）{s.get('page') or ''}".rstrip())
    return "\n".join(rows)


def save_sources(assets: Path, sources: list[dict]) -> None:
    if not sources:
        return
    # fetch() hands back a Path for the downloaded file; keep the record JSON-safe
    rows = [{k: (str(v) if isinstance(v, Path) else v) for k, v in s.items()} for s in sources]
    (assets / "sources.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
