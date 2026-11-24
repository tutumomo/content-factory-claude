"""Ratings, modes, characters and the provider routing: the rules that guard a restricted episode.

Everything here drives the shipped code (store.new_episode, sources.chain, llm.complete_json,
prompts.critic_roles, characters.*, comfy._graph, pipeline.approve) rather than a copy of it.

Run:  .venv/bin/python -m pytest tests/test_ratings.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import characters, comfy, llm, prompts, sources, store, youtube

from .conftest import set_settings, wait_for


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Point the store at an empty folder so these tests never touch the shared smoke-test data."""
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "EPISODES", tmp_path / "episodes")
    return tmp_path


@pytest.fixture
def ceiling(client):
    """Raise the channel's rating ceiling for one test, then put it back where it was."""
    ch = client.get("/api/channel").json()
    old = ch.get("max_rating") or "general"
    client.put("/api/channel", json={**ch, "max_rating": "adult"})
    yield "adult"
    ch2 = client.get("/api/channel").json()
    client.put("/api/channel", json={**ch2, "max_rating": old})


@pytest.fixture
def offline(client):
    """Run the episode on the offline mock LLM (the real one would call Claude CLI)."""
    set_settings(client, llm={"provider": "mock"})
    return client


def _raise_ceiling(data, level: str = "adult") -> None:
    """Let the channel make restricted episodes (the default ceiling is general)."""
    store.save_channel({**store.get_channel(), "max_rating": level})


def _use_stock_visuals(data) -> None:
    """Put the free stock footage in the visuals chain, so the rating filter has something to drop."""
    s = store.get_settings()
    store.save_settings({**s, "visuals": {**s["visuals"], "source": "mix"}})


def _restricted_episode(client, topic: str, rating: str = "adult") -> str:
    r = client.post("/api/episodes", json={"topic": topic, "format": "short",
                                            "mode": "narrative", "rating": rating})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _run_to_approval(client, eid: str, rating: str = "adult") -> None:
    """Drive an episode up to the approval gate (the last gate before the publish package)."""
    wait_for(client, eid)
    ep = client.get(f"/api/episodes/{eid}").json()
    if ep.get("waiting_for") == "sources":
        assert client.post(f"/api/episodes/{eid}/sources", json={"proceed": True}).status_code == 200
        wait_for(client, eid)
    for _ in range(10):
        ep = client.get(f"/api/episodes/{eid}").json()
        w = ep.get("waiting_for")
        if w == "direction":
            d = ep["files"]["brief"]["directions"][0]["id"]
            assert client.post(f"/api/episodes/{eid}/direction", json={"id": d}).status_code == 200
        elif w == "script":
            assert client.post(f"/api/episodes/{eid}/script", json={"approve": True}).status_code == 200
        elif w == "storyboard":
            assert client.post(f"/api/episodes/{eid}/storyboard", json={"approve": True}).status_code == 200
        elif w == "cost":
            assert client.post(f"/api/episodes/{eid}/cost").status_code == 200
        elif w == "package":
            assert client.post(f"/api/episodes/{eid}/package", json={"title": 0, "thumb": 0}).status_code == 200
        else:
            break
        wait_for(client, eid)
    ep = client.get(f"/api/episodes/{eid}").json()
    assert ep["waiting_for"] == "approval", ep


def _run_to_done(client, eid: str, rating: str | None = None) -> dict:
    """Run an episode to done; a restricted episode gets its rating confirmation at the gate."""
    _run_to_approval(client, eid, rating or "general")
    body = {"confirm_rating": rating} if rating else {}
    r = client.post(f"/api/episodes/{eid}/approve", json=body)
    assert r.status_code == 200, r.text
    return wait_for(client, eid)


# ---------- criterion 1: mode and rating are first-class data ----------

def test_new_episode_defaults_to_news_general(data):
    ep = store.new_episode("測試題目", "short")
    assert ep["mode"] == "news"
    assert ep["rating"] == "general"
    assert ep["characters"] == []


