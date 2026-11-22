"""Open-licensed audio: Freesound sound effects and Openverse music.

Same shape as stock.py: keys come from environment variables named in settings (values are
never stored), downloads are cached by URL hash, and every file keeps its license and
attribution in a sidecar `.json` so the publish description can credit CC-BY material.

Openverse (api.openverse.org) aggregates CC audio from Jamendo, Freesound, Wikimedia and
more, and needs no account: anonymous limits are 20 requests/min and 200/day.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import httpx

from . import store

FREESOUND_API = "https://freesound.org/apiv2/search/text/"
OPENVERSE_API = "https://api.openverse.org/v1/audio/"
FS_FIELDS = "id,name,previews,license,duration,username,url,tags"

# Freesound license filter values that are fine to publish commercially.
FS_LICENSE = {
    "cc0": 'license:"Creative Commons 0"',
    "by": 'license:"Attribution"',
}

# Short search terms, because the full generation prompt is too specific for a search box.
SFX_QUERY = {
    "whoosh": "whoosh transition", "riser": "riser", "impact": "cinematic impact",
    "ding": "bell ding", "pop": "pop", "click": "ui click", "paper": "page turn",
    "keyboard": "keyboard typing", "phone": "notification chime", "cash": "cash register",
    "alarm": "alarm beep", "glitch": "glitch", "heartbeat": "heartbeat",
    "crowd": "crowd ambience", "wind": "wind ambience", "water": "water splash",
    "fire": "fire crackle", "birds": "birds ambience", "city": "city ambience",
    "night": "night crickets", "scifi": "sci fi interface", "sparkle": "magic sparkle",
    "error": "error buzz", "success": "success chime",
}

STOP = {"instrumental", "music", "background", "bgm", "no", "vocals", "vocal", "with", "the",
        "and", "for", "about", "soft", "light", "subtle", "mellow", "unobtrusive", "warm",
        "track", "song", "style", "loop", "loops"}


class AudioStockError(RuntimeError):
    pass


def _visual_cfg() -> dict:
    return store.get_settings().get("visuals") or {}


def _sfx_cfg() -> dict:
    return store.get_settings().get("sfx") or {}


def _music_cfg() -> dict:
    return store.get_settings().get("music") or {}


def keys() -> dict[str, str]:
    return {
        "freesound": os.environ.get(_sfx_cfg().get("freesound_key_env") or "FREESOUND_API_KEY", "").strip(),
    }


def status() -> dict:
    k = keys()
    return {
        "keys_set": {n: bool(v) for n, v in k.items()},
        "sfx_license": _sfx_cfg().get("freesound_license") or "cc0",
        "music_license": _music_cfg().get("openverse_license") or "cc0",
        "detail": "、".join(n for n, v in k.items() if v) or
                  "Freesound 沒有金鑰：請在環境變數設定 FREESOUND_API_KEY（音樂用 Openverse，免金鑰）",
    }


def _num(d: dict, key: str) -> float:
    try:
        return float(d.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _sidecar(path: Path, meta: dict) -> None:
    path.with_suffix(path.suffix + ".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")


def _download(url: str, path: Path, timeout: float = 120.0) -> bool:
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
            r.raise_for_status()
            tmp = path.with_suffix(path.suffix + ".part")
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk)
            tmp.replace(path)
        return path.stat().st_size > 2000
    except (httpx.HTTPError, OSError):
        return False


# ---------- Freesound (sound effects) ----------

def search_sfx(query: str, limit: int = 8, max_seconds: float = 5.0,
               license: str = "") -> list[dict]:
    key = keys()["freesound"]
    if not key or not (query or "").strip():
        return []
    lic = FS_LICENSE.get((license or _sfx_cfg().get("freesound_license") or "cc0").lower())
    flt = f'duration:[0.2 TO {max_seconds:g}]'
    if lic:
        flt += " " + lic
    try:
        r = httpx.get(FREESOUND_API, params={"query": query, "token": key, "fields": FS_FIELDS,
                                             "filter": flt, "page_size": limit,
                                             "sort": "score"},
                      timeout=20)
        r.raise_for_status()
        rows = r.json().get("results", [])
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for s in rows:
        p = s.get("previews") or {}
        url = p.get("preview-hq-mp3") or p.get("preview-lq-mp3")
        if not url:
            continue
        out.append({"provider": "freesound", "id": s.get("id"), "url": url,
                    "title": s.get("name") or "", "author": s.get("username") or "",
                    "page": s.get("url") or (f"https://freesound.org/s/{s.get('id')}/"),
                    "license": s.get("license") or "", "duration": _num(s, "duration")})
    return out


def fetch_sfx(tag: str, dest_dir: Path, license: str = "") -> dict | None:
    """Download one CC0 preview into the sfx library as `<tag>__freesound<id>.mp3`."""
    tag = (tag or "").strip().lower()
    query = SFX_QUERY.get(tag) or tag
    ambience = tag in {"crowd", "wind", "water", "fire", "birds", "city", "night", "glitch"}
    cands = search_sfx(query, max_seconds=15.0 if ambience else 5.0, license=license)
    dest_dir.mkdir(parents=True, exist_ok=True)
    for cand in cands[:3]:
        path = dest_dir / f"{tag}__freesound{cand['id']}.mp3"
        if not (path.exists() and path.stat().st_size > 2000):
            if not _download(cand["url"], path):
                continue
        meta = {"provider": "freesound", "id": cand["id"], "title": cand["title"],
                "author": cand["author"], "page": cand["page"], "license": cand["license"],
                "duration": cand["duration"], "tag": tag}
        _sidecar(path, meta)
        return {**meta, "path": path}
    return None


# ---------- Openverse (background music, no account needed) ----------

def _style_words(style: str) -> list[str]:
    out: list[str] = []
    for w in re.split(r"[^a-z0-9]+", (style or "").lower()):
        if len(w) > 2 and w not in STOP and w not in out:
            out.append(w)
    return out


def search_music(style: str, min_seconds: float = 30.0, limit: int = 10,
                 license: str = "") -> list[dict]:
    """Instrumental-ish tracks from Openverse. Jamendo-sourced tracks are preferred."""
    mode = (license or _music_cfg().get("openverse_license") or "cc0").lower()
    lic = "cc0" if mode == "cc0" else "cc0,by"
    words = _style_words(style)[:3] or ["music"]
    rows: list[dict] = []
    for q in words:
        for src in ("jamendo", ""):
            params = {"q": q, "license": lic, "license_type": "commercial",
                      "page_size": min(max(limit, 5), 20)}
            if src:
                params["source"] = src
            try:
                r = httpx.get(OPENVERSE_API, params=params, timeout=20)
                r.raise_for_status()
                got = r.json().get("results") or []
            except (httpx.HTTPError, ValueError):
                continue
            if got:
                rows = got
                break
        if rows:
            break
    out = []
    for t in rows:
        url = t.get("url") or ""
        dur = _num(t, "duration") / 1000.0        # Openverse reports milliseconds
        if not url or not dur:
            continue
        lic_name = {"cc0": "CC0", "by": "CC BY", "by-sa": "CC BY-SA"}.get(
            (t.get("license") or "").lower(), (t.get("license") or "").upper())
        out.append({"provider": "openverse", "id": t.get("id"), "url": url,
                    "title": t.get("title") or "", "author": t.get("creator") or "",
                    "page": t.get("foreign_landing_url") or "", "license": lic_name,
                    "license_url": t.get("license_url") or "", "source": t.get("source") or "",
                    "duration": dur})
    # longest first: the bed has to cover the whole episode (it loops if even this is short)
    out.sort(key=lambda r: (-(r["duration"] >= min_seconds), -r["duration"]))
    return out


def fetch_music(style: str, min_seconds: float, dest_dir: Path, license: str = "") -> dict | None:
    """Download one track (long enough when possible) into the music cache."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for cand in search_music(style, min_seconds, license=license)[:3]:
        h = hashlib.sha1(f"openverse|{cand['id']}".encode()).hexdigest()[:16]
        path = dest_dir / f"bgm_openverse_{h}.mp3"
        if not (path.exists() and path.stat().st_size > 50000):
            if not _download(cand["url"], path):
                continue
        meta = {**cand, "style": style}
        _sidecar(path, meta)
        return {**meta, "path": path}
    return None


# ---------- credits ----------

def credit(row: dict) -> str:
    who = row.get("author") or row.get("provider") or ""
    lic = row.get("license") or ""
    title = row.get("title") or ""
    page = row.get("page") or ""
    kind = "音效" if row.get("provider") == "freesound" else "音樂"
    body = " ".join(x for x in (title, f"— {who}" if who else "") if x).strip()
    src = row.get("source") or row.get("provider") or ""
    tail = "，".join(x for x in (src, lic) if x)
    return f"- {kind}：{body}（{tail}）{page}".rstrip()


def credits(rows: list[dict]) -> str:
    seen, lines = set(), []
    for row in rows:
        k = (row.get("provider"), row.get("id"))
        if k in seen:
            continue
        seen.add(k)
        lines.append(credit(row))
    return "\n".join(lines)
