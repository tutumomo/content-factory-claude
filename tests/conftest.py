"""Offline smoke-test harness.

The app reads CF_DATA at import time, so it is pointed at a throw-away folder before `app` is
imported. Every service that would touch the network or the GPU (audio.cpp TTS/alignment, stock
footage, ComfyUI, MiniMax-H3, music, Remotion) is replaced with a local fake that writes real
media files, so ffmpeg, subtitles, verify and the publish package run for real.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import pytest

_DATA = Path(tempfile.mkdtemp(prefix="cf-smoke-data-"))
os.environ["CF_DATA"] = str(_DATA)

from fastapi.testclient import TestClient  # noqa: E402

from app import comfy, h3video, llm, main, media, music, pipeline, stock, store, video  # noqa: E402

RATE = 24000


def _tone_wav(out: Path, seconds: float, freq: float = 220.0, amp: float = 0.3) -> Path:
    """Speech-like tone: amplitude-modulated so loudness checks see a voice, not silence."""
    n = int(seconds * RATE)
    frames = bytearray()
    for i in range(n):
        t = i / RATE
        env = 0.6 + 0.4 * math.sin(2 * math.pi * 3 * t)
        frames += struct.pack("<h", int(32767 * amp * env * math.sin(2 * math.pi * freq * t)))
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return out


def _test_video(out: Path, seconds: float, size: tuple[int, int] = (640, 360), audio: bool = False) -> Path:
    """Moving test pattern (testsrc2) so the 'picture changes' check has real motion."""
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
           "-i", f"testsrc2=size={w}x{h}:rate=30:duration={seconds:.2f}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds:.2f}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True)
    return out


class Fakes:
    """Counts calls so tests can assert which sources were actually used."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    # audio.cpp
    def tts_health(self) -> dict:
        return {"ok": True, "models": ["fake"], "detail": "就緒（fake）"}

    def tts(self, text: str, out: Path, emotion: str = "") -> Path:
        self.hit("tts")
        chars = len(re.sub(r"\s", "", text))
        # ~0.6–1.2 s per scene keeps a whole episode quick while staying above the 2 char/s speed check
        return _tone_wav(out, max(0.8, chars / 9.0))

    def align(self, wav: Path, text: str):
        self.hit("align")
        chars = [c for c in text if re.match(r"\w", c)]
        dur = media.wav_duration(wav)
        step = dur / max(1, len(chars))
        return [{"word": c, "start": i * step, "end": (i + 1) * step} for i, c in enumerate(chars)]

    # stock footage
    def stock_status(self) -> dict:
        return {"providers": ["pexels"], "detail": "fake"}

    def stock_fetch(self, query: str, vertical: bool = False):
        self.hit("stock")
        p = stock.cache_dir() / "fake_stock.mp4"
        if not p.exists():
            _test_video(p, 6, (360, 640) if vertical else (640, 360))
        return {"path": p, "provider": "pexels", "author": "fake", "page": "https://example.invalid/v",
                "license": "Pexels", "duration": 6.0, "query": query}

    # ComfyUI / H3
    def comfy_health(self) -> dict:
        return {"ok": True, "detail": "ComfyUI 就緒（fake）"}

    def comfy_generate(self, prompt: str, size, out: Path, seed=None) -> Path:
        from PIL import Image
        self.hit("comfy")
        out.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, ((seed or 0) * 37 % 255, 90, 140)).save(out, quality=85)
        return out

    def h3_generate(self, desc: str, size, seconds: float, out: Path, i: int = 0, seed=None) -> Path:
        self.hit("h3video")
        return _test_video(out, min(6.0, max(2.0, seconds)), (320, 576) if size[1] > size[0] else (576, 320),
                           audio=True)

    # music (all providers)
    def music_generate(self, seconds: float, style: str = "", seed=None, out=None, force=False, eid="",
                       source: str = ""):
        name = (source or music.provider()).lower()
        self.hit("music:" + name)
        p = music.cache_dir() / f"fake_bgm_{name}.wav"
        if not p.exists():
            _tone_wav(p, max(8.0, seconds), freq=110.0, amp=0.2)
        return p

    # Remotion
    def remotion_available(self) -> dict:
        return {"ok": True, "dir": "fake", "detail": "就緒（fake）"}

    def remotion_render(self, assets: Path, props: dict, out: Path, timeout: int = 3600) -> Path:
        self.hit("remotion")
        frames = sum(s["frames"] for s in props["scenes"])
        return _test_video(out, frames / props["fps"], (props["width"], props["height"]))