def test_news_plus_adult_is_refused_with_a_readable_reason(data):
    with pytest.raises(ValueError) as e:
        store.new_episode("測試題目", "short", mode="news", rating="adult")
    msg = str(e.value)
    assert "narrative" in msg and "成人向" in msg, msg


def test_api_refuses_news_plus_adult_and_returns_the_reason(client):
    r = client.post("/api/episodes", json={"topic": "測試", "format": "short",
                                            "mode": "news", "rating": "adult"})
    assert r.status_code == 400
    assert "narrative" in r.json()["detail"]


def test_api_writes_mode_and_rating_and_reads_them_back(client, ceiling):
    r = client.post("/api/episodes", json={"topic": "測試敘事", "format": "short",
                                            "mode": "narrative", "rating": "suggestive"})
    assert r.status_code == 200, r.text
    ep = r.json()
    assert ep["mode"] == "narrative"
    assert ep["rating"] == "suggestive"
    got = client.get(f"/api/episodes/{ep['id']}").json()
    assert got["mode"] == "narrative"
    assert got["rating"] == "suggestive"


def test_rating_above_the_channel_ceiling_is_refused(data):
    assert store.get_channel()["max_rating"] == "general"
    with pytest.raises(ValueError) as e:
        store.new_episode("測試題目", "short", mode="narrative", rating="suggestive")
    assert "上限" in str(e.value)


def test_raising_the_ceiling_allows_a_restricted_episode(data):
    _raise_ceiling(data, "suggestive")
    ep = store.new_episode("測試題目", "short", mode="narrative", rating="suggestive")
    assert ep["rating"] == "suggestive"


def test_meta_exposes_modes_ratings_and_each_mode_critic_set(client):
    meta = client.get("/api/meta").json()
    assert meta["modes"] == ["news", "narrative"]
    assert meta["ratings"] == ["general", "suggestive", "adult"]
    assert set(meta["critics_by_mode"]) == {"news", "narrative"}
    assert meta["critics_by_mode"]["news"] != meta["critics_by_mode"]["narrative"]


# ---------- criterion 2: rating gates the sources and the platforms ----------

def test_general_chain_is_unchanged_by_the_rating_filter(data):
    _use_stock_visuals(data)
    assert sources.chain("visuals", "general") == sources.chain("visuals")


def test_restricted_ratings_drop_the_free_stock_source(data):
    _use_stock_visuals(data)
    assert "stock" in sources.chain("visuals", "general")
    for rating in ("suggestive", "adult"):
        chain = sources.chain("visuals", rating)
        assert "stock" not in chain, (rating, chain)
        assert "comfy" in chain and "slides" in chain


def test_the_plan_records_the_excluded_source(data):
    _use_stock_visuals(data)
    plan, _ = sources.start(["visuals"], rating="adult")
    assert "stock" not in plan.chains["visuals"]
    assert "stock" in plan.excluded["visuals"]
    assert "實拍素材" in plan.line("visuals")


def test_restricted_episode_blocks_youtube_upload_at_the_entry(client, ceiling):
    eid = _restricted_episode(client, "受限測試")
    ep = store.get_episode(eid)
    ep["status"] = "done"
    store.save_episode(ep)
    up = client.post(f"/api/episodes/{eid}/youtube")
    assert up.status_code == 409
    assert "18+" in up.json()["detail"]


def test_the_upload_worker_refuses_a_restricted_episode(data):
    ep = {"id": "x", "rating": "adult"}
    assert "18+" in youtube.upload_blocked_reason(ep)
    assert youtube.upload_blocked_reason({"id": "x", "rating": "general"}) == ""


def test_verify_has_a_rating_check(offline, ceiling, fakes):
    client = offline
    set_settings(client, visuals={"source": "mix"})
    eid = _restricted_episode(client, "分級檢查測試")
    ep = _run_to_done(client, eid, rating="adult")
    verify = ep["files"]["verify"]
    assert "分級" in verify["checks"]
    assert verify["checks"]["分級"]["ok"] is True
    assert "成人" in verify["checks"]["分級"]["value"]
    # the restricted episode never used the free stock library
    assert "stock" not in json.dumps(verify["sources"]["plan"], ensure_ascii=False)
    assert "實拍素材" in json.dumps(verify["sources"]["plan"], ensure_ascii=False)


