"""Narration (audio.cpp TTS + forced alignment), subtitles and ffmpeg assembly, with measured checks."""
from __future__ import annotations

import json
import os
import re
import subprocess
import wave
from pathlib import Path

import httpx

from . import store

PUNCT = "，。！？；：、,.!?;:…—「」『』（）()\"'"
_CC = None  # lazily built OpenCC converter (tw2sp); False when the package is missing


class MediaError(RuntimeError):
    pass


def run(cmd: list[str], timeout: int = 1800) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise MediaError(f"{cmd[0]} 失敗：{r.stderr[-600:]}")
    return r.stdout + r.stderr


def _post_busy_retry(url: str, wait_total: float = 900, **kw) -> httpx.Response:
    """audio.cpp answers 503 server_busy while another client holds its single model slot; wait and retry."""
    import time
    deadline = time.time() + wait_total
    delay = 3.0
    while True:
        r = httpx.post(url, **kw)
        if r.status_code != 503 or time.time() > deadline:
            return r
        time.sleep(delay)
        delay = min(delay * 1.5, 30)
        for v in (kw.get("files") or {}).values():  # rewind uploaded file handles
            if hasattr(v[1], "seek"):
                v[1].seek(0)


def tts_health(timeout: float = 5) -> dict:
    cfg = store.get_settings()["tts"]
    try:
        r = httpx.get(cfg["base_url"].rstrip("/") + "/v1/models", timeout=timeout)
        r.raise_for_status()
        ids = [m.get("id") for m in r.json().get("data", [])]
        return {"ok": cfg["model"] in ids, "models": ids,
                "detail": "就緒" if cfg["model"] in ids else f"伺服器上沒有 {cfg['model']}"}
    except httpx.HTTPError as e:
        return {"ok": False, "models": [], "detail": f"audio.cpp 伺服器連不上：{e}（請先執行 audiocpp-webui 或啟動 audiocpp_server）"}


VOICE_TASKS = {"tts", "clon", "vdes"}  # audio.cpp task tokens that produce narration
BUILTIN_VOICES = ("vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee")


def list_models(base_url: str | None = None) -> dict:
    """Every model the audio.cpp server has registered, split into voice-capable and the rest.

    `voices` is the server-side reference library (voice_dir WAVs + presets), which is what
    the settings page offers as 參考音色; `builtin` are the model's own speaker names.
    """
    cfg = store.get_settings()["tts"]
    base = (base_url or cfg["base_url"]).rstrip("/")
    out = {"base_url": base, "models": [], "other": [], "current": cfg["model"],
           "voices": [], "builtin": list(BUILTIN_VOICES), "ok": False, "detail": ""}
    try:
        r = httpx.get(base + "/v1/models", timeout=5)
        r.raise_for_status()
        rows = r.json().get("data", [])
    except httpx.HTTPError as e:
        out["detail"] = f"audio.cpp 伺服器連不上：{e}"
        return out
    for m in rows:
        item = {"id": m.get("id"), "family": m.get("family") or "", "task": m.get("task") or "",
                "loaded": bool(m.get("loaded"))}
        (out["models"] if item["task"] in VOICE_TASKS else out["other"]).append(item)
    out["ok"] = bool(out["models"])
    out["detail"] = f"{len(out['models'])} 個語音模型" if out["ok"] else "伺服器上沒有語音模型"
    try:
        vr = httpx.get(base + "/v1/audio/voices", params={"model": cfg["model"]}, timeout=5)
        if vr.status_code == 200:
            out["voices"] = [v for v in vr.json().get("voices", []) if v not in BUILTIN_VOICES]
    except httpx.HTTPError:
        pass
    return out


def split_for_tts(text: str, limit: int = 110) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])", text)
    chunks, cur = [], ""
    for p in parts:
        if not p.strip():
            continue
        if len(cur) + len(p) > limit and cur:
            chunks.append(cur)
            cur = p
        else:
            cur += p
    if cur.strip():
        chunks.append(cur)
    out = []
    for c in chunks:  # hard split anything still too long at commas
        while len(c) > limit * 1.6:
            cut = max(c.rfind("，", 0, limit), c.rfind(",", 0, limit))
            cut = cut + 1 if cut > 0 else limit
            out.append(c[:cut])
            c = c[cut:]
        out.append(c)
    return [c.strip() for c in out if c.strip()]