@pytest.fixture(scope="session")
def data_dir() -> Path:
    sfx = _DATA / "sfx"
    for tag in ("whoosh", "ding", "pop", "click"):
        _tone_wav(sfx / f"{tag}__fake.wav", 0.6, freq=880.0, amp=0.2)
    yield _DATA
    if not os.environ.get("CF_KEEP_DATA"):
        shutil.rmtree(_DATA, ignore_errors=True)


@pytest.fixture
def fakes(data_dir) -> Fakes:
    f = Fakes()
    mp = pytest.MonkeyPatch()
    real_json = llm.complete_json

    def short_json(task, system, prompt):
        """Mock script: 3 short scenes, so a matrix row renders in a few seconds.

        The narration stays in the 2–9 char/s band the assemble stage checks for.
        """
        data = real_json(task, system, prompt)
        if task in ("script", "revise") and isinstance(data, dict):
            data["scenes"] = data["scenes"][:3]
            for i, sc in enumerate(data["scenes"]):
                sc["narration"] = f"第{i + 1}段測試旁白，說明這個主題的重點。"
        return data

    mp.setattr(llm, "complete_json", short_json)
    mp.setattr(media, "tts_health", f.tts_health)
    mp.setattr(media, "tts", f.tts)
    mp.setitem(media.TTS_SOURCES, "audiocpp", f.tts)
    mp.setattr(media, "align", f.align)
    mp.setattr(stock, "status", f.stock_status)
    mp.setattr(stock, "fetch", f.stock_fetch)
    mp.setattr(comfy, "health", f.comfy_health)
    mp.setattr(comfy, "generate", f.comfy_generate)
    mp.setattr(comfy, "free", lambda: None)
    mp.setattr(h3video, "generate", f.h3_generate)
    mp.setattr(music, "generate", f.music_generate)
    mp.setattr(video, "available", f.remotion_available)
    mp.setattr(video, "render", f.remotion_render)
    # nothing in the smoke test may reach a real web page
    mp.setattr(pipeline, "fetch_text", lambda url, limit=6000: "（測試：不抓網頁）")
    mp.setattr(pipeline.websearch, "search",
               lambda ep, gaps=None, tried=None, limit=3, choice="auto": {"engine": "", "results": [], "errors": []})
    yield f
    mp.undo()


@pytest.fixture(scope="session")
def client(data_dir):
    # one TestClient for the whole session: each startup starts another worker thread
    with TestClient(main.app) as c:
        yield c


def set_settings(c: TestClient, **sections) -> dict:
    s = c.get("/api/settings").json()
    for sec, vals in sections.items():
        s.setdefault(sec, {}).update(vals)
    r = c.put("/api/settings", json=s)
    assert r.status_code == 200, r.text
    return r.json()


def wait_for(c: TestClient, eid: str, timeout: float = 300) -> dict:
    """Wait until the worker parks the episode at a gate, finishes, or fails."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ep = c.get(f"/api/episodes/{eid}").json()
        if ep["status"] in ("waiting", "done", "error") and not pipeline.busy()["current"] \
                and pipeline.busy()["queued"] == 0:
            return ep
        time.sleep(0.2)
    raise AssertionError(f"{eid} 卡住：{ep['stage']}/{ep['status']}；log 尾：{ep['log'][-3:]}")


# answers for every gate, used by run_to_done
GATE_ACTIONS = {
    "sources": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/sources", json={"proceed": True}),
    "direction": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/direction",
                                           json={"id": ep["files"]["brief"]["directions"][0]["id"]}),
    "script": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/script", json={"approve": True}),
    "storyboard": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/storyboard", json={"approve": True}),
    "cost": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/cost"),
    "package": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/package", json={"title": 0, "thumb": 0}),
    "approval": lambda c, eid, ep: c.post(f"/api/episodes/{eid}/approve"),
}


def run_to_done(c: TestClient, eid: str, max_gates: int = 12) -> tuple[dict, list[str]]:
    seen: list[str] = []
    for _ in range(max_gates):
        ep = wait_for(c, eid)
        if ep["status"] == "done":
            return ep, seen
        assert ep["status"] == "waiting", f"{eid} 出錯：{ep.get('error')}\n" + "\n".join(
            (x if isinstance(x, str) else str(x)) for x in ep["log"][-8:])
        seen.append(ep["waiting_for"])
        r = GATE_ACTIONS[ep["waiting_for"]](c, eid, ep)
        assert r.status_code == 200, (ep["waiting_for"], r.status_code, r.text)
    raise AssertionError(f"{eid} 過了 {max_gates} 個閘門還沒完成：{seen}")
