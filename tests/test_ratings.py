"""Ratings, modes, characters and the provider routing: the rules that guard a restricted episode.

Everything here drives the shipped code (store.new_episode, sources.chain, llm.complete_json,
prompts.critic_roles, characters.*, comfy._graph, pipeline.approve) rather than a copy of it.

Run:  .venv/bin/python -m pytest tests/test_ratings.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app import characters, comfy, llm, pipeline, prompts, sources, store, suggest, youtube

from app.style_presets_nsfw import NSFW_CATEGORIES, NSFW_PRESETS

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


def _restricted_episode_form(client, topic: str, form: str, rating: str = "adult") -> str:
    r = client.post("/api/episodes", json={"topic": topic, "format": "short", "mode": "fiction",
                                            "rating": rating, "form": form})
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
    assert ep["waiting_for"] == "approval", (ep.get("stage"), ep.get("error"), (ep.get("log") or [])[-3:])


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
    assert meta["modes"] == list(store.MODES)
    assert meta["ratings"] == ["general", "suggestive", "adult"]
    assert set(meta["critics_by_mode"]) == set(store.MODES)
    assert meta["critics_by_mode"]["news"] != meta["critics_by_mode"]["narrative"]


def test_timeout_is_generous_by_default_and_overridable_per_task(monkeypatch):
    cfg = {"timeout_s": 1800}
    assert llm.timeout_for("script", cfg) == 1800
    cfg2 = {"timeout_s": 900, "task_timeout_s": {"brief": 3600}}
    assert llm.timeout_for("brief", cfg2) == 3600
    assert llm.timeout_for("script", cfg2) == 900
    # a bad value must not crash the call path
    assert llm.timeout_for("script", {"timeout_s": "slow"}) == 1800


def test_a_timed_out_local_model_says_how_long_it_waited(monkeypatch):
    def boom(*a, **kw):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(llm.httpx, "post", boom)
    cfg = {"openai_base_url": "http://127.0.0.1:1/v1", "openai_model": "m", "timeout_s": 2400,
           "openai_key_env": ""}
    with pytest.raises(llm.LLMError) as e:
        llm._openai("sys", "prompt", cfg, timeout=2400)
    msg = str(e.value)
    assert "2400" in msg, msg
    assert "逾時" in msg
    assert "timed out" not in msg      # the bare httpx wording is what confused the owner


def test_the_default_llm_timeout_is_thirty_minutes():
    assert store.DEFAULT_SETTINGS["llm"]["timeout_s"] == 1800


def test_health_reports_comfyui_and_whether_the_chain_needs_it(client, monkeypatch):
    monkeypatch.setattr(comfy, "status", lambda **kw: {"ok": False, "detail": "ComfyUI 連不上"})
    monkeypatch.setattr(sources, "chain", lambda kind, rating="general": ["slides"] if kind == "visuals" else [])
    h = client.get("/api/health").json()
    assert h["comfy"]["ok"] is False
    assert h["comfy"]["needed"] is False          # slides only: a red dot would be misleading
    monkeypatch.setattr(sources, "chain", lambda kind, rating="general": ["comfy", "slides"] if kind == "visuals" else [])
    h2 = client.get("/api/health").json()
    assert h2["comfy"]["needed"] is True
    assert h2["comfy"]["chain"] == ["comfy", "slides"]


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

    def fake_openai(system, prompt, cfg, timeout=None):
        seen["openai"] = (timeout,)
        return "openai"

    monkeypatch.setattr(llm, "_claude_cli", fake_cli)
    monkeypatch.setattr(llm, "_openai", fake_openai)
    monkeypatch.setattr(store, "get_settings", lambda: {"llm": {
        "provider": "claude_cli", "task_routes": {"script": "openai"},
        "openai_base_url": "http://127.0.0.1:1/v1", "openai_model": "x",
        "openai_key_env": "", "timeout_s": 5}})
    assert llm.complete("script", "s", "p") == "openai"
    assert seen.get("openai") and not seen.get("cli")
    assert seen["openai"][0] == 5      # the configured timeout reaches the provider
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


def test_creating_a_restricted_episode_with_an_unattested_character_is_refused(data):
    _raise_ceiling(data)
    card = characters.save({"name": "無宣告", "description": "x"})
    with pytest.raises(ValueError) as e:
        store.new_episode("測試題目", "short", mode="narrative", rating="adult",
                          characters=[card["id"]])
    assert "成年宣告" in str(e.value)
    # a general episode may still use the same card
    ep = store.new_episode("測試題目", "short", characters=[card["id"]])
    assert ep["characters"] == [card["id"]]


def test_a_restricted_episode_with_a_real_person_photo_is_refused(data):
    _raise_ceiling(data)
    card = characters.save({"name": "真人", "adult_attested": True,
                             "ref_image": "/tmp/face.png", "model_release": ""})
    with pytest.raises(ValueError) as e:
        store.new_episode("測試題目", "short", mode="narrative", rating="adult",
                          characters=[card["id"]])
    assert "同意文件" in str(e.value)


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


# ---------- creative modes: no verification, free invention ----------

def test_fiction_is_an_allowed_mode_with_its_own_rules(data):
    assert "fiction" in store.MODES
    assert set(prompts.critic_roles("fiction")) != set(prompts.critic_roles("news"))
    assert prompts.mode_block("fiction") == prompts.FICTION_RULES
    assert "不需要依據" in prompts.FICTION_RULES


def test_creative_modes_skip_the_source_gate(data, monkeypatch):
    """A fiction episode with no links must not stop to ask for sources."""
    _raise_ceiling(data)
    ep = store.new_episode("憑空編的故事", "short", mode="fiction", rating="adult", form="novel")
    monkeypatch.setattr(pipeline, "wait", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gated")))
    monkeypatch.setattr(pipeline, "fetch_text", lambda url, limit=6000: "（不抓）")
    assert pipeline.st_sources(store.get_episode(ep["id"])) is True
    verdict = store.get_episode(ep["id"])["checks"]["sources"]
    assert verdict["ok"] is True and verdict.get("creative") is True
    assert "不查證" in verdict["value"]


def test_news_still_gates_without_sources(data, monkeypatch):
    """The default news path keeps its old behaviour: no material means a gate."""
    ep = store.new_episode("沒有來源的新聞", "short")
    calls = {}

    def fake_wait(eid, what):
        calls["gated"] = what

    monkeypatch.setattr(pipeline, "wait", fake_wait)
    monkeypatch.setattr(pipeline, "fetch_text", lambda url, limit=6000: "（不抓）")
    assert pipeline.st_sources(store.get_episode(ep["id"])) is False
    assert calls.get("gated") == "sources"


def test_the_rating_note_reaches_the_fiction_script_prompt(data):
    _raise_ceiling(data)
    ep = store.new_episode("故事", "short", mode="fiction", rating="adult", form="novel")
    sys, _ = prompts.script(ep, {"id": "A"}, "")
    assert prompts.FICTION_RULES in sys
    assert "成人" in sys
    assert "未成年" in sys       # the hard line survives even in free-invention mode


# ---------- content forms ----------

def test_the_five_forms_round_trip_through_the_store(data):
    for form in store.FORMS:
        ep = store.new_episode(f"測試 {form}", "short", form=form)
        assert ep["form"] == form
        assert store.get_episode(ep["id"])["form"] == form


def test_an_unknown_form_falls_back_to_video(data):
    ep = store.new_episode("測試", "short", form="podcast")
    assert ep["form"] == "video"
    assert store.form_of({}) == "video"          # old episodes predate the field


def test_each_form_declares_what_it_needs():
    assert store.FORM_NEEDS["novel"] == {"voice": False, "visual": False}
    assert store.FORM_NEEDS["video"] == {"voice": True, "visual": True}
    assert store.FORM_NEEDS["audiobook"] == {"voice": True, "visual": False}
    assert store.FORM_NEEDS["gallery"] == {"voice": False, "visual": True}


def test_text_forms_get_their_own_review_roles():
    video = set(prompts.critic_roles("fiction", "video"))
    novel = set(prompts.critic_roles("fiction", "novel"))
    audio = set(prompts.critic_roles("fiction", "audiobook"))
    assert novel != video
    assert "prose" in novel and "pull" in novel
    assert "listenability" in audio
    assert "listenability" not in novel


def test_each_form_tells_the_model_what_the_finished_piece_is():
    for form in store.FORMS:
        block = prompts.form_block(form)
        assert block and block != prompts.form_block("video") or form == "video"
    assert "不要寫「畫面」" in prompts.form_block("novel")
    assert "給耳朵聽" in prompts.form_block("audiobook")
    assert "一張圖" in prompts.form_block("gallery")


def test_a_novel_episode_produces_text_and_no_video(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "小說成品", form="novel")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "novel.txt").is_file()
    assert (out / "manuscript.md").is_file()
    assert not (out / "video.mp4").exists()
    assert not (out / "subtitles.srt").exists()
    verify = ep["files"]["verify"]
    assert verify["checks"]["成品形態"]["ok"] is True
    assert "不配音" in verify["checks"]["成品形態"]["value"]


def test_an_audiobook_episode_produces_an_mp3_and_chapters(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "MP3 小說成品", form="audiobook")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "audiobook.mp3").is_file()
    assert (out / "audiobook.mp3").stat().st_size > 0
    assert (out / "chapters.json").is_file()
    chapters = json.loads((out / "chapters.json").read_text("utf-8"))
    assert chapters and all("start" in c for c in chapters)
    assert not (out / "video.mp4").exists()


def test_a_gallery_episode_produces_images_and_captions(offline, ceiling, fakes, monkeypatch):
    client = offline
    monkeypatch.setattr(comfy, "health", lambda timeout=4: {"ok": True, "detail": "fake"})
    sources._cache.clear()
    eid = _restricted_episode_form(client, "圖集成品", form="gallery")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    images = sorted(out.glob("image_*.jpg"))
    assert images, "gallery must ship images"
    assert (out / "captions.json").is_file()
    caps = json.loads((out / "captions.json").read_text("utf-8"))
    assert len(caps) == len(images)
    assert all(c["caption"] for c in caps)
    assert not (out / "video.mp4").exists()


def test_a_talk_episode_produces_a_script_and_no_video(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "話題評論成品", form="talk")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "script.txt").is_file()
    assert (out / "manuscript.md").is_file()
    assert not (out / "video.mp4").exists()


# ---------- NSFW style cards ----------

def test_nsfw_style_cards_exist_with_a_rating_floor():
    assert len(NSFW_PRESETS) >= 8
    for card in NSFW_PRESETS:
        assert card["rating_min"] in ("suggestive", "adult"), card["id"]
        assert card["category"] in NSFW_CATEGORIES
        assert card["avoid"], "every adult card must carry its hard lines"
        assert any("未成年" in a for a in card["avoid"]), card["id"]
        assert "未經同意" in " ".join(card["avoid"]) or card["rating_min"] == "suggestive", card["id"]


def test_a_general_channel_never_sees_the_adult_cards(data):
    """The cards are gated by the channel ceiling: not hidden, simply absent."""
    assert store.get_channel()["max_rating"] == "general"
    ids = {c["id"] for c in store.preset_styles()}
    assert not any(i.startswith("nsfw-") for i in ids)
    assert "情慾敘事" not in store.style_categories()
    _raise_ceiling(data, "adult")
    ids = {c["id"] for c in store.preset_styles()}
    assert "nsfw-narr-slowburn" in ids
    assert "情慾敘事" in store.style_categories()


def test_nsfw_cards_survive_the_store_round_trip(data):
    _raise_ceiling(data, "adult")
    styles = store.get_styles()
    card = next(c for c in styles["items"] if c["id"] == "nsfw-narr-slowburn")
    assert card["nsfw"] is True
    assert card["rating_min"] == "adult"
    assert card["forms"]
    general = next(c for c in styles["items"] if not c["id"].startswith("nsfw-"))
    assert general["nsfw"] is False
    assert general["rating_min"] == "general"


def test_the_nsfw_categories_are_declared_separately():
    for cat in ("情慾敘事", "感官描寫", "成人話題", "角色關係"):
        assert cat in NSFW_CATEGORIES
        assert cat not in store.STYLE_CATEGORIES       # general list stays untouched


def test_meta_exposes_forms_and_nsfw_topics(client):
    meta = client.get("/api/meta").json()
    assert meta["forms"] == list(store.FORMS)
    assert set(meta["critics_by_form"]) == set(store.FORMS)
    assert meta["nsfw_topics"]
    assert meta["form_label"]["novel"] == "小說／文字"


# ---------- every NSFW deliverable format ----------

def test_every_content_form_has_at_least_one_nsfw_card():
    """A format with no card would leave the owner with no guidance for it."""
    missing = [f for f in store.FORMS if not any(f in c["forms"] for c in NSFW_PRESETS)]
    assert missing == [], f"這些形態沒有對應的 NSFW 風格卡：{missing}"


def test_every_nsfw_card_only_names_real_forms():
    for card in NSFW_PRESETS:
        for f in card["forms"]:
            assert f in store.FORMS, (card["id"], f)


def test_every_form_has_its_own_prompt_rule_and_review_roles():
    for form in store.FORMS:
        assert form in prompts.FORM_RULES, f"{form} 沒有提示詞規則"
        assert prompts.form_block(form).strip()
        roles = prompts.critic_roles("fiction", form)
        assert roles, form


def test_the_forms_cover_the_shapes_adult_content_takes():
    """Text, voice, image, screen and stage: the vocabulary has to reach all of them."""
    for f in ("novel", "serial", "poem", "chat", "script", "comic", "guide",
              "audiobook", "radio_drama", "asmr", "gallery", "video", "talk"):
        assert f in store.FORMS, f


def test_text_forms_each_write_their_own_layout():
    blocks = [{"headline": "第一章", "body": "A：你睡了嗎\nB：還沒\nA：那就好"}]
    for form, marker in (("chat", "A：你睡了嗎"), ("poem", "A：你睡了嗎"),
                         ("comic", "第 1 格："), ("script", "內景／外景")):
        rendered = pipeline._RENDERERS[store.form_layout(form)](blocks)
        assert marker in rendered, (form, rendered)
    assert "第 1 格：" in pipeline._RENDERERS["panels"](blocks)
    assert "內景／外景" in pipeline._RENDERERS["screenplay"](blocks)
    # prose and chapters stay prose
    assert pipeline._RENDERERS["prose"](blocks) == pipeline._RENDERERS["chapters"](blocks)


def test_each_text_form_ships_a_named_file():
    for form in pipeline.TEXT_FORMS:
        assert form in pipeline.TEXT_TARGET, form
        assert pipeline._form_outputs(form), form
    assert pipeline.TEXT_TARGET["script"] == "screenplay.txt"
    assert pipeline.TEXT_TARGET["comic"] == "comic_script.txt"
    assert "radio_drama.mp3" in pipeline._form_outputs("radio_drama")
    assert "asmr.mp3" in pipeline._form_outputs("asmr")


def test_a_serial_episode_ships_chapters_not_a_film(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "連載成品", form="serial")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "serial.txt").is_file()
    assert (out / "manuscript.md").is_file()
    assert not (out / "video.mp4").exists()


def test_a_chat_episode_ships_the_message_log(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "訊息體成品", form="chat")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "chat.txt").is_file()
    assert not (out / "video.mp4").exists()


def test_a_comic_episode_ships_a_panel_script(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "漫畫腳本成品", form="comic")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "comic_script.txt").is_file()
    assert not (out / "video.mp4").exists()


def test_an_asmr_episode_ships_an_audio_track(offline, ceiling, fakes):
    client = offline
    eid = _restricted_episode_form(client, "耳語音檔成品", form="asmr")
    ep = _run_to_done(client, eid, rating="adult")
    out = Path(ep["published_dir"])
    assert (out / "asmr.mp3").is_file()
    assert (out / "asmr.mp3").stat().st_size > 0
    assert (out / "asmr_script.txt").is_file()
    assert not (out / "video.mp4").exists()


# ---------- pre-filling the new-episode dialog from the topic ----------

def test_the_rules_guess_every_setting_from_the_topic(data):
    _raise_ceiling(data)
    s = suggest.suggest("情慾小說：深夜的公寓")
    assert s["mode"] == "fiction"
    assert s["rating"] == "adult"
    assert s["form"] == "novel"
    assert s["style_id"].startswith("nsfw-")
    assert s["by"] == "rules"
    assert s["reasons"], "a guess must be able to explain itself"


def test_a_news_topic_stays_news_and_general(data):
    s = suggest.suggest("黃仁勳回應 AI 泡沫")
    assert s["mode"] == "news"
    assert s["rating"] == "general"
    assert s["form"] == "video"
    assert not s["style_id"].startswith("nsfw-"), "a general topic must not get an adult card"


def test_a_poem_topic_picks_the_poem_form_and_a_narrative_mode(data):
    s = suggest.suggest("寫一首關於離別的詩")
    assert s["form"] == "poem"
    assert s["mode"] == "fiction"


def test_the_guess_never_exceeds_the_channel_ceiling(data):
    assert store.get_channel()["max_rating"] == "general"
    s = suggest.suggest("情慾小說：深夜的公寓")
    assert s["rating"] == "general", "a general-capped channel must not be offered adult"
    assert not s["style_id"].startswith("nsfw-")


def test_urls_already_in_the_topic_are_pre_filled(data):
    s = suggest.suggest("看這篇 https://example.com/a 和 https://example.com/b 的說法")
    assert "https://example.com/a" in s["source_urls"]
    assert "https://example.com/b" in s["source_urls"]


def test_known_urls_are_kept_and_merged_with_the_topic_ones(data):
    s = suggest.suggest("看這篇 https://example.com/a", urls=["https://example.com/b"])
    assert s["source_urls"][0] == "https://example.com/b"     # caller's links come first
    assert "https://example.com/a" in s["source_urls"]


def test_an_idea_format_wins_over_the_guessed_one(data):
    s = suggest.suggest("黃仁勳回應 AI 泡沫", idea_format="long")
    assert s["format"] == "long"


def test_the_guess_only_offers_settings_the_api_would_accept(data):
    _raise_ceiling(data)
    for topic in ("情慾小說：深夜的公寓", "寫一首離別的詩", "Google 發布 Gemini", "漫畫：夏天"):
        s = suggest.suggest(topic)
        assert s["mode"] in store.MODES
        assert s["rating"] in store.RATINGS
        assert s["form"] in store.FORMS
        assert s["format"] in ("short", "long")
        # the same combination the create API validates
        assert store.rating_conflict(s["mode"], s["rating"]) is None, topic


def test_the_suggest_endpoint_answers_with_a_full_pre_fill(client, ceiling):
    r = client.get("/api/suggest", params={"topic": "情慾小說：深夜的公寓"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "fiction" and body["rating"] == "adult"
    assert body["form"] == "novel"
    assert isinstance(body["source_urls"], list)
    assert body["reasons"]


def test_the_suggest_endpoint_reads_the_idea_it_was_given(client, ceiling):
    idea = client.post("/api/ideas", json={"title": "情慾小說：雨夜的旅館",
                                            "urls": ["https://example.com/ref"],
                                            "kind": "note"}).json()
    r = client.get("/api/suggest", params={"idea_id": idea["id"]})
    assert r.status_code == 200
    body = r.json()
    assert "旅館" in body["topic"]
    assert "https://example.com/ref" in body["source_urls"]
    assert body["form"] == "novel"