# ---------- criterion 3: the writing layer survives a refusing provider ----------

def test_refusal_is_reported_as_a_refusal_not_a_json_error(monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda task, system, prompt: "抱歉，我無法協助這個請求。")
    with pytest.raises(llm.LLMRefusal) as e:
        llm.complete_json("script", "sys", "prompt")
    msg = str(e.value)
    assert "拒絕" in msg
    assert "不是合法 JSON" not in msg


def test_refusal_is_detected_by_the_shared_marker_function():
    assert llm.looks_like_refusal("抱歉，我無法協助這個請求。")
    assert llm.looks_like_refusal("I can't help with that.")
    assert not llm.looks_like_refusal('{"score": 8, "summary": "ok"}')


def test_a_task_can_be_routed_to_another_provider(monkeypatch):
    seen = {}

    def fake_cli(system, prompt, cfg, tools="", timeout=None):
        seen["cli"] = True
        return "cli"

    def fake_openai(system, prompt, cfg):
        seen["openai"] = True
        return "openai"

    monkeypatch.setattr(llm, "_claude_cli", fake_cli)
    monkeypatch.setattr(llm, "_openai", fake_openai)
    monkeypatch.setattr(store, "get_settings", lambda: {"llm": {
        "provider": "claude_cli", "task_routes": {"script": "openai"},
        "openai_base_url": "http://127.0.0.1:1/v1", "openai_model": "x",
        "openai_key_env": "", "timeout_s": 5}})
    assert llm.complete("script", "s", "p") == "openai"
    assert seen.get("openai") and not seen.get("cli")
    # an unrouted task still uses the default provider
    seen.clear()
    assert llm.complete("brief", "s", "p") == "cli"


def test_provider_for_falls_back_to_the_default_provider():
    cfg = {"provider": "claude_cli", "task_routes": {"script": "openai", "bad": "nope"}}
    assert llm.provider_for("script", cfg) == "openai"
    assert llm.provider_for("brief", cfg) == "claude_cli"
    assert llm.provider_for("bad", cfg) == "claude_cli"


def test_narrative_mode_uses_its_own_rules_and_review_roles():
    news_block = prompts.mode_block("news", "general")
    narr_block = prompts.mode_block("narrative", "adult")
    assert news_block == prompts.ANTI_HALLUCINATION
    assert narr_block == prompts.NARRATIVE_RULES
    assert "自洽" in narr_block
    assert set(prompts.critic_roles("narrative")) == {"boundary", "coherence", "tension", "ai_voice"}
    assert set(prompts.critic_roles("news")) == {"fact", "audience", "pacing", "ai_voice"}


def test_narrative_script_prompt_carries_the_rating_note(data):
    ep = {"id": "e", "topic": "故事", "format": "short", "style_id": None,
          "mode": "narrative", "rating": "adult", "characters": []}
    sys, _ = prompts.script(ep, {"id": "A"}, "")
    assert prompts.NARRATIVE_RULES in sys
    assert prompts.ANTI_HALLUCINATION not in sys
    assert "成人" in sys


def test_news_script_prompt_is_unchanged_by_the_rating_work(data):
    ep = {"id": "e", "topic": "新聞", "format": "short", "style_id": None,
          "mode": "news", "rating": "general", "characters": []}
    sys, _ = prompts.script(ep, {"id": "A"}, "")
    assert prompts.ANTI_HALLUCINATION in sys
    assert prompts.NARRATIVE_RULES not in sys


# ---------- criterion 4: characters and image controls ----------

