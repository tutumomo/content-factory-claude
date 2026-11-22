"""Built-in style cards: list integrity, the original five untouched, and fallbacks for old data."""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from app import prompts, store
from app.style_presets import EXTRA_PRESETS, NEW_CATEGORIES

ORIGINAL_IDS = ["preset-tech-decode", "preset-news-flash", "preset-easy-guide", "preset-deep-take", "preset-tool-review"]
ORIGINAL_CATEGORIES = ["科技數碼", "新聞快評", "知識科普", "觀點深度", "生活工具"]
# sha256 of json.dumps(the five original cards as shipped on main, ensure_ascii=False, sort_keys=True)
ORIGINAL_SHA256 = "1c078f693bfbb116f70cbe3bb0af5dcad6e7c84edf0a36562177b3ee8cbe550e"
REQUIRED_TEXT = ["id", "name", "icon", "category", "summary", "tone", "opening", "structure", "pacing", "source"]


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Point the store at an empty folder so these tests never touch the shared smoke-test data."""
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "EPISODES", tmp_path / "episodes")
    return tmp_path


def test_original_five_unchanged():
    assert [p["id"] for p in store.PRESET_STYLES[:5]] == ORIGINAL_IDS
    blob = json.dumps(store.PRESET_STYLES[:5], ensure_ascii=False, sort_keys=True).encode()
    assert hashlib.sha256(blob).hexdigest() == ORIGINAL_SHA256
    assert store.STYLE_CATEGORIES[:5] == ORIGINAL_CATEGORIES


def test_preset_list_integrity():
    presets = store.PRESET_STYLES
    ids = [p["id"] for p in presets]
    assert len(ids) == len(set(ids)), "風格卡 id 重複"
    assert 30 <= len(presets) <= 40
    assert presets[5:] == EXTRA_PRESETS
    assert "my-channel-style" not in ids
    for p in presets:
        for k in REQUIRED_TEXT:
            assert str(p.get(k) or "").strip(), f"{p['id']} 缺 {k}"
        assert p["preset"] is True
        assert p["category"] in store.STYLE_CATEGORIES, p["id"]
        assert p["words"] and p["avoid"], p["id"]
    for p in EXTRA_PRESETS:
        assert re.fullmatch(r"preset(-[a-z0-9]+)+", p["id"]), p["id"]
        # every new card says which scene template(s) fit, using the real template names
        assert p["visual"].strip() and any(k in p["visual"] for k in prompts.STYLES), p["id"]
    assert len({p["name"] for p in presets}) == len(presets), "風格卡名稱重複"


def test_every_category_has_three_to_six_cards():
    assert len(store.STYLE_CATEGORIES) == len(set(store.STYLE_CATEGORIES))
    assert store.STYLE_CATEGORIES[5:] == NEW_CATEGORIES
    for cat in store.STYLE_CATEGORIES:
        n = sum(p["category"] == cat for p in store.PRESET_STYLES)
        assert 3 <= n <= 6, (cat, n)


def test_fresh_data_gets_all_presets(data):
    styles = store.get_styles()
    assert [x["id"] for x in styles["items"]] == [p["id"] for p in store.PRESET_STYLES]
    assert styles["active_id"] == "preset-tech-decode"


def test_old_styles_json_keeps_edits_and_gains_new_cards(data):
    """A styles.json written before this change: original cards only, no `visual`, a custom card active."""
    old = [{k: v for k, v in p.items()} for p in store.PRESET_STYLES[:5]]
    old[0]["summary"] = "使用者自己改過的簡介"
    custom = {"id": "my-channel-style", "name": "我的頻道風格", "icon": "🎙️", "category": "科技數碼",
              "summary": "x", "tone": "y", "preset": False, "source": "由頻道定位建立"}
    (data / "styles.json").write_text(json.dumps({"active_id": "my-channel-style", "items": [custom, *old]},
                                                 ensure_ascii=False), "utf-8")
    styles = store.get_styles()
    ids = [x["id"] for x in styles["items"]]
    assert ids[:6] == ["my-channel-style", *ORIGINAL_IDS]
    assert ids[6:] == [p["id"] for p in EXTRA_PRESETS]
    assert styles["active_id"] == "my-channel-style"
    by_id = {x["id"]: x for x in styles["items"]}
    assert by_id["preset-tech-decode"]["summary"] == "使用者自己改過的簡介"
    assert by_id["preset-tech-decode"]["visual"] == ""
    # the merged list was written back, so a second read is stable
    assert store.get_styles() == styles


def test_unknown_active_id_falls_back(data):
    (data / "styles.json").write_text(json.dumps({"active_id": "preset-gone", "items": []}), "utf-8")
    styles = store.get_styles()
    assert styles["active_id"] == store.PRESET_STYLES[0]["id"]


def test_unknown_style_id_in_episode_falls_back(data):
    assert store.get_style("preset-does-not-exist") is None
    block = store.style_block("preset-does-not-exist")
    assert store.PRESET_STYLES[0]["name"] in block
    ep = store.new_episode("測試題目", "short", style_id="preset-does-not-exist")
    assert ep["style_id"] == store.get_styles()["active_id"]
    ep2 = store.new_episode("測試題目二", "short", style_id="preset-cine-trailer")
    assert ep2["style_id"] == "preset-cine-trailer"


def test_style_block_includes_visual_only_when_set(data):
    assert "畫面方向" not in store.style_block("preset-tech-decode")
    block = store.style_block("preset-retro-vhs")
    assert "畫面方向" in block and "bigtype" in block


def test_api_lists_and_activates_new_card(client):
    meta = client.get("/api/meta").json()
    assert meta["style_categories"][:5] == ORIGINAL_CATEGORIES
    items = client.get("/api/styles").json()["items"]
    ids = {x["id"] for x in items}
    assert set(ORIGINAL_IDS) <= ids and "preset-anim-paper-cutout" in ids
    before = client.get("/api/styles").json()["active_id"]
    try:
        r = client.post("/api/styles/preset-anim-paper-cutout/activate")
        assert r.status_code == 200 and r.json()["active_id"] == "preset-anim-paper-cutout"
        assert client.get("/api/styles").json()["active_id"] == "preset-anim-paper-cutout"
        assert client.post("/api/styles/preset-nope/activate").status_code == 404
        assert client.delete("/api/styles/preset-anim-paper-cutout").status_code == 400
    finally:
        client.post(f"/api/styles/{before}/activate")


def test_custom_card_keeps_visual(client):
    r = client.post("/api/styles", json={"name": "測試畫面卡", "visual": "模板 clean，冷白光", "category": "動畫手繪"})
    assert r.status_code == 200
    card = r.json()
    try:
        assert card["visual"] == "模板 clean，冷白光" and card["category"] == "動畫手繪"
        upd = client.put(f"/api/styles/{card['id']}", json={"visual": "改成暖光"}).json()
        assert upd["visual"] == "改成暖光"
    finally:
        client.delete(f"/api/styles/{card['id']}")
