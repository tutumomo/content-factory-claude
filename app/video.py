"""Remotion render path: build the Episode composition props from the assembled assets and render.

The composition is video-only. Audio (narration + effects + music bed) is prepared once and muxed
afterwards, so both render engines share the same soundtrack.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import store


class VideoError(RuntimeError):
    pass


def project_dir() -> Path:
    d = (store.get_settings().get("render") or {}).get("remotion_dir") or ""
    return Path(d) if d else (store.ROOT / "remotion")


def bin_path() -> Path:
    return project_dir() / "node_modules" / ".bin" / "remotion"


def available() -> dict:
    p = project_dir()
    ok = bin_path().exists()
    return {"ok": ok, "dir": str(p), "detail": "就緒" if ok else f"找不到 {bin_path()}（先在 remotion/ 執行 npm install）"}


def build_props(scenes: list[dict], cues: list[dict], size: tuple[int, int], durations: list[float],
                accent: str = "#ffd166", channel: str = "", fps: int = 30,
                imgs: list[str] | None = None) -> dict:
    out = []
    for i, sc in enumerate(scenes):
        dur = max(1.0, float(durations[i]))
        out.append({
            "img": (imgs[i] if imgs and i < len(imgs) else f"s{i:02d}.jpg"),
            "headline": sc.get("headline") or "",
            "bullets": (sc.get("bullets") or [])[:3],
            "frames": max(1, int(round(dur * fps))),
            "kenBurns": "in" if i % 2 == 0 else "out",
        })
    caps = []
    for c in cues:
        frm = int(round(float(c["start"]) * fps))
        to = max(frm + 1, int(round(float(c["end"]) * fps)))
        caps.append({"from": frm, "to": to, "text": c["text"]})
    return {"width": size[0], "height": size[1], "fps": fps, "accent": accent,
            "channel": channel, "scenes": out, "captions": caps}


def render(assets: Path, props: dict, out: Path, timeout: int = 3600) -> Path:
    if not bin_path().exists():
        raise VideoError(available()["detail"])
    props_file = assets / "remotion_props.json"
    props_file.write_text(json.dumps(props, ensure_ascii=False), "utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(bin_path()), "render", "src/index.ts", "Episode", str(out),
           "--props", str(props_file), "--public-dir", str(assets),
           "--codec", "h264", "--crf", "20", "--pixel-format", "yuv420p",
           "--concurrency", "4", "--log", "error", "--overwrite"]
    r = subprocess.run(cmd, cwd=str(project_dir()), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not out.exists():
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-6:]
        raise VideoError("Remotion 渲染失敗：" + " / ".join(tail)[:600])
    return out