def to_simplified(text: str) -> str:
    """audio.cpp 的 TTS 對繁體字常讀錯，送進去前先轉簡體（台灣用詞一併轉，例如 軟體→软件）。字幕仍用原文。"""
    global _CC
    if not text:
        return text
    if _CC is None:
        try:
            from opencc import OpenCC
            _CC = OpenCC("tw2sp")
        except ImportError:
            _CC = False
    if _CC is False:
        return text
    return _CC.convert(text)


def tts(text: str, out: Path, emotion: str = "") -> Path:
    """Narration from the audio.cpp server (qwen3 / index-tts2.5 / zonos3 …)."""
    cfg = store.get_settings()["tts"]
    if cfg.get("convert_simplified", True) and str(cfg.get("language", "")).lower() in ("chinese", "中文", "zh"):
        text = to_simplified(text)
    opts = {k: v for k, v in (("language", cfg.get("language")), ("instruct", cfg.get("instruct"))) if v}
    emo = (emotion or "").strip() or (cfg.get("emotion") or "")
    if emo:
        if cfg["model"].startswith("qwen3"):
            # qwen3 takes a free-text instruct: fold the per-scene emotion into it
            opts["instruct"] = "，".join(x for x in (opts.get("instruct"), f"語氣：{emo}") if x)
        else:
            opts["emotion"] = emo
            opts["emotion_alpha"] = float(cfg.get("emotion_alpha") or 1.0)
    body = {"model": cfg["model"], "input": text}
    voice = (cfg.get("voice") or "").strip()
    library_voice = bool(voice) and voice not in BUILTIN_VOICES
    if voice and (cfg["model"].startswith("qwen3") or library_voice):
        body["voice"] = voice
    if library_voice and cfg["model"].startswith("qwen3"):
        # voice_dir recordings in this library carry no transcript, so ask Qwen3 for the
        # speaker-embedding clone instead of ICL (which would demand reference_text).
        opts["x_vector_only_mode"] = True
    if cfg.get("voice_ref"):
        body["voice_ref"] = cfg["voice_ref"]
    if opts:
        body["options"] = opts
    try:
        # Cap the 503 wait so a busy server falls through to the next voice source instead of
        # holding the episode for 15 minutes; the chain (sources.Narrator) handles what comes next.
        r = _post_busy_retry(cfg["base_url"].rstrip("/") + "/v1/audio/speech", json=body, timeout=300,
                             wait_total=float(cfg.get("busy_wait_s") or 120))
    except httpx.HTTPError as e:
        raise MediaError(f"TTS 連線失敗：{e}") from e
    if r.status_code != 200 or not r.content.startswith(b"RIFF"):
        raise MediaError(f"TTS 失敗 HTTP {r.status_code}：{r.text[:300]}")
    out.write_bytes(r.content)
    return out


# ---------- fallback voices (voice chain: see sources.py) ----------

EDGE_VOICE_DEFAULT = "zh-TW-HsiaoChenNeural"
GEMINI_TTS_API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TTS_DEFAULT = "gemini-2.5-flash-preview-tts"
GEMINI_VOICE_DEFAULT = "Kore"


def _to_wav(src: Path, out: Path, rate: int = 24000, raw: bool = False) -> Path:
    """Any TTS output → 24 kHz mono 16-bit wav, so chunks from different sources can be joined.

    `raw` means headerless PCM (Gemini TTS returns audio/L16), which ffmpeg needs told up front.
    """
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if raw:
        cmd += ["-f", "s16le", "-ar", str(rate), "-ac", "1"]
    run(cmd + ["-i", str(src), "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", str(out)])
    return out


