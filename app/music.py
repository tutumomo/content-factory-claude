"""Background music: YuE2 3B instrumental through audio.cpp, mixed under the narration.

Generation goes through the running audiocpp_server (`POST /v1/tasks/run`), so the model is
loaded once per episode instead of once per scene. Results are cached by (style, seconds, seed),
so re-assembling an episode costs no GPU time.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from . import store

DEFAULT_STYLE = ("instrumental background music, warm lo-fi, soft piano, light brushed drums, "
                 "subtle upright bass, mellow and unobtrusive, no vocals")
FRAMES_PER_SEC = 25            # YuE2 semantic frames per second of audio
MAX_SECONDS = 354.0            # semantic_max_tokens cap 9000 → 360 s; stay under it


class MusicError(RuntimeError):
    pass


def cfg() -> dict:
    return store.get_settings().get("music") or {}


def cache_dir() -> Path:
    d = Path(cfg().get("cache_dir") or (store.DATA / "music"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def style_of(script: dict | None = None) -> str:
    """Script-level style wins; empty means the setting (or the built-in default)."""
    s = ((script or {}).get("music") or "").strip()
    if isinstance(s, dict):
        s = (s.get("style") or "").strip()
    return s or (cfg().get("style") or "").strip() or DEFAULT_STYLE


def _key(style: str, seconds: float, seed: int) -> str:
    return hashlib.sha1(f"{style}|{seconds:.1f}|{seed}".encode()).hexdigest()[:16]


def generate(seconds: float, style: str = "", seed: int | None = None, out: Path | None = None,
             force: bool = False) -> Path:
    """Render an instrumental bed of `seconds` length (capped) and return the wav path."""
    c = cfg()
    style = (style or "").strip() or (c.get("style") or "").strip() or DEFAULT_STYLE
    seed = int(seed if seed is not None else (c.get("seed") or 1234))
    want = max(8.0, min(float(seconds), MAX_SECONDS))
    path = out or (cache_dir() / f"bgm_{_key(style, want, seed)}.wav")
    if path.exists() and path.stat().st_size > 44 and not force:
        return path
    base = (c.get("base_url") or store.get_settings()["tts"]["base_url"]).rstrip("/")
    model = c.get("model") or "yue2"
    options = {
        "style": style,
        "cot": "off",
        "semantic_max_tokens": int(round(want * FRAMES_PER_SEC)),
        "num_inference_steps": int(c.get("steps") or 8),
        "seed": seed,
    }
    if c.get("guidance_scale"):
        options["guidance_scale"] = float(c["guidance_scale"])
    body = {"model": model, "request": {"lyrics": "", "options": options}}
    try:
        r = httpx.post(base + "/v1/tasks/run", json=body, timeout=float(c.get("timeout_s") or 3600))
    except httpx.HTTPError as e:
        raise MusicError(f"音樂伺服器連不上：{e}") from e
    if r.status_code != 200:
        raise MusicError(f"音樂生成失敗 HTTP {r.status_code}：{r.text[:300]}")
    data = r.json()
    audio = data.get("audio")
    if not audio:
        raise MusicError(f"音樂生成沒有回傳音檔：{json.dumps(data, ensure_ascii=False)[:300]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(audio))
    return path


def duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0.0


def status() -> dict:
    c = cfg()
    base = (c.get("base_url") or store.get_settings()["tts"]["base_url"]).rstrip("/")
    model = c.get("model") or "yue2"
    info = {"enabled": bool(c.get("enabled", True)), "base_url": base, "model": model,
            "style": style_of(), "cache": str(cache_dir()), "models": [], "ok": False, "detail": ""}
    try:
        r = httpx.get(base + "/v1/models", timeout=5)
        r.raise_for_status()
        info["models"] = [m.get("id") for m in r.json().get("data", [])]
        info["ok"] = model in info["models"]
        info["detail"] = "就緒" if info["ok"] else f"伺服器上沒有 {model}"
    except httpx.HTTPError as e:
        info["detail"] = f"audio.cpp 伺服器連不上：{e}"
    info["cached"] = sorted(p.name for p in cache_dir().glob("bgm_*.wav"))
    return info


def mix(video_in: Path, bgm: Path, out: Path, total: float, gain_db: float = -20.0,
        duck: bool = True, fade_in: float = 1.2, fade_out: float = 2.0) -> Path:
    """Lay the bed under the existing mix, ducking it while narration plays, then loudnorm."""
    bed = (f"[1:a]aresample=48000,volume={gain_db:g}dB,"
           f"afade=t=in:st=0:d={fade_in:g},afade=t=out:st={max(0.0, total - fade_out):.2f}:d={fade_out:g}")
    if duck:
        graph = (f"[0:a]asplit=2[nar][sc];{bed}[bg];"
                 f"[bg][sc]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[duck];"
                 f"[nar][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,"
                 f"loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    else:
        graph = (f"{bed}[bg];[0:a][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95,"
                 f"loudnorm=I=-16:TP=-1.5:LRA=11[a]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_in),
           "-stream_loop", "-1", "-i", str(bgm), "-filter_complex", graph,
           "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise MusicError(f"背景音樂混音失敗：{r.stderr[-500:]}")
    return out


def probe_wav(p: Path) -> dict:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True)
    log = out.stdout + out.stderr
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", log)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", log)
    return {"mean_db": float(mean.group(1)) if mean else None, "max_db": float(peak.group(1)) if peak else None,
            "duration": round(duration(p), 2)}


def cli_available() -> bool:
    return bool(shutil.which("audiocpp_cli"))
