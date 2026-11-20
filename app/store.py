"""JSON file storage for channel, settings, preferences and episodes."""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EPISODES = DATA / "episodes"
_lock = threading.RLock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "llm": {
        "provider": "claude_cli",          # claude_cli | openai | mock
        "claude_model": "",                # empty = CLI default
        "openai_base_url": "http://127.0.0.1:1234/v1",
        "openai_model": "",
        "openai_key_env": "",              # name of env var holding the key, never the key
        "timeout_s": 600,
    },
    "tts": {
        "base_url": "http://127.0.0.1:8090",
        "model": "qwen3-tts-1.7b-customvoice",
        "voice": "vivian",
        "language": "chinese",
        "instruct": "自然、清楚、有精神的科技節目主持人語氣",
        "align_model": "qwen3-forced-aligner-0.6b",
        "align_language": "Chinese",
    },
    "pipeline": {
        "review_script": True,             # gate: user reviews script before assembly
        "critique_threshold": 8,
        "critique_max_rounds": 3,
        "title_count": 6,
        "thumbnail_count": 4,
    },
}

DEFAULT_CHANNEL: dict[str, Any] = {
    "name": "",
    "topic": "",
    "audience": "",
    "tone": "",
    "benchmarks": "",
    "formats": ["long", "short", "carousel"],
    "platforms": ["YouTube", "Instagram", "Facebook"],
    "taboo": "",
}


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return json.loads(json.dumps(default))
    return json.loads(path.read_text("utf-8"))


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def _merge(default: dict, cur: dict) -> dict:
    out = json.loads(json.dumps(default))
    for k, v in cur.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get_settings() -> dict:
    with _lock:
        return _merge(DEFAULT_SETTINGS, _read(DATA / "settings.json", {}))


def save_settings(s: dict) -> dict:
    with _lock:
        merged = _merge(DEFAULT_SETTINGS, s)
        _write(DATA / "settings.json", merged)
        return merged


def get_channel() -> dict:
    with _lock:
        return _merge(DEFAULT_CHANNEL, _read(DATA / "channel.json", {}))


def save_channel(c: dict) -> dict:
    with _lock:
        merged = _merge(DEFAULT_CHANNEL, c)
        _write(DATA / "channel.json", merged)
        return merged


# ---------- preferences (taste log, principle 3) ----------

SEED_PREFS = [
    {"category": "講稿語氣", "rule": "避免空話開場，例如「在這個 AI 快速發展的時代」。", "date": "預設"},
    {"category": "講稿語氣", "rule": "避免「讓我們一起來看看」「總而言之」等套話。", "date": "預設"},
    {"category": "縮圖", "rule": "候選要涵蓋深色與淺色、人物感與大字兩種方向。", "date": "預設"},
]


def get_prefs() -> list[dict]:
    with _lock:
        return _read(DATA / "preferences.json", SEED_PREFS)


def save_prefs(p: list[dict]) -> list[dict]:
    with _lock:
        _write(DATA / "preferences.json", p)
        return p


def add_pref(category: str, rule: str) -> None:
    with _lock:
        p = get_prefs()
        p.append({"category": category, "rule": rule, "date": datetime.now().strftime("%Y-%m-%d")})
        save_prefs(p)


def prefs_text() -> str:
    lines = [f"- [{p['category']}] {p['rule']}" for p in get_prefs()]
    return "\n".join(lines) if lines else "（尚無）"


# ---------- radar ----------

def get_radar() -> list[dict]:
    with _lock:
        return _read(DATA / "radar.json", [])


def save_radar(items: list[dict]) -> None:
    with _lock:
        _write(DATA / "radar.json", items)


# ---------- episodes ----------

def slugify(text: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", text).strip("-")[:30]
    return s or "episode"


def ep_dir(eid: str) -> Path:
    if not re.fullmatch(r"[\w一-鿿-]+", eid):
        raise ValueError("bad episode id")
    return EPISODES / eid


def new_episode(topic: str, fmt: str, notes: str = "", sources: list[str] | None = None) -> dict:
    with _lock:
        eid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slugify(topic)
        ep = {
            "id": eid,
            "topic": topic,
            "format": fmt,                 # long | short
            "notes": notes,
            "source_urls": sources or [],
            "stage": "sources",
            "status": "queued",            # queued | running | waiting | done | error
            "waiting_for": None,           # direction | script | package | approval
            "error": None,
            "created": time.time(),
            "updated": time.time(),
            "log": [],
            "checks": {},
        }
        ep_dir(eid).mkdir(parents=True, exist_ok=True)
        save_episode(ep)
        return ep


def get_episode(eid: str) -> dict:
    with _lock:
        return _read(ep_dir(eid) / "episode.json", None)


def save_episode(ep: dict) -> None:
    with _lock:
        ep["updated"] = time.time()
        _write(ep_dir(ep["id"]) / "episode.json", ep)


def update_episode(eid: str, **kw) -> dict:
    with _lock:
        ep = get_episode(eid)
        ep.update(kw)
        save_episode(ep)
        return ep


def log(eid: str, msg: str) -> None:
    with _lock:
        ep = get_episode(eid)
        ep["log"].append({"t": time.time(), "msg": msg})
        ep["log"] = ep["log"][-300:]
        save_episode(ep)


def list_episodes() -> list[dict]:
    with _lock:
        out = []
        if EPISODES.exists():
            for d in EPISODES.iterdir():
                f = d / "episode.json"
                if f.exists():
                    ep = json.loads(f.read_text("utf-8"))
                    ep.pop("log", None)
                    out.append(ep)
        return sorted(out, key=lambda e: e["created"], reverse=True)


def write_text(eid: str, name: str, text: str) -> Path:
    p = ep_dir(eid) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, "utf-8")
    return p


def write_json(eid: str, name: str, obj: Any) -> Path:
    p = ep_dir(eid) / name
    _write(p, obj)
    return p


def read_json(eid: str, name: str, default: Any = None) -> Any:
    return _read(ep_dir(eid) / name, default)