def edge_tts(text: str, out: Path, emotion: str = "") -> Path:
    """Free Microsoft Edge read-aloud endpoint (community `edge-tts` package, no key).

    Unofficial endpoint: give it a short timeout and let the caller fall through on any failure.
    It has no alignment data, so subtitles stay on the character-count estimate.
    """
    import asyncio
    cfg = store.get_settings()["tts"]
    voice = (cfg.get("edge_voice") or EDGE_VOICE_DEFAULT).strip()
    text = (text or "").strip()
    if not text:
        raise MediaError("Edge TTS 沒有文字")
    try:
        import edge_tts
    except ImportError as e:
        raise MediaError("沒有 edge-tts 套件（pip install edge-tts）") from e
    mp3 = out.with_suffix(".edge.mp3")
    tmo = float(cfg.get("edge_timeout_s") or 60)

    async def _run():
        await asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(mp3)), timeout=tmo)

    try:
        asyncio.run(_run())
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001 - any failure means "try the next source"
        raise MediaError(f"Edge TTS 失敗（{voice}）：{type(e).__name__}: {e}") from e
    if not (mp3.exists() and mp3.stat().st_size > 1000):
        raise MediaError("Edge TTS 沒有回傳音檔")
    return _to_wav(mp3, out)


def gemini_tts(text: str, out: Path, emotion: str = "") -> Path:
    """Paid Google Gemini TTS. Callers must pass cost.decide first (sources.Narrator does)."""
    import base64
    cfg = store.get_settings()["tts"]
    name = (cfg.get("gemini_key_env") or "GEMINI_API_KEY").strip()
    key = os.environ.get(name, "")
    if not key:
        raise MediaError(f"沒有環境變數 {name}")
    model = (cfg.get("gemini_model") or GEMINI_TTS_DEFAULT).strip()
    voice = (cfg.get("gemini_voice") or GEMINI_VOICE_DEFAULT).strip()
    text = (text or "").strip()
    if not text:
        raise MediaError("Gemini TTS 沒有文字")
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    try:
        r = httpx.post(GEMINI_TTS_API.format(model=model), json=body, timeout=float(cfg.get("gemini_timeout_s") or 180),
                       headers={"x-goog-api-key": key})
    except httpx.HTTPError as e:
        raise MediaError(f"Gemini TTS 連線失敗：{e}") from e
    if r.status_code == 429:
        detail = r.text[:300]
        if "spending" in detail.lower() or "billing" in detail.lower():
            raise MediaError(f"Gemini 專案本月花費上限（429 spending cap）：{detail}")
        raise MediaError(f"Gemini TTS 被限流（429）：{detail}")
    if r.status_code in (401, 403):
        raise MediaError(f"Gemini 金鑰無效或沒有權限（HTTP {r.status_code}）：{r.text[:200]}")
    if r.status_code != 200:
        raise MediaError(f"Gemini TTS 失敗 HTTP {r.status_code}：{r.text[:300]}")
    try:
        part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError, ValueError):
        raise MediaError(f"Gemini TTS 沒有回傳音訊：{r.text[:300]}")
    raw = base64.b64decode(part.get("data") or "")
    if not raw:
        raise MediaError("Gemini TTS 回傳空音訊")
    if raw[:4] == b"RIFF":
        tmp = out.with_suffix(".gemini.wav")
        tmp.write_bytes(raw)
        return _to_wav(tmp, out)
    # raw PCM: sample rate comes in the mime type, e.g. audio/L16;codec=pcm;rate=24000
    m = re.search(r"rate=(\d+)", str(part.get("mimeType") or ""))
    pcm = out.with_suffix(".gemini.pcm")
    pcm.write_bytes(raw)
    return _to_wav(pcm, out, rate=int(m.group(1)) if m else 24000, raw=True)


TTS_SOURCES = {"audiocpp": tts, "edge": edge_tts, "gemini": gemini_tts}


def tts_with(source: str, text: str, out: Path, emotion: str = "") -> Path:
    """Narration from one named source; unknown ids fail cleanly so the chain can move on."""
    fn = TTS_SOURCES.get((source or "").lower())
    if not fn:
        raise MediaError(f"未知的配音來源：{source}")
    return fn(text, out, emotion=emotion)


def wav_duration(p: Path) -> float:
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def audio_duration(p: Path) -> float:
    """Duration of any audio file (wav read directly, others through ffprobe)."""
    try:
        return wav_duration(p)
    except (wave.Error, EOFError):
        out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)])
        return float(out.strip().splitlines()[-1])


def has_audio(p: Path) -> bool:
    """True when the media file has at least one audio stream."""
    try:
        out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                   "-of", "csv=p=0", str(p)], timeout=60)
    except Exception:
        return False
    return bool(out.strip())