def test_a_character_without_an_adult_attestation_is_rejected(data):
    card = characters.save({"name": "無宣告", "description": "tall"})
    assert card["adult_attested"] is False
    assert characters.card_problem(card, "general") == ""
    assert "成年宣告" in characters.card_problem(card, "adult")
    ok, bad = characters.usable_cards([card["id"]], "adult")
    assert ok == [] and len(bad) == 1


def test_a_real_person_photo_without_a_release_is_rejected(data):
    card = characters.save({"name": "真人", "adult_attested": True,
                             "ref_image": "/tmp/face.png", "model_release": ""})
    assert "同意文件" in characters.card_problem(card, "adult")
    released = characters.save({"name": "真人", "adult_attested": True,
                                 "ref_image": "/tmp/face.png", "model_release": "consent.pdf"})
    assert characters.card_problem(released, "adult") == ""


def test_a_card_with_an_attestation_is_usable_at_a_restricted_rating(data):
    card = characters.save({"name": "角色A", "adult_attested": True, "description": "same person"})
    ok, bad = characters.usable_cards([card["id"]], "adult")
    assert [c["id"] for c in ok] == [card["id"]] and bad == []


def test_the_same_character_gets_the_same_description_and_seed_in_every_scene(data):
    card = characters.save({"name": "角色A", "adult_attested": True,
                             "description": "a woman with short black hair", "seed_base": 4242})
    scene_a = {"characters": ["角色A"]}
    scene_b = {"characters": ["角色A"]}
    cards_a = characters.scene_cards(scene_a, [card])
    cards_b = characters.scene_cards(scene_b, [card])
    assert characters.prompt_fragments(cards_a) == characters.prompt_fragments(cards_b)
    assert "short black hair" in characters.prompt_fragments(cards_a)
    # the character's own offset is stable; only the scene index moves the seed
    off = characters.seed_offset(card)
    assert off == 4242
    assert characters.scene_seed(1000, 7, 0, cards_a) - characters.scene_seed(1000, 7, 1, cards_a) == -1
    assert characters.scene_seed(1000, 7, 0, cards_a) == 1000 + 7 + 0 + off


def test_a_scene_that_names_nobody_shows_nobody(data):
    card = characters.save({"name": "角色A", "adult_attested": True, "description": "x"})
    assert characters.scene_cards({"characters": []}, [card]) == []
    assert characters.scene_cards({}, [card]) == []
    assert characters.scene_cards({"characters": ["角色A"]}, [card]) == [card]


def test_the_negative_prompt_becomes_a_real_negative_condition(data):
    def set_negative(v):
        s = store.get_settings()
        store.save_settings({**s, "visuals": {**s["visuals"], "negative": v}})

    set_negative("")
    without = comfy._graph("a prompt", 512, 512, 1)
    assert without["5"]["class_type"] == "ConditioningZeroOut"
    set_negative("blurry, extra fingers")
    with_neg = comfy._graph("a prompt", 512, 512, 1)
    assert with_neg["5"]["class_type"] == "CLIPTextEncode"
    assert with_neg["5"]["inputs"]["text"] == "blurry, extra fingers"
    assert with_neg["7"]["inputs"]["negative"] == ["5", 0]
    # the only difference between the two graphs is the negative conditioning
    diff = {k for k in set(without) | set(with_neg) if without.get(k) != with_neg.get(k)}
    assert diff == {"5"}


def test_per_call_settings_override_the_global_ones(data):
    s = store.get_settings()
    store.save_settings({**s, "visuals": {**s["visuals"], "unet": "global.safetensors"}})
    assert comfy.cfg()["unet"] == "global.safetensors"
    with comfy.using({"unet": "per_call.safetensors"}):
        assert comfy.cfg()["unet"] == "per_call.safetensors"
        graph = comfy._graph("p", 512, 512, 1)
        assert graph["1"]["inputs"]["unet_name"] == "per_call.safetensors"
    assert comfy.cfg()["unet"] == "global.safetensors"


# ---------- criterion 5: the restricted publish package and the audit trail ----------

