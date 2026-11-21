"""Sound-effect library: fixed tag vocabulary, local index, MOSS-SoundEffect generation.

The library is a plain folder of short wav/mp3 files named `<tag>__<anything>.wav`.
Assembly only reads from the library, so a batch runs without touching the GPU.
New files are made either by `build()` (audio.cpp MOSS-SoundEffect) or by importing a folder.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import store

AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

# tags that read as ambience rather than a one-shot: generate longer
AMBIENCE = {"crowd", "wind", "water", "fire", "birds", "city", "night", "glitch"}

# tag: (中文名, 給音效模型的英文描述)
TAGS: dict[str, tuple[str, str]] = {
    "whoosh": ("咻・轉場", "quick airy air whoosh transition, soft swoosh"),
    "riser": ("上升音", "short rising tension riser building to a soft hit"),
    "impact": ("重擊", "single deep cinematic impact thud with a short tail"),
    "ding": ("叮", "bright single bell ding, clean and short"),
    "pop": ("彈出", "small cartoon pop sound, quick and round"),
    "click": ("喀", "single crisp UI click"),
    "paper": ("翻頁", "paper page turn swish"),
    "keyboard": ("打字", "fast mechanical keyboard typing burst"),
    "phone": ("通知", "smartphone notification chime"),
    "cash": ("收銀", "cash register ding with coins"),
    "alarm": ("警示", "short digital alarm beep pattern"),
    "glitch": ("雜訊", "digital glitch stutter burst"),
    "heartbeat": ("心跳", "slow heartbeat thump thump"),
    "crowd": ("人群", "distant crowd murmur ambience"),
    "wind": ("風", "soft wind ambience"),
    "water": ("水", "water splash and drip"),
    "fire": ("火", "crackling fire ambience"),
    "birds": ("鳥", "morning birds chirping ambience"),
    "city": ("城市", "city street ambience with light traffic"),
    "night": ("夜晚", "quiet night ambience with crickets"),
    "scifi": ("科幻", "sci-fi interface beeps and servo sweep"),
    "sparkle": ("發光", "magical sparkle shimmer"),
    "error": ("錯誤", "video game error buzz"),
    "success": ("成功", "positive success chime, two notes"),
}

DEFAULT_MODEL = "/mnt/gdrive/Models/MOSS-SoundEffect-v2-GGUF/moss-soundeffect-v2-q8_0.gguf"
SPEC_DIR = "/home/altos/audio.cpp/model_specs"


class SfxError(RuntimeError):
    pass


def cfg() -> dict:
    return store.get_settings().get("sfx") or {}


def lib_dir() -> Path:
    d = Path(cfg().get("library_dir") or (store.DATA / "sfx"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def vocab() -> dict[str, str]:
    return {k: v[0] for k, v in TAGS.items()}


def normalize(tag: str) -> str:
    """Accept a slug or the Chinese label; anything else becomes '' (no sound)."""
    t = (tag or "").strip()
    if t.lower() in TAGS:
        return t.lower()
    for k, (label, _) in TAGS.items():
        if t == label or t == label.split("・")[0]:
            return k
    return ""


def tag_of(path: Path) -> str:
    stem = path.stem
    if "__" in stem:
        return stem.split("__", 1)[0].lower()
    m = re.match(r"[a-z]+", stem.lower())
    return m.group(0) if m else "other"


def index() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for p in sorted(lib_dir().iterdir()):
        if p.is_file() and p.suffix.lower() in AUDIO_EXT:
            key = tag_of(p)
            out.setdefault(key, []).append(p)
    return out


def pick(tag: str, salt: str = "") -> Path | None:
    """Deterministic pick so a rerun of the same episode keeps the same sounds."""
    files = index().get(tag.strip().lower()) or []
    if not files:
        return None
    return files[sum(map(ord, salt)) % len(files)]


def status() -> dict:
    idx = index()
    model = Path(cfg().get("model_path") or DEFAULT_MODEL)
    return {
        "dir": str(lib_dir()),
        "total": sum(len(v) for v in idx.values()),
        "tags": [{"tag": k, "label": v[0], "count": len(idx.get(k, []))} for k, v in TAGS.items()],
        "model": {"path": str(model), "ok": model.exists(), "cli": bool(shutil.which("audiocpp_cli"))},
    }


def import_files(folder: str, tag: str = "") -> dict:
    """Copy audio files from a user folder. Name them `tag__note.wav` to set the tag explicitly."""
    src = Path(folder).expanduser()
    if not src.is_dir():
        raise SfxError(f"找不到資料夾：{src}")
    dst = lib_dir()
    moved, skipped = [], []
    for p in sorted(src.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXT:
            continue
        name = p.name
        if tag and "__" not in name:
            name = f"{tag.strip().lower()}__{name}"
        target = dst / name
        if target.exists():
            skipped.append(name)
            continue
        shutil.copy2(p, target)
        moved.append(name)
    return {"copied": moved, "skipped": skipped}


def generate(tag: str, out: Path | None = None, duration: float | None = None) -> Path:
    if tag not in TAGS:
        raise SfxError(f"未知音效標籤：{tag}")
    duration = duration or (8.0 if tag in AMBIENCE else 3.0)
    model = Path(cfg().get("model_path") or DEFAULT_MODEL)
    if not model.exists():
        raise SfxError(f"找不到音效模型：{model}")
    cli = shutil.which("audiocpp_cli")
    if not cli:
        raise SfxError("找不到 audiocpp_cli")
    out = out or (lib_dir() / f"{tag}__{int(time.time())}.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [cli, "--model", str(model), "--family", "moss_soundeffect", "--task", "gen",
           "--backend", "cuda"]
    if Path(SPEC_DIR).is_dir():
        cmd += ["--model-spec-override", SPEC_DIR]
    cmd += ["--text", TAGS[tag][1], "--request-option", f"duration_sec={duration:g}", "--out", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not out.exists():
        raise SfxError(f"音效生成失敗：{(r.stderr or r.stdout)[-400:]}")
    return out


BUILD: dict = {"running": False, "done": 0, "total": 0, "current": "", "last": {}, "error": None}


def build(tags: list[str] | None = None, force: bool = False, per_tag: int = 1) -> dict:
    """Generate missing tags one by one. Each call loads the model, so this is a slow batch job."""
    have = index()
    todo = [t for t in (tags or list(TAGS)) if t in TAGS]
    made, errors = [], []
    BUILD.update(running=True, done=0, total=len(todo), current="", last={}, error=None)
    try:
        for t in todo:
            BUILD["current"] = t
            ok = True
            if force or not have.get(t):
                for _ in range(per_tag):
                    try:
                        made.append(str(generate(t)))
                    except Exception as e:  # keep going; report at the end
                        errors.append({"tag": t, "error": str(e)})
                        ok = False
                        break
            BUILD.update(done=BUILD["done"] + 1, last={"tag": t, "ok": ok})
    finally:
        BUILD.update(running=False, current="")
    res = {"generated": made, "errors": errors, "status": status()}
    BUILD["last"] = res
    return res


def build_async(tags: list[str] | None = None, force: bool = False) -> dict:
    import threading
    if BUILD.get("running"):
        return {"started": False, "state": dict(BUILD), "error": "已經在生成中"}
    threading.Thread(target=build, kwargs={"tags": tags, "force": force}, daemon=True, name="sfx-build").start()
    return {"started": True, "state": dict(BUILD)}


def manifest() -> Path:
    p = lib_dir() / "tags.json"
    p.write_text(json.dumps(vocab(), ensure_ascii=False, indent=2), "utf-8")
    return p
