"""Character cards: one fixed look per character, reused across every scene that shows them.

A card is a JSON record under `data/characters.json`:

    {"id": "ch-abc123", "name": "角色代號", "adult_attested": true,
     "description": "fixed appearance description (English, goes into every prompt)",
     "seed_base": 12345, "ref_image": "", "model_release": "", "lora": ""}

Two rules are enforced here and nowhere else, because they are legal boundaries, not style:

* `adult_attested` must be present and true for any character used by a non-general episode.
  A missing field means "not attested", never "assumed fine".
* `ref_image` (a photo of a real person) requires a `model_release`: the written consent that
  the person agreed to this use. No release, no photo.

The card also carries the two things that make a character look like the same person twice:
`description` (pasted verbatim into every prompt that shows them) and `seed_base` (a stable
seed offset, so the same character does not drift between scenes).
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from . import store

_lock = threading.RLock()
FILE = "characters.json"

FIELDS = ("id", "name", "adult_attested", "description", "negative", "ref_image",
          "model_release", "lora", "lora_strength", "seed_base")


def path() -> Path:
    return store.DATA / FILE


def _read() -> dict:
    if not path().exists():
        return {"items": []}
    try:
        raw = json.loads(path().read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": []}
    items = raw.get("items") if isinstance(raw, dict) else None
    return {"items": [c for c in (items or []) if isinstance(c, dict)]}


def _write(data: dict) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    tmp = path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path())


def normalize(raw: dict) -> dict:
    """One card with every field present and typed. `adult_attested` is never defaulted to true."""
    card = dict(raw or {})
    out: dict[str, Any] = {
        "id": str(card.get("id") or f"ch-{uuid.uuid4().hex[:8]}").strip(),
        "name": str(card.get("name") or "未命名角色").strip(),
        "adult_attested": card.get("adult_attested") is True,
        "description": str(card.get("description") or "").strip(),
        "negative": str(card.get("negative") or "").strip(),
        "ref_image": str(card.get("ref_image") or "").strip(),
        "model_release": str(card.get("model_release") or "").strip(),
        "lora": str(card.get("lora") or "").strip(),
        "lora_strength": float(card.get("lora_strength") or 0.8),
        "seed_base": int(card.get("seed_base") or 0),
    }
    return out


def list_all() -> list[dict]:
    with _lock:
        return [normalize(c) for c in _read()["items"]]


def get(cid: str) -> dict | None:
    cid = str(cid or "").strip()
    if not cid:
        return None
    for c in list_all():
        if c["id"] == cid:
            return c
    return None


def save(raw: dict) -> dict:
    """Create or update a card. `id` decides which one."""
    card = normalize(raw)
    with _lock:
        data = _read()
        items = data["items"]
        for i, c in enumerate(items):
            if c.get("id") == card["id"]:
                items[i] = card
                break
        else:
            items.insert(0, card)
        _write(data)
    return card


def delete(cid: str) -> bool:
    with _lock:
        data = _read()
        items = data["items"]
        kept = [c for c in items if c.get("id") != cid]
        if len(kept) == len(items):
            return False
        data["items"] = kept
        _write(data)
        return True


# ---------- the two hard rules ----------

def card_problem(card: dict, rating: str) -> str:
    """Why this card may not be used at this rating; empty string when it may.

    Only non-general episodes are restricted: a general episode may show anyone, so a card
    without an adult attestation is simply not used for anything explicit there.
    """
    rating = (rating or "general").strip().lower()
    if rating == "general":
        return ""
    if card.get("adult_attested") is not True:
        return (f"角色「{card.get('name') or card.get('id')}」沒有成年宣告"
                f"（adult_attested 必須明確為 true），{rating} 分級不能用這個角色。")
    if (card.get("ref_image") or "").strip() and not (card.get("model_release") or "").strip():
        return (f"角色「{card.get('name') or card.get('id')}」用了真人照片但沒有附同意文件"
                f"（model_release），{rating} 分級不能用這個角色。")
    return ""


def usable_cards(ids: list[str], rating: str) -> tuple[list[dict], list[str]]:
    """The cards an episode may use, plus the reasons the others were rejected."""
    ok, bad = [], []
    for cid in ids or []:
        card = get(cid)
        if card is None:
            bad.append(f"找不到角色卡 {cid}")
            continue
        why = card_problem(card, rating)
        if why:
            bad.append(why)
            continue
        ok.append(card)
    return ok, bad


# ---------- prompt injection ----------

def prompt_fragment(card: dict) -> str:
    """The fixed appearance text for one character, or "" when the card has none."""
    return (card.get("description") or "").strip()


def prompt_fragments(cards: list[dict]) -> str:
    """Every character's fixed description, in one block that goes in front of a scene prompt."""
    parts = [prompt_fragment(c) for c in cards or []]
    parts = [p for p in parts if p]
    return "; ".join(parts)


def scene_cards(scene: dict, cards: list[dict]) -> list[dict]:
    """Which of the episode's characters this scene shows.

    A scene names them in `characters` (by name or id). A scene that names nobody shows nobody:
    an explicit empty list means "no characters here", not "all of them".
    """
    named = scene.get("characters")
    if named is None:
        return []
    if not isinstance(named, list):
        named = [named]
    wanted = {str(x).strip() for x in named if str(x).strip()}
    if not wanted:
        return []
    out = []
    for c in cards or []:
        if str(c.get("name") or "").strip() in wanted or str(c.get("id") or "").strip() in wanted:
            out.append(c)
    return out


def seed_offset(card: dict) -> int:
    """This character's stable seed offset. Same card -> same offset, in every scene."""
    try:
        base = int(card.get("seed_base") or 0)
    except (TypeError, ValueError):
        base = 0
    if base:
        return base % 100000
    # no explicit base: derive one from the id so the character is still stable across scenes
    return (hash_id(str(card.get("id") or "")) % 100000)


def hash_id(text: str) -> int:
    """A stable integer for a string (Python's hash() changes between runs)."""
    h = 0
    for ch in text.encode("utf-8"):
        h = (h * 131 + ch) % 2147483647
    return h


def scene_seed(base_seed: int, ep_seed: int, index: int, cards: list[dict]) -> int:
    """The seed for one scene: the episode seed plus a stable offset per character in it."""
    off = sum(seed_offset(c) for c in cards or [])
    return int(base_seed) + int(ep_seed) + int(index) + off