def test_a_restricted_publish_package_has_no_carousel_fb_post_or_shorts_captions(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode(client, "受限發布包測試")
    ep = _run_to_done(client, eid, rating="adult")
    pub = Path(ep["published_dir"])
    assert (pub / "video.mp4").is_file()
    assert (pub / "subtitles.srt").is_file()
    assert (pub / "thumbnail.jpg").is_file()
    assert (pub / "metadata.json").is_file()
    assert (pub / "CHECKLIST.md").is_file()
    assert not (pub / "shorts").exists()
    assert not (pub / "shorts" / "caption_tiktok.txt").exists()
    assert not (pub / "shorts" / "caption_instagram.txt").exists()
    assert not list(pub.glob("card_*.jpg"))
    meta = json.loads((pub / "metadata.json").read_text("utf-8"))
    assert meta["contentRating"] == "adult"
    assert meta["ai_generated"] is True
    assert meta["ai_disclosure"]
    assert "fb_post" not in meta
    checklist = (pub / "CHECKLIST.md").read_text("utf-8")
    assert "不支援自動上傳" in checklist


def test_a_general_publish_package_is_unchanged(offline, fakes):
    client = offline
    r = client.post("/api/episodes", json={"topic": "一般發布包測試", "format": "short"})
    eid = r.json()["id"]
    ep = _run_to_done(client, eid)
    assert ep["status"] == "done"
    pub = Path(ep["published_dir"])
    assert (pub / "shorts" / "caption_tiktok.txt").is_file()
    assert (pub / "shorts" / "caption_instagram.txt").is_file()
    meta = json.loads((pub / "metadata.json").read_text("utf-8"))
    assert "contentRating" not in meta
    assert not (pub / "CHECKLIST.md").exists()


def test_approving_a_restricted_episode_needs_a_matching_rating_confirmation(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode(client, "分級確認測試")
    _run_to_approval(client, eid)
    bad = client.post(f"/api/episodes/{eid}/approve", json={"confirm_rating": "general"})
    assert bad.status_code == 400
    assert "分級確認" in bad.json()["detail"]
    good = client.post(f"/api/episodes/{eid}/approve", json={"confirm_rating": "adult"})
    assert good.status_code == 200, good.text
    ep = store.get_episode(eid)
    approvals = ep.get("approvals") or []
    assert any(a.get("rating") == "adult" and a.get("confirm_rating") == "adult" for a in approvals)


def test_a_general_episode_needs_no_rating_confirmation(offline, fakes):
    client = offline
    r = client.post("/api/episodes", json={"topic": "一般核准測試", "format": "short"})
    eid = r.json()["id"]
    ep = _run_to_done(client, eid)
    assert ep["status"] == "done"


def test_the_manifest_records_models_characters_seeds_and_prompt_hashes(offline, ceiling, fakes, monkeypatch):
    client = offline
    # the shared fake's health probe takes no timeout, so ComfyUI reads as unavailable; make it usable here
    monkeypatch.setattr(comfy, "health", lambda timeout=4: {"ok": True, "detail": "ComfyUI 就緒（fake）"})
    sources._cache.clear()      # probe results are cached for 30 s; drop what an earlier test cached
    set_settings(client, visuals={"source": "comfy"})
    card = characters.save({"name": "角色A", "adult_attested": True,
                             "description": "same person", "seed_base": 777})
    r = client.post("/api/episodes", json={"topic": "稽核軌跡測試", "format": "short",
                                            "mode": "narrative", "rating": "adult",
                                            "characters": [card["id"]]})
    eid = r.json()["id"]
    ep = _run_to_done(client, eid, rating="adult")
    manifest = store.read_json(eid, "assets/manifest.json")
    assert manifest["rating"] == "adult"
    assert manifest["characters"] and manifest["characters"][0]["id"] == card["id"]
    assert manifest["characters"][0]["seed_base"] == 777
    assert manifest["models"], "manifest must record which models made the pictures"
    assert manifest["scenes"]
    for s in manifest["scenes"]:
        assert "seed" in s and "prompt_sha256" in s