def concat_wavs(parts: list[Path], out: Path, gap: float = 0.18) -> Path:
    with wave.open(str(parts[0])) as w0:
        params = w0.getparams()
    silence = b"\x00" * int(params.framerate * gap) * params.sampwidth * params.nchannels
    with wave.open(str(out), "wb") as o:
        o.setparams(params)
        for i, p in enumerate(parts):
            with wave.open(str(p)) as w:
                if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (params.framerate, params.sampwidth, params.nchannels):
                    raise MediaError("TTS 片段格式不一致")
                o.writeframes(w.readframes(w.getnframes()))
            if i < len(parts) - 1:
                o.writeframes(silence)
    return out


def align(wav: Path, text: str) -> list[dict] | None:
    cfg = store.get_settings()["tts"]
    if not cfg.get("align_model"):
        return None
    try:
        with wav.open("rb") as fh:
            r = _post_busy_retry(cfg["base_url"].rstrip("/") + "/v1/audio/alignments",
                           data={"model": cfg["align_model"], "text": text, "language": cfg["align_language"]},
                           files={"file": (wav.name, fh, "audio/wav")}, timeout=600)
        r.raise_for_status()
        return r.json().get("words") or None
    except (httpx.HTTPError, json.JSONDecodeError):
        return None


def _clean(s: str) -> str:
    return re.sub(r"[\W_]+", "", s)


