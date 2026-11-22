"""Free stock B-roll: Pexels and Pixabay video search with a disk cache and credits.

Keys come from environment variables (names in settings, values never stored). Every download
gets a cache file named after the source URL hash, so a re-assemble costs no network. Sources
are recorded per episode in assets/sources.json for the publish description.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx

from . import store

PEXELS_API = "https://api.pexels.com/videos/search"
PIXABAY_API = "https://pixabay.com/api/videos/"
MIN_SECONDS = 3.0


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
                                      "per_page": 8, "size": "medium"},
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
    r = httpx.get(PIXABAY_API, params={"key": key, "q": query, "video_type": "film", "per_page": 8,
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


def fetch(query: str, vertical: bool = False) -> dict | None:
    """Download the best candidate; returns {path, provider, author, page, license, duration}."""
    for cand in search(query, vertical)[:3]:
        h = hashlib.sha1(cand["url"].encode()).hexdigest()[:16]
        ext = ".mp4" if ".mp4" in cand["url"].lower() else Path(cand["url"]).suffix or ".mp4"
        path = cache_dir() / f"{h}{ext}"
        if not (path.exists() and path.stat().st_size > 10000):
            try:
                with httpx.stream("GET", cand["url"], timeout=120, follow_redirects=True) as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(".part")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_bytes(1 << 16):
                            fh.write(chunk)
                    tmp.replace(path)
            except httpx.HTTPError:
                continue
        return {"path": path, "provider": cand["provider"], "author": cand.get("author", ""),
                "page": cand.get("page", ""), "license": cand.get("license", ""),
                "duration": float(cand.get("duration") or 0), "query": query}
    return None


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
