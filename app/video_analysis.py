"""Read a reference video's editing rhythm so a style card can match it.

Statistics are measured with ffmpeg (scene cuts, shot lengths, loudness); the LLM turns them into
a style card. yt-dlp handles links when it is installed. Nothing is uploaded anywhere.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from . import llm, media, prompts, store

TMP = store.DATA / "tmp"


class VideoAnalysisError(RuntimeError):
    pass


def _download(url: str) -> Path:
    try:
        import yt_dlp  # noqa: F401
    except ImportError as e:
        raise VideoAnalysisError("沒有 yt-dlp：請先 .venv/bin/python -m pip install yt-dlp") from e
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / "reference.mp4"
    if out.exists():
        out.unlink()
    cmd = [sys.executable, "-m", "yt_dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
           "--merge-output-format", "mp4", "-o", str(out), url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not out.exists():
        raise VideoAnalysisError(f"下載失敗：{r.stderr.strip()[-300:]}")
    return out


def cuts(path: Path) -> list[float]:
    """Timestamps of hard scene cuts (ffmpeg scene score > 0.3)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-filter:v",
                        "select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    log = r.stderr
    return sorted(float(x) for x in re.findall(r"pts_time:([\d.]+)", log))


def stats(path: Path) -> dict:
    info = media.probe(path)
    dur = float(info["format"]["duration"])
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    pts = cuts(path)
    shots = [b - a for a, b in zip([0.0] + pts, pts + [dur]) if b > a]
    vol = media.volume(path)
    return {"duration": round(dur, 1), "resolution": f"{v.get('width')}x{v.get('height')}",
            "fps": v.get("r_frame_rate"), "cuts": len(pts), "avg_shot": round(sum(shots) / len(shots), 2) if shots else round(dur, 1),
            "cut_density_per_min": round(len(pts) / max(dur / 60, 0.1), 1),
            "longest_shot": round(max(shots), 1) if shots else round(dur, 1),
            "shortest_shot": round(min(shots), 1) if shots else round(dur, 1),
            "mean_db": vol.get("mean_db"), "cut_times": [round(t, 2) for t in pts]}


def analyze(url_or_path: str, name_hint: str = "") -> dict:
    src = url_or_path.strip()
    if not src:
        raise VideoAnalysisError("請給一支參考影片的網址或本機路徑")
    local = Path(src)
    path = local if local.exists() else _download(src)
    st = stats(path)
    cut_times = st.pop("cut_times")
    sysp, pr = prompts.style_from_video(json.dumps(st, ensure_ascii=False), name_hint)
    card = llm.complete_json("style_video", sysp, pr)
    card.setdefault("source", "由參考影片分析")
    card["visual_notes"] = {"avg_shot_seconds": st["avg_shot"], "cut_density_per_min": st["cut_density_per_min"],
                            "reference": src if not local.exists() else str(local)}
    saved = store.create_style(card, activate=False)
    shotlist = [f"# 參考影片節奏（{name_hint or card.get('name', '')}）", "",
                f"- 長度：{st['duration']} 秒｜解析度 {st['resolution']}",
                f"- 切點：{st['cuts']} 個｜平均鏡頭 {st['avg_shot']} 秒｜每分鐘 {st['cut_density_per_min']} 刀",
                f"- 最長／最短鏡頭：{st['longest_shot']}／{st['shortest_shot']} 秒", "",
                "## 分鏡參考", "", "| # | 秒數 | 內容摘要 |", "|---|---|---|"]
    prev = 0.0
    for i, t in enumerate(cut_times + [st["duration"]], 1):
        shotlist.append(f"| {i} | {round(t - prev, 1)} | （參考片第 {i} 個鏡頭） |")
        prev = t
    TMP.mkdir(parents=True, exist_ok=True)   # a local file skips _download, which made the folder
    out = TMP / f"shotlist-{saved['id']}.md"
    out.write_text("\n".join(shotlist) + "\n", "utf-8")
    return {"style": saved, "stats": st, "shotlist": str(out.relative_to(store.DATA))}