def cues_for_scene(narration: str, words: list[dict] | None, duration: float, max_chars: int) -> list[dict]:
    """Phrase-level cues. Uses aligner word times when available, else proportional timing."""
    # split on CJK punctuation; split on ASCII punctuation only when it is not inside a word or
    # number (keeps "audio.cpp", "v0.9.5", "1,000" intact)
    splitter = r"[，。！？；：、…\n]+|(?<![A-Za-z0-9])[,.!?;:]+|[,.!?;:]+(?![A-Za-z0-9])"
    phrases = [p.strip() for p in re.split(splitter, narration) if p and p.strip()]
    pieces = []
    for p in phrases:  # split long phrases into even parts instead of a ragged tail
        k = -(-len(p) // max_chars)
        step = -(-len(p) // k)
        start = 0
        for _ in range(k - 1):
            cut = start + step
            near = [j for j in range(max(start + 2, cut - 4), min(len(p) - 1, cut + 4)) if p[j] == " "]
            if near:
                cut = min(near, key=lambda j: abs(j - (start + step)))
            else:  # never cut inside a latin word / number
                latin = re.compile(r"[A-Za-z0-9.]")
                inside = lambda j: 0 < j < len(p) and latin.match(p[j - 1]) and latin.match(p[j])
                if inside(cut):
                    left, right = cut, cut
                    while inside(left) and left > start + 1:
                        left -= 1
                    while inside(right) and right < len(p) - 1:
                        right += 1
                    cut = left if (cut - left) <= (right - cut) and left > start + 1 else right
            pieces.append(p[start:cut].strip())
            start = cut
        pieces.append(p[start:].strip())
    cues = []
    if words:
        wi = 0
        for p in pieces:
            need = len(_clean(p))
            got, start, end = 0, None, None
            while wi < len(words) and got < need:
                w = words[wi]
                start = w["start"] if start is None else start
                end = w["end"]
                got += len(_clean(w["word"])) or 1
                wi += 1
            if start is None:
                break
            cues.append({"start": start, "end": end, "text": p})
        if len(cues) == len(pieces):
            for a, b in zip(cues, cues[1:]):  # close tiny gaps so text does not flicker
                if b["start"] - a["end"] < 0.25:
                    a["end"] = b["start"]
            return cues
    total = sum(len(p) for p in pieces) or 1
    t, cues = 0.0, []
    for p in pieces:
        d = duration * len(p) / total
        cues.append({"start": t, "end": t + d, "text": p})
        t += d
    return cues


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(cues: list[dict], size: tuple[int, int], out: Path) -> Path:
    W, H = size
    vertical = H > W
    fs = int(W * (0.066 if vertical else 0.042))
    margin_v = int(H * (0.12 if vertical else 0.06))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK TC,{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{max(3, fs // 12)},1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [f"Dialogue: 0,{_ass_time(c['start'])},{_ass_time(c['end'])},Default,,0,0,0,,{c['text'].replace(chr(10), ' ')}" for c in cues]
    out.write_text(head + "\n".join(lines) + "\n", "utf-8")
    return out


def write_srt(cues: list[dict], out: Path) -> Path:
    def ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    out.write_text("\n".join(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1)), "utf-8")
    return out


def scene_clip(img: Path, wav: Path, out: Path, pad: float = 0.35, sfx: Path | None = None,
               sfx_gain: float = -16.0, sfx_lead: float = 0.12) -> float:
    dur = wav_duration(wav) + pad
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(img), "-i", str(wav)]
    if sfx:
        sd = audio_duration(sfx)
        eff = min(sd, dur - min(sfx_lead, 0.1))
        fout = min(0.8, max(0.25, eff * 0.35))
        fade_st = max(0.0, eff - fout)
        delay = int(min(sfx_lead, max(0.0, dur - 0.1)) * 1000)
        graph = (f"[1:a]apad=pad_dur={pad},aresample=48000[nar];"
                 f"[2:a]aresample=48000,volume={sfx_gain:g}dB,"
                 f"afade=t=in:st=0:d=0.08,afade=t=out:st={fade_st:.2f}:d={fout:.2f},"
                 f"adelay={delay}|{delay}[fx];"
                 f"[nar][fx]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        cmd += ["-i", str(sfx), "-filter_complex", graph]
    else:
        cmd += ["-filter_complex", f"[1:a]apad=pad_dur={pad},aresample=48000[a]"]
    cmd += ["-map", "0:v", "-map", "[a]", "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast",
            "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ac", "2", str(out)]
    run(cmd)
    return dur


def scene_clip_video(bg: Path, wav: Path, out: Path, size: tuple[int, int], pad: float = 0.35,
                     sfx: Path | None = None, sfx_gain: float = -16.0, sfx_lead: float = 0.12,
                     bg_audio_gain: float | None = None) -> float:
    """Narration over looping footage, cropped to the target frame.

    bg_audio_gain (dB) keeps the footage's own soundtrack (e.g. H3 ambience) under the narration;
    None drops it. Footage without an audio stream is treated as silent.
    """
    dur = wav_duration(wav) + pad
    W, H = size
    parts = [f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30,setsar=1[v]",
             f"[1:a]apad=pad_dur={pad},aresample=48000[nar]"]
    mix = ["[nar]"]
    if sfx:
        sd = audio_duration(sfx)
        eff = min(sd, dur - min(sfx_lead, 0.1))
        fout = min(0.8, max(0.25, eff * 0.35))
        fade_st = max(0.0, eff - fout)
        delay = int(min(sfx_lead, max(0.0, dur - 0.1)) * 1000)
        parts.append(f"[2:a]aresample=48000,volume={sfx_gain:g}dB,"
                     f"afade=t=in:st=0:d=0.08,afade=t=out:st={fade_st:.2f}:d={fout:.2f},"
                     f"adelay={delay}|{delay}[fx]")
        mix.append("[fx]")
    if bg_audio_gain is not None and has_audio(bg):
        fo = max(0.0, dur - 0.3)
        # H3 ambience comes out very quiet (~-40 dB mean); level it to narration loudness first so the
        # gain really is "relative to narration"
        parts.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11,"
                     f"aresample=48000,volume={bg_audio_gain:g}dB,"
                     f"afade=t=in:st=0:d=0.2,afade=t=out:st={fo:.2f}:d=0.3[amb]")
        mix.append("[amb]")
    if len(mix) > 1:
        parts.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        parts[1] = parts[1].replace("[nar]", "[a]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(bg), "-i", str(wav)]
    if sfx:
        cmd += ["-i", str(sfx)]
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2", str(out)]
    run(cmd)
    return dur


def concat_and_burn(clips: list[Path], ass: Path, out: Path, workdir: Path, loudnorm: bool = True) -> Path:
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), "utf-8")
    joined = workdir / "joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)])
    ass_arg = str(ass.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined), "-vf", f"subtitles='{ass_arg}'"]
    # with a music bed still to come, loudness is normalised after the mix instead
    cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if loudnorm else []
    run(cmd + ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)])
    return out


def join_clips(clips: list[Path], out: Path, workdir: Path) -> Path:
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), "utf-8")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    return out


