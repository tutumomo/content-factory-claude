"""Background music from audio.cpp music generators, mixed under the narration.

Generation goes through the running audiocpp_server (`POST /v1/tasks/run`), so the model is
loaded once per episode instead of once per scene. Results are cached by (style, seconds, seed),
so re-assembling an episode costs no GPU time.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
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

# Google DeepMind Lyria through the Gemini API "Interactions" endpoint.
LYRIA_API = "https://generativelanguage.googleapis.com/v1beta/interactions"
LYRIA_REVISION = "2026-05-20"
LYRIA_MODELS = {
    "lyria-3-clip-preview": "Lyria 3 Clip（固定 30 秒片段，成片時 loop，$0.04/首）",
    "lyria-3-pro-preview": "Lyria 3 Pro（完整歌曲約 3 分鐘，$0.08/首）",
}


class MusicError(RuntimeError):
    pass


def cfg() -> dict:
    return store.get_settings().get("music") or {}


def provider() -> str:
    return (cfg().get("provider") or "audiocpp").lower()


def lyria_key() -> tuple[str, str]:
    """(key value, env var name). The value is never logged or returned by the API."""
    name = (cfg().get("lyria_key_env") or "GEMINI_API_KEY").strip()
    return os.environ.get(name, ""), name


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


def model_id(base: str) -> str:
    """Configured id when the server has it; otherwise the closest music model of the same family.

    Model ids come from whoever installed the package (the sync tool names them after the
    package, e.g. yue2-main-q8-0), so a stale id should fall back rather than fail.
    """
    want = cfg().get("model") or "yue2"
    try:
        r = httpx.get(base + "/v1/models", timeout=5)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except httpx.HTTPError:
        return want
    ids = [m.get("id") for m in rows]
    if want in ids:
        return want
    prefix = want.split("-")[0].lower()
    for i in ids:                       # same install prefix, e.g. yue2-…
        if str(i).lower().startswith(prefix):
            return i
    for m in rows:                      # same family
        if m.get("family") == family_of(base, want):
            return m.get("id")
    for m in rows:                      # last resort: any installed music generator
        if m.get("task") == "gen" and m.get("family") != "moss_soundeffect":
            return m.get("id")
    return want


def family_of(base: str, model: str) -> str:
    try:
        r = httpx.get(base + "/v1/models", timeout=5)
        r.raise_for_status()
        for m in r.json().get("data", []):
            if m.get("id") == model:
                return (m.get("family") or "").lower()
    except httpx.HTTPError:
        pass
    return model.split("-")[0].lower()


def _key(style: str, seconds: float, seed: int, model: str = "") -> str:
    return hashlib.sha1(f"{model}|{style}|{seconds:.1f}|{seed}".encode()).hexdigest()[:16]


def generate(seconds: float, style: str = "", seed: int | None = None, out: Path | None = None,
             force: bool = False, eid: str = "") -> Path:
    """Render an instrumental bed of `seconds` length (capped) and return the audio path."""
    if provider() == "lyria":
        return lyria_generate(style, seconds, out=out, force=force, eid=eid)
    c = cfg()
    style = (style or "").strip() or (c.get("style") or "").strip() or DEFAULT_STYLE
    seed = int(seed if seed is not None else (c.get("seed") or 1234))
    want = max(8.0, min(float(seconds), MAX_SECONDS))
    base = (c.get("base_url") or store.get_settings()["tts"]["base_url"]).rstrip("/")
    model = model_id(base)
    path = out or (cache_dir() / f"bgm_{_key(style, want, seed, model)}.wav")
    if path.exists() and path.stat().st_size > 44 and not force:
        return path
    fam = family_of(base, model)
    if fam.startswith("minimax_music"):
        # MiniMax Music 3 wants both a text prompt and non-empty lyrics; the bracketed
        # tag is the model's instrumental marker, everything else stays style-driven.
        options = {"lyrics": (c.get("minimax_lyrics") or "[Instrumental]"),
                   "duration_sec": float(round(want)),
                   "num_inference_steps": int(c.get("steps") or 30), "seed": seed}
        if c.get("guidance_scale"):
            options["guidance_scale"] = float(c["guidance_scale"])
        body = {"model": model, "request": {"text": style, "options": options}}
    else:  # yue2: style is the required field, empty lyrics = instrumental
        options = {"style": style, "cot": "off",
                   "semantic_max_tokens": int(round(want * FRAMES_PER_SEC)),
                   "num_inference_steps": int(c.get("steps") or 8), "seed": seed}
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


def _find_audio(node):
    """First audio content block anywhere in an Interactions response."""
    if isinstance(node, dict):
        if node.get("type") in ("audio", "audio_output") and isinstance(node.get("data"), str) and node["data"]:
            return node
        for v in node.values():
            hit = _find_audio(v)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _find_audio(v)
            if hit:
                return hit
    return None


def lyria_generate(style: str = "", seconds: float = 30.0, out: Path | None = None,
                   force: bool = False, eid: str = "") -> Path:
    """Instrumental bed from Google Lyria 3 (Gemini API). Cached per model+prompt."""
    c = cfg()
    key, key_name = lyria_key()
    if not key:
        raise MusicError(f"沒有 Google API 金鑰：請設定環境變數 {key_name}")
    model = (c.get("lyria_model") or "lyria-3-clip-preview").strip()
    style = (style or c.get("style") or "").strip() or DEFAULT_STYLE
    prompt = style.rstrip(".")
    low = prompt.lower()
    if "instrumental" not in low:
        prompt += ", instrumental"
    if "no vocals" not in low:
        prompt += ", no vocals"
    if model != "lyria-3-clip-preview":
        prompt += f", target length about {int(max(20, min(float(seconds), 170)))} seconds"
    prompt += "."
    tag = hashlib.sha1(f"lyria|{model}|{prompt}".encode()).hexdigest()[:16]
    path = out or (cache_dir() / f"bgm_lyria_{tag}.mp3")
    if path.exists() and path.stat().st_size > 1024 and not force:
        return path
    body = {"model": model, "input": prompt}
    if model != "lyria-3-clip-preview":
        body["response_format"] = {"type": "audio"}
    try:
        r = httpx.post(LYRIA_API, json=body, timeout=float(c.get("timeout_s") or 600),
                       headers={"x-goog-api-key": key, "Api-Revision": LYRIA_REVISION})
    except httpx.HTTPError as e:
        raise MusicError(f"Lyria 連線失敗：{e}") from e
    if r.status_code != 200:
        raise MusicError(f"Lyria 生成失敗 HTTP {r.status_code}：{r.text[:300]}")
    data = r.json()
    block = _find_audio(data)
    if not block:
        raise MusicError(f"Lyria 沒有回傳音訊：{json.dumps(data, ensure_ascii=False)[:300]}")
    raw = base64.b64decode(block["data"])
    if raw[:4] == b"RIFF":
        path = path.with_suffix(".wav")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    try:
        from . import cost
        cost.record("lyria", 1, cost.price(model), eid, model)
    except Exception:  # accounting must never fail the render
        pass
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
    cached = sorted(p.name for p in cache_dir().glob("bgm_*.*"))
    if provider() == "lyria":
        key, key_name = lyria_key()
        model = (c.get("lyria_model") or "lyria-3-clip-preview").strip()
        return {"enabled": bool(c.get("enabled", True)), "provider": "lyria", "model": model,
                "models": list(LYRIA_MODELS), "style": style_of(), "cache": str(cache_dir()),
                "key_env": key_name, "key_set": bool(key), "ok": bool(key),
                "detail": "就緒" if key else f"沒有環境變數 {key_name}（Google AI Studio 金鑰）",
                "note": "Lyria 產生的音訊內嵌 SynthID 浮水印；Gemini API 專案需有額度且未達月上限",
                "cached": cached}
    base = (c.get("base_url") or store.get_settings()["tts"]["base_url"]).rstrip("/")
    model = model_id(base)
    info = {"enabled": bool(c.get("enabled", True)), "provider": "audiocpp", "base_url": base,
            "model": model, "style": style_of(), "cache": str(cache_dir()), "models": [],
            "available": [], "ok": False, "detail": ""}
    try:
        r = httpx.get(base + "/v1/models", timeout=5)
        r.raise_for_status()
        rows = r.json().get("data", [])
        info["models"] = [m.get("id") for m in rows]
        info["available"] = [{"id": m.get("id"), "family": m.get("family") or "",
                              "loaded": bool(m.get("loaded"))}
                             for m in rows
                             if m.get("task") == "gen" and m.get("family") != "moss_soundeffect"]
        info["ok"] = model in info["models"]
        info["detail"] = "就緒" if info["ok"] else f"伺服器上沒有 {model}"
    except httpx.HTTPError as e:
        info["detail"] = f"audio.cpp 伺服器連不上：{e}"
    info["cached"] = cached
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