def loudnorm_copy(video_in: Path, out: Path) -> Path:
    """Normalise loudness without touching the picture (used before an external video render)."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_in), "-c:v", "copy",
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])
    return out


def extract_audio(video_in: Path, out: Path) -> Path:
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_in), "-vn", "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


def mux_audio(video_in: Path, audio_in: Path, out: Path, total: float) -> Path:
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_in), "-i", str(audio_in),
         "-map", "0:v", "-map", "1:a", "-t", f"{total:.3f}", "-c:v", "copy", "-c:a", "copy",
         "-movflags", "+faststart", str(out)])
    return out


def probe(p: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,codec_name",
               "-of", "json", str(p)])
    return json.loads(out)


def volume(p: Path) -> dict:
    out = run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", "volumedetect", "-vn", "-f", "null", "-"])
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", out)
    peak = re.search(r"max_volume: (-?[\d.]+) dB", out)
    return {"mean_db": float(mean.group(1)) if mean else None, "max_db": float(peak.group(1)) if peak else None}


def silences(p: Path, min_len: float = 2.0) -> list[float]:
    out = run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", f"silencedetect=n=-45dB:d={min_len}", "-vn", "-f", "null", "-"])
    return [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", out)]


def frame(p: Path, t: float, out: Path) -> Path:
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1", "-q:v", "3", str(out)])
    return out


def frame_diffs(p: Path, workdir: Path, step: float = 2.0) -> dict:
    """How much the picture actually changes: share of frame pairs that look identical."""
    from PIL import Image, ImageChops, ImageStat
    frames = sorted(workdir.glob("risk_*.jpg"))
    for f in frames:
        f.unlink()
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf", f"fps=1/{step:g}",
         "-q:v", "4", str(workdir / "risk_%04d.jpg")])
    frames = sorted(workdir.glob("risk_*.jpg"))
    if len(frames) < 2:
        return {"pairs": 0, "avg_diff": 0.0, "static_ratio": 0.0}
    prev = Image.open(frames[0]).convert("L").resize((64, 64))
    diffs = []
    for f in frames[1:]:
        cur = Image.open(f).convert("L").resize((64, 64))
        diffs.append(ImageStat.Stat(ImageChops.difference(prev, cur)).mean[0])
        prev = cur
    static = sum(1 for d in diffs if d < 1.5)
    out = {"pairs": len(diffs), "avg_diff": round(sum(diffs) / len(diffs), 2),
           "static_ratio": round(static / len(diffs), 3)}
    for f in frames:
        f.unlink()
    return out


def verify_video(p: Path, expect_size: tuple[int, int], expect_dur: float, workdir: Path,
                 slideshow_risk_max: float = 0.7) -> dict:
    info = probe(p)
    dur = float(info["format"]["duration"])
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    vol = volume(p)
    sil = silences(p)
    risk = frame_diffs(p, workdir)
    frames = []
    for i, frac in enumerate((0.1, 0.5, 0.9)):
        frames.append(str(frame(p, dur * frac, workdir / f"check_{i}.jpg").relative_to(store.DATA)))
    checks = {
        "播放長度": {"ok": abs(dur - expect_dur) < 1.5, "value": f"{dur:.1f} 秒（預期 {expect_dur:.1f}）"},
        "解析度": {"ok": (v.get("width"), v.get("height")) == expect_size, "value": f"{v.get('width')}x{v.get('height')}"},
        "有音軌": {"ok": a is not None, "value": a["codec_name"] if a else "無"},
        "音量": {"ok": vol["mean_db"] is not None and -30 < vol["mean_db"] < -10 and (vol["max_db"] or 0) <= -0.5,
               "value": f"平均 {vol['mean_db']} dB，峰值 {vol['max_db']} dB"},
        "長靜音段": {"ok": not sil, "value": "無" if not sil else "、".join(f"{s:.1f}s" for s in sil)},
        "畫面變化": {"ok": risk["static_ratio"] <= slideshow_risk_max,
                 "value": f"{risk['static_ratio'] * 100:.0f}% 幀幾乎無變化（上限 {slideshow_risk_max * 100:.0f}%），平均差 {risk['avg_diff']}"},
    }
    return {"checks": checks, "frames": frames, "duration": dur}
