"""Content Factory web app (FastAPI)."""
from __future__ import annotations

import csv
import html
import io
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import characters, comfy, cost, llm, media, music, pipeline, prompts, sfx, sources, stock, stock_audio, store, suggest, video, video_analysis, watch, youtube
from . import health as service_health

app = FastAPI(title="內容工廠")
STATIC = store.ROOT / "static"
store.DATA.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def _startup() -> None:
    pipeline.start_worker()
    cur = store.get_insights_summary()  # a restart in the middle of an analysis leaves this flag set
    if cur.get("analyzing"):
        store.save_insights_summary({**cur, "analyzing": False, "error": "上次分析被伺服器重啟中斷，請重新分析"})
    watch.reset_running("上次掃描被伺服器重啟中斷，請重新掃描。")  # watch scan running at restart
    radar = store.get_radar_state()  # same for a radar scan that was running at restart
    if radar.get("status") == "running":
        store.save_radar_state({**radar, "status": "error", "finished": time.time(), "error": "上次掃描被伺服器重啟中斷",
                                "message": "上次掃描被伺服器重啟中斷，請重新掃描。"})
    for ep in store.list_episodes():  # resume work interrupted by a restart
        if (ep.get("youtube") or {}).get("status") in ("queued", "uploading"):
            store.update_episode(ep["id"], youtube={**ep["youtube"], "status": "error", "error": "上傳被伺服器重啟中斷，請重新上傳"})
        if ep["status"] in ("queued", "running"):
            store.log(ep["id"], "伺服器重啟，重新排入佇列")
            pipeline.enqueue("episode", ep["id"])
    watch.start_scheduler()


def _ep(eid: str) -> dict:
    try:
        ep = store.visible_episode(eid)
    except ValueError:
        ep = None
    if not ep:
        raise HTTPException(404, "找不到這一集")
    return ep


# ---------- meta & config ----------

@app.get("/api/meta")
def meta():
    return {
        "stages": pipeline.STAGES,
        "stage_label": pipeline.STAGE_LABEL,
        "wait_label": pipeline.WAIT_LABEL,
        "styles": prompts.STYLES,
        "critics": {k: v[0] for k, v in prompts.CRITICS.items()},
        "critics_by_mode": {m: {k: v[0] for k, v in prompts.critic_roles(m).items()}
                             for m in store.MODES},
        "critics_by_form": {f: {k: v[0] for k, v in prompts.critic_roles("fiction", f).items()}
                             for f in store.FORMS},
        "modes": list(store.MODES),
        "mode_label": store.MODE_LABEL,
        "ratings": list(store.RATINGS),
        "rating_label": store.RATING_LABEL,
        "forms": list(store.FORMS),
        "form_label": store.FORM_LABEL,
        "form_desc": store.FORM_DESC,
        "nsfw_topics": list(store.NSFW_TOPICS),
        # the effective ceiling: the channel's own limit, capped to `general` when the NSFW
        # switch is off, so every consumer (dialog, card picker, create API) inherits the cap
        "max_rating": store.effective_max_rating(),
        "pref_cats": store.PREF_CATS,
        "style_categories": store.style_categories(),
        "sfx_tags": sfx.vocab(),
    }


@app.get("/api/health")
def health(llm_check: bool = False):
    out = {"tts": media.tts_health(), "worker": pipeline.busy(), "provider": store.get_settings()["llm"]["provider"],
           "comfy": _comfy_status()}
    if llm_check:
        out["llm"] = llm.health()
    return out


@app.get("/api/status")
def service_status():
    """Status page: every local service and CLI, probed in parallel (never starts anything)."""
    return service_health.services()


def _comfy_status() -> dict:
    """ComfyUI's health, plus whether the current visuals chain would actually use it.

    The status bar shows one dot per service. ComfyUI being down is not an error when the
    chain does not use it (slides only), so the UI needs to know that difference.
    """
    st = comfy.status()
    chain = sources.chain("visuals")
    needed = [s for s in chain if s in ("comfy", "h3video")]
    return {**st, "needed": bool(needed), "chain": chain,
            "h3_enabled": bool(store.get_settings()["h3video"].get("enabled", True))}



@app.get("/api/settings")
def get_settings():
    return store.get_settings()


@app.get("/api/tts/models")
def tts_models(base_url: str = ""):
    """Voice-capable models the audio.cpp server has registered (for the settings dropdown)."""
    return media.list_models(base_url or None)


@app.get("/api/tts/voices")
def tts_voices(base_url: str = "", model: str = ""):
    """Reference voice library of the audio.cpp server, proxied so the browser never calls :8090."""
    return media.list_voices(base_url or None, model or None)


@app.post("/api/tts/test")
def tts_test(body: dict = Body(default={})):
    """Speak one short line with the settings shown in the form (not saved to any episode)."""
    text = (body.get("text") or "這是參考聲音測試").strip()[:200] or "這是參考聲音測試"
    over = body.get("tts") if isinstance(body.get("tts"), dict) else None
    try:
        wav = media.test_tts(text, emotion=body.get("emotion") or "", cfg=over)
    except media.MediaError as e:
        raise HTTPException(502, str(e))
    return Response(content=wav, media_type="audio/wav")


@app.put("/api/settings")
def put_settings(s: dict = Body(...)):
    return store.save_settings(s)


# ---------- visuals & sound effects ----------

@app.get("/api/sfx")
def sfx_status():
    return {**sfx.status(), "build": dict(sfx.BUILD)}


@app.post("/api/sfx/build")
def sfx_build(body: dict = Body(default={})):
    tags = [t for t in (body.get("tags") or []) if t]
    try:
        return sfx.build_async(tags or None, force=bool(body.get("force")))
    except sfx.SfxError as e:
        raise HTTPException(400, str(e))


@app.post("/api/sfx/import")
def sfx_import(body: dict = Body(...)):
    try:
        return sfx.import_files(body.get("folder") or "", body.get("tag") or "")
    except sfx.SfxError as e:
        raise HTTPException(400, str(e))


@app.post("/api/sfx/stock")
def sfx_stock(body: dict = Body(default={})):
    tags = [t for t in (body.get("tags") or []) if t]
    return sfx.stock_fill(tags or None, force=bool(body.get("force")))


@app.get("/api/stock/audio")
def stock_audio_status():
    return stock_audio.status()


@app.get("/api/visuals/health")
def visuals_health():
    return comfy.health()


@app.get("/api/visuals/presets")
def visuals_presets():
    return comfy.presets()


@app.get("/api/stock")
def stock_status():
    return stock.status()


@app.get("/api/cost")
def cost_status():
    return cost.status()


@app.post("/api/episodes/{eid}/cost")
def cost_approve(eid: str):
    with _gate(eid, "cost"):
        mc = store.get_settings()["music"]
        usd = cost.price((mc.get("lyria_model") or "lyria-3-clip-preview").strip())
        cost.approve(eid, usd)
        store.log(eid, f"使用者核准雲端花費 ${usd:.2f}")
        pipeline.enqueue("episode", eid)
    return {"ok": True, "usd": usd}


@app.get("/api/music")
def music_status():
    return music.status()


@app.get("/api/sources")
def sources_status(probe: bool = True):
    """Source chains per category (visuals / voice / music / sfx) with live health lights."""
    return sources.overview(probe_all=probe)


@app.get("/api/render/remotion")
def remotion_status():
    return video.available()


@app.post("/api/music/preview")
def music_preview(body: dict = Body(default={})):
    """Short instrumental bed for auditioning a style before a full assemble."""
    secs = float(body.get("seconds") or 20)
    try:
        p = music.generate(secs, (body.get("style") or "").strip(), seed=body.get("seed"),
                           force=bool(body.get("force")))
    except music.MusicError as e:
        raise HTTPException(400, str(e))
    return {"file": p.name, "path": str(p), "url": f"/files/{p.relative_to(store.DATA).as_posix()}",
            **music.probe_wav(p)}


@app.post("/api/music/open")
def music_open(body: dict = Body(default={})):
    p = Path(body.get("path") or "").resolve()
    if not p.is_file():
        raise HTTPException(400, "找不到音檔")
    if store.DATA.resolve() not in p.parents:
        raise HTTPException(400, "音檔不在資料夾內，無法播放")
    return {"url": f"/files/{p.relative_to(store.DATA.resolve()).as_posix()}"}


@app.get("/api/channel")
def get_channel():
    return store.get_channel()


@app.put("/api/channel")
def put_channel(c: dict = Body(...)):
    return store.save_channel(c)


# ---------- preferences (taste rules) ----------

@app.get("/api/preferences")
def get_prefs():
    return store.get_prefs()


@app.put("/api/preferences")
def put_prefs(p: list = Body(...)):
    return store.save_prefs(p)


@app.post("/api/preferences")
def create_pref(body: dict = Body(...)):
    rule = (body.get("rule") or "").strip()
    if not rule:
        raise HTTPException(400, "請輸入規則內容")
    return store.add_pref(
        body.get("category") or "講稿語氣",
        rule,
        status=body.get("status") or "active",
        source=body.get("source") or "manual",
        evidence=body.get("evidence") or "",
    )


@app.patch("/api/preferences/{pid}")
def patch_pref(pid: str, body: dict = Body(...)):
    updated = store.update_pref(pid, body)
    if not updated:
        raise HTTPException(404, "找不到這條規則")
    return updated


@app.delete("/api/preferences/{pid}")
def remove_pref(pid: str):
    if not store.delete_pref(pid):
        raise HTTPException(404, "找不到這條規則")
    return {"ok": True}


# ---------- styles ----------

@app.get("/api/nsfw")
def nsfw_state():
    forced = (os.environ.get("CF_NSFW") or "").strip().lower()
    return {"enabled": store.nsfw_enabled(),
            "forced_off": forced in ("0", "false", "off", "no")}


@app.put("/api/nsfw")
def set_nsfw_state(body: dict = Body(...)):
    """Flip the switch. Off hides restricted episodes everywhere; on resumes the ones it paused."""
    on = bool(body.get("enabled"))
    forced = (os.environ.get("CF_NSFW") or "").strip().lower()
    if forced in ("0", "false", "off", "no") and on:
        raise HTTPException(409, "這台機器用 CF_NSFW=0 強制關閉，不能從介面打開")
    state = store.set_nsfw(on)
    resumed = pipeline.resume_paused() if state else 0
    return {"enabled": state, "resumed": resumed}


@app.post("/api/nsfw/resume")
def nsfw_resume():
    """Re-queue the episodes a closed switch paused (idempotent)."""
    return {"resumed": pipeline.resume_paused()}


@app.get("/api/styles")
def list_styles():
    data = store.get_styles()
    if not store.nsfw_enabled():
        data = {**data, "items": [c for c in data["items"] if not c.get("nsfw")]}
    return data


# ---------- character cards ----------

@app.get("/api/characters")
def list_characters():
    items = characters.list_all()
    if not store.nsfw_enabled():
        items = [c for c in items if not c.get("ref_image") and not c.get("adult_attested")]
    return {"items": items}


@app.post("/api/characters")
def create_character(body: dict = Body(...)):
    card = characters.save(body)
    return card


@app.put("/api/characters/{cid}")
def update_character(cid: str, body: dict = Body(...)):
    body = {**body, "id": cid}
    return characters.save(body)


@app.delete("/api/characters/{cid}")
def delete_character(cid: str):
    if not characters.delete(cid):
        raise HTTPException(404, "找不到這張角色卡")
    return {"ok": True}


@app.post("/api/styles")
def create_style(body: dict = Body(...)):
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "請輸入風格名稱")
    return store.create_style(body, activate=bool(body.get("activate")))


@app.put("/api/styles/{sid}")
def update_style(sid: str, body: dict = Body(...)):
    updated = store.update_style(sid, body)
    if not updated:
        raise HTTPException(404, "找不到這張風格卡")
    return updated


@app.delete("/api/styles/{sid}")
def delete_style(sid: str):
    try:
        ok = store.delete_style(sid)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not ok:
        raise HTTPException(404, "找不到這張風格卡")
    return {"ok": True}


@app.post("/api/styles/{sid}/activate")
def activate_style(sid: str):
    try:
        return store.activate_style(sid)
    except KeyError as e:
        raise HTTPException(404, "找不到這張風格卡") from e


@app.post("/api/styles/extract")
def extract_style(body: dict = Body(...)):
    parts: list[str] = []
    text = (body.get("text") or "").strip()
    if text:
        parts.append(text)
    for eid in body.get("episode_ids") or []:
        try:
            scr = store.read_json(eid, "script.json", None)
        except ValueError:
            scr = None
        if isinstance(scr, dict) and scr.get("scenes"):
            ep = store.get_episode(eid)
            title = (ep or {}).get("topic") or eid
            nar = "\n".join((s.get("narration") or "").strip() for s in scr["scenes"] if s.get("narration"))
            if nar:
                parts.append(f"【{title}】\n{nar}")
    sample = "\n\n".join(parts).strip()
    if not sample:
        raise HTTPException(400, "請貼上示範講稿，或勾選至少一集已有講稿的集數")
    try:
        sys, pr = prompts.extract_style(sample, body.get("name") or "")
        data = llm.complete_json("extract_style", sys, pr)
    except llm.LLMError as e:
        raise HTTPException(502, str(e)) from e
    if not isinstance(data, dict) or not (data.get("name") or "").strip():
        raise HTTPException(502, "模型沒有回傳合法的風格卡")
    data["source"] = "由範本提煉"
    return store.create_style(data, activate=True)


# ---------- radar & ideas ----------

@app.post("/api/styles/from-video")
def style_from_video(body: dict = Body(...)):
    try:
        return video_analysis.analyze(body.get("url") or "", body.get("name") or "")
    except video_analysis.VideoAnalysisError as e:
        raise HTTPException(400, str(e))
    except llm.LLMError as e:
        raise HTTPException(400, str(e))


@app.get("/api/radar")
def radar():
    return store.get_radar()


@app.get("/api/radar/state")
def radar_state():
    return store.get_radar_state()


@app.post("/api/radar/scan")
def radar_scan(body: dict = Body(...)):
    seeds = (body.get("seeds") or "").strip()
    if not seeds:
        raise HTTPException(400, "請貼上線索（連結、熱門話題或筆記）")
    store.save_radar_state({
        "status": "running", "message": "正在抓取線索與整理候選…", "started": time.time(),
        "finished": None, "added": 0, "failed_urls": [], "error": None,
    })
    pipeline.enqueue("radar", seeds)
    return {"ok": True}


@app.get("/api/watch")
def watch_list():
    return {"sources": watch.list_sources(), "now": time.time()}


@app.get("/api/watch/catalog")
def watch_catalog():
    return {"catalog": watch.catalog()}


@app.post("/api/watch/catalog")
def watch_catalog_add(body: dict = Body(...)):
    try:
        src = watch.add_catalog(body.get("id") or "")
    except watch.WatchError as e:
        raise HTTPException(400, str(e)) from e
    if body.get("run_now") and not src["already"]:
        watch.run_now(src["id"])
    return src


@app.post("/api/watch/keyword")
def watch_keyword(body: dict = Body(...)):
    try:
        src = watch.add_keyword(body.get("keyword") or "")
    except watch.WatchError as e:
        raise HTTPException(400, str(e)) from e
    if body.get("run_now") and not src["already"]:
        watch.run_now(src["id"])
    return src


@app.post("/api/watch")
def watch_create(body: dict = Body(...)):
    try:
        src = watch.create(body)
    except watch.WatchError as e:
        raise HTTPException(400, str(e)) from e
    if body.get("run_now"):
        watch.run_now(src["id"])
    return src


@app.put("/api/watch/{sid}")
def watch_update(sid: str, body: dict = Body(...)):
    try:
        return watch.update(sid, body)
    except watch.WatchError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/watch/{sid}")
def watch_delete(sid: str):
    if not watch.delete(sid):
        raise HTTPException(404, "找不到這個訂閱來源")
    return {"ok": True}


@app.post("/api/watch/{sid}/run")
def watch_run(sid: str):
    try:
        queued = watch.run_now(sid)
    except watch.WatchError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "queued": queued}


@app.delete("/api/radar/{idx}")
def radar_delete(idx: int):
    items = store.all_ideas()
    if 0 <= idx < len(items):
        items.pop(idx)
        store.save_radar(items)
    return items


@app.get("/api/ideas")
def get_ideas():
    return store.list_ideas()


@app.post("/api/ideas")
def create_idea(body: dict = Body(...)):
    title = (body.get("title") or "").strip()
    notes = (body.get("notes") or "").strip()
    urls = [str(u).strip() for u in (body.get("urls") or []) if str(u).strip()]
    if not title and not notes and not urls:
        raise HTTPException(400, "請輸入靈感內容或連結")
    try:
        return store.add_idea(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/ideas/{iid}")
def update_idea(iid: str, body: dict = Body(...)):
    updated = store.update_idea(iid, body)
    if not updated:
        raise HTTPException(404, "找不到這條靈感")
    return updated


@app.delete("/api/ideas/{iid}")
def delete_idea(iid: str):
    if not store.delete_idea(iid):
        raise HTTPException(404, "找不到這條靈感")
    return {"ok": True}


# ---------- episodes ----------

@app.get("/api/episodes")
def episodes():
    return store.list_episodes()


@app.get("/api/suggest")
def suggest_episode(topic: str = "", notes: str = "", format: str = "", urls: str = "",
                    idea_id: str = "", deep: bool = False):
    """Pre-fill the new-episode dialog: rules fire instantly, `deep=1` asks the model too.

    The dialog calls this twice: once without `deep` the moment the dialog opens (so the
    controls are never blank), then again with `deep=1` in the background to refine.
    """
    idea_urls: list[str] = []
    idea = store.get_idea(idea_id) if idea_id else None
    if idea:
        idea_urls = [u for u in (idea.get("urls") or []) if str(u).startswith("http")]
        topic = topic or idea.get("title") or ""
        notes = notes or idea.get("notes") or idea.get("why") or ""
    given = [u.strip() for u in (urls or "").splitlines() if u.strip().startswith("http")]
    return suggest.suggest(topic, notes, [*given, *idea_urls], idea_format=format or None, deep=deep)


@app.post("/api/episodes")
def create_episode(body: dict = Body(...)):
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "請輸入題目")
    fmt = body.get("format") if body.get("format") in ("long", "short") else "short"
    urls = [u.strip() for u in (body.get("source_urls") or []) if str(u).strip().startswith("http")]
    characters = [str(c).strip() for c in (body.get("characters") or []) if str(c).strip()]
    try:
        ep = store.new_episode(
            topic,
            fmt,
            body.get("notes", ""),
            urls,
            style_id=body.get("style_id") or None,
            idea_id=body.get("idea_id") or None,
            mode=body.get("mode") or "news",
            rating=body.get("rating") or "general",
            characters=characters,
            form=body.get("form") or "",
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    pipeline.enqueue("episode", ep["id"])
    return ep


@app.get("/api/episodes/{eid}")
def episode(eid: str):
    ep = _ep(eid)
    files = {}
    for name in ("brief.json", "script.json", "critique.json", "package.json",
                 "output/storyboard.json", "output/verify.json"):
        files[name.split("/")[-1].removesuffix(".json")] = store.read_json(eid, name)
    d = store.ep_dir(eid)
    ep["files"] = files
    ep["video"] = f"episodes/{eid}/output/final.mp4" if (d / "output/final.mp4").exists() else None
    ep["published_dir"] = str(d / "publish") if (d / "publish").exists() else None
    ep["metrics"] = store.read_json(eid, "metrics.json", [])
    return ep


@app.delete("/api/episodes/{eid}")
def delete_episode(eid: str):
    _ep(eid)
    if pipeline.busy()["current"].get("args", [None])[0] == eid:
        raise HTTPException(409, "這一集正在處理，請稍後再刪")
    shutil.rmtree(store.ep_dir(eid))
    return {"ok": True}


@app.patch("/api/episodes/{eid}/schedule")
def set_schedule(eid: str, body: dict = Body(...)):
    _ep(eid)
    try:
        return store.update_schedule(eid, body.get("schedule"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@contextmanager
def _gate(eid: str, what: str | None, status: str = "waiting"):
    """Claim a gate atomically (status -> queued) before acting on it.

    A double click or a second tab gets 409 instead of running the pipeline twice.
    If the decision fails (bad input, error), the episode goes back to the gate it was at.
    """
    _ep(eid)
    before = store.claim_episode(eid, status, what)
    if before is None:
        if status != "waiting":
            raise HTTPException(409, "這一集目前的狀態不能做這個動作")
        if what is None:
            raise HTTPException(409, "只有在等你決定時才能退件")
        raise HTTPException(409, f"這一集目前不是在等「{pipeline.WAIT_LABEL[what]}」")
    try:
        yield before
    except Exception:
        store.update_episode(eid, status=before["status"], waiting_for=before.get("waiting_for"),
                             error=before.get("error"))
        raise


@app.post("/api/episodes/{eid}/sources")
def episode_sources(eid: str, body: dict = Body(...)):
    with _gate(eid, "sources"):
        pipeline.sources_decision(eid, body.get("notes", ""), body.get("source_urls") or [], bool(body.get("proceed")))
    return {"ok": True}


@app.post("/api/episodes/{eid}/direction")
def direction(eid: str, body: dict = Body(...)):
    with _gate(eid, "direction"):
        try:
            pipeline.choose_direction(eid, str(body.get("id") or ""), body.get("notes", ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.post("/api/episodes/{eid}/script")
def script(eid: str, body: dict = Body(...)):
    with _gate(eid, "script"):
        try:
            pipeline.script_decision(eid, bool(body.get("approve")), body.get("feedback", ""), body.get("script"))
        except llm.LLMError as e:  # an edited script without readable scenes
            raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.get("/api/episodes/{eid}/storyboard")
def storyboard(eid: str):
    ep = _ep(eid)
    p = store.ep_dir(eid) / "output" / "storyboard.json"
    if not p.exists():
        raise HTTPException(404, "還沒有分鏡，等這一集跑到分鏡階段")
    return {**store.read_json(eid, "output/storyboard.json"),
            "waiting": ep["status"] == "waiting" and ep["waiting_for"] == "storyboard"}


@app.post("/api/episodes/{eid}/storyboard")
def storyboard_decide(eid: str, body: dict = Body(...)):
    approve = bool(body.get("approve"))
    notes = (body.get("notes") or "").strip()
    if not approve and not notes:
        raise HTTPException(400, "退回請留一句原因，系統會記下來")
    with _gate(eid, "storyboard"):
        pipeline.storyboard_decision(eid, approve, notes)
    return {"ok": True}


@app.post("/api/episodes/{eid}/package")
def package(eid: str, body: dict = Body(...)):
    try:
        title_idx, thumb_idx = int(body.get("title", 0)), int(body.get("thumb", 0))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, "標題或縮圖編號不正確") from e
    with _gate(eid, "package"):
        try:
            pipeline.package_choice(eid, title_idx, body.get("custom_title", ""), thumb_idx, body.get("schedule", ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.post("/api/episodes/{eid}/approve")
def approve(eid: str, body: dict = Body(default={})):
    with _gate(eid, "approval"):
        try:
            pipeline.approve(eid, confirm_rating=(body.get("confirm_rating") or ""))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.post("/api/episodes/{eid}/reject")
def reject(eid: str, body: dict = Body(...)):
    _ep(eid)
    back = body.get("back_to")
    if back not in pipeline.REJECT_TO:
        raise HTTPException(400, "退回階段不正確")
    if not (body.get("reason") or "").strip():
        raise HTTPException(400, "請留一句退件理由，系統會記下來")
    with _gate(eid, None):
        pipeline.reject(eid, back, body["reason"])
    return {"ok": True}


@app.post("/api/episodes/{eid}/retry")
def retry(eid: str):
    _ep(eid)
    if not store.claim_episode(eid, "error"):
        raise HTTPException(409, "只有出錯的集數可以重試")
    pipeline.enqueue("episode", eid)
    return {"ok": True}


@app.post("/api/episodes/{eid}/metrics")
def add_metrics(eid: str, body: dict = Body(...)):
    _ep(eid)
    m = store.read_json(eid, "metrics.json", [])
    keys = ("platform", "date", "views", "watch_time", "followers", "likes", "saves", "comments", "note")
    m.append({k: body.get(k) for k in keys})
    store.write_json(eid, "metrics.json", m)
    return m


@app.delete("/api/episodes/{eid}/metrics/{idx}")
def delete_metrics(eid: str, idx: int):
    _ep(eid)
    m = store.read_json(eid, "metrics.json", [])
    if not (0 <= idx < len(m)):
        raise HTTPException(404, "找不到這筆成效紀錄")
    m.pop(idx)
    store.write_json(eid, "metrics.json", m)
    return m


def _yt_video_id(ep: dict) -> str:
    return str(((ep.get("youtube") or {}).get("video_id")) or "").strip()


def _apply_youtube_stats(eid: str, stats: dict) -> tuple[dict, str]:
    """Write today's YouTube row: update the same-day row, otherwise append one."""
    rows = store.read_json(eid, "metrics.json", [])
    today = time.strftime("%Y-%m-%d")
    for row in rows:
        if (isinstance(row, dict) and str(row.get("platform") or "").lower() == "youtube"
                and str(row.get("date") or "") == today):
            for k in ("views", "likes", "comments"):
                row[k] = str(stats.get(k, 0))
            store.write_json(eid, "metrics.json", rows)
            return row, "updated"
    row = {"platform": "YouTube", "date": today, "views": str(stats.get("views", 0)),
           "watch_time": "", "followers": "", "likes": str(stats.get("likes", 0)),
           "saves": "", "comments": str(stats.get("comments", 0)), "note": ""}
    rows.append(row)
    store.write_json(eid, "metrics.json", rows)
    return row, "appended"


@app.post("/api/episodes/{eid}/metrics/youtube")
def sync_youtube_metric(eid: str, body: dict | None = Body(default=None)):
    """Pull views/likes/comments from the YouTube Data API for one episode.

    `url` is optional: manual uploads have no video id, so the owner can paste the link once.
    """
    ep = _ep(eid)
    url = str((body or {}).get("url") or "").strip()
    vid = _yt_video_id(ep)
    if url:
        vid = youtube.video_id_from_url(url)
        if not vid:
            raise HTTPException(400, "這不是可辨識的 YouTube 影片網址")
        yt = {**(ep.get("youtube") or {}), "video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"}
        store.update_episode(eid, youtube=yt)
    if not vid:
        raise HTTPException(400, "這一集還沒有 YouTube 影片，請貼上影片網址")
    try:
        stats = youtube.video_stats([vid]).get(vid)
    except youtube.YouTubeError as e:
        raise HTTPException(400, str(e)) from e
    if not stats:
        raise HTTPException(404, "YouTube 找不到這支影片（可能已刪除、未公開，或不同頻道）")
    row, action = _apply_youtube_stats(eid, stats)
    return {"action": action, "row": row, "video_id": vid}


@app.post("/api/insights/sync-youtube")
def sync_insights_youtube():
    """Refresh today's metrics for every episode that already has a YouTube video id."""
    todo = [(ep["id"], _yt_video_id(ep)) for ep in store.list_episodes() if _yt_video_id(ep)]
    if not todo:
        raise HTTPException(400, "還沒有任何集數連結 YouTube 影片，請到集數頁貼上影片網址")
    try:
        stats = youtube.video_stats([vid for _, vid in todo])
    except youtube.YouTubeError as e:
        raise HTTPException(400, str(e)) from e
    updated, missing = 0, []
    for eid, vid in todo:
        s = stats.get(vid)
        if not s:
            missing.append(eid)
            continue
        _apply_youtube_stats(eid, s)
        updated += 1
    return {"updated": updated, "missing": missing}


# ---------- insights ----------

@app.get("/api/insights")
def insights(days: int = 30, platform: str = "all"):
    return store.aggregate_insights(days=days, platform=platform)


@app.post("/api/insights/analyze")
def insights_analyze():
    agg = store.aggregate_insights(days=0, platform="all")
    if agg["totals"]["records"] == 0:
        raise HTTPException(400, "請先錄入至少一筆成效數據")
    cur = store.get_insights_summary()
    store.save_insights_summary({**cur, "analyzing": True, "error": None})
    pipeline.enqueue("insights_analyze")
    return {"ok": True}


CSV_ALIASES = {
    "episode": ("集數", "集數id", "標題", "題目", "episode", "episode_id", "title"),
    "platform": ("平台", "platform"),
    "date": ("日期", "date"),
    "views": ("觀看", "觀看數", "播放", "播放量", "views"),
    "watch_time": ("平均觀看", "完播", "watch_time"),
    "followers": ("新追蹤", "漲粉", "追蹤", "followers"),
    "likes": ("讚", "點讚", "按讚", "likes"),
    "saves": ("收藏", "saves"),
    "comments": ("留言", "評論", "comments"),
    "note": ("備註", "note"),
}


def _csv_val(norm_row: dict[str, str], field: str) -> str:
    for alias in CSV_ALIASES[field]:
        if alias in norm_row and norm_row[alias] != "":
            return norm_row[alias]
    return ""


def _match_titles(ep: dict) -> list[str]:
    return [t for t in (
        ((ep.get("package_choice") or {}).get("title") or "").strip().lower(),
        (ep.get("topic") or "").strip().lower(),
    ) if t]


def _match_episode(query: str, eps: list[dict]) -> tuple[dict | None, str]:
    """Return (episode, reason). Reason explains why nothing matched."""
    q = query.strip().lower()
    if not q:
        return None, "沒有填集數"
    for ep in eps:
        if ep["id"].lower() == q:
            return ep, ""
    for ep in eps:
        if q in _match_titles(ep):
            return ep, ""
    if len(q) < 4:
        return None, "名稱太短，請填集數 id 或完整標題"
    need = max(4, (len(q) + 1) // 2)  # at least half of the text has to overlap, never a 3-char hit
    scored = []
    for ep in eps:
        best = 0
        for t in _match_titles(ep):
            short, long_ = (q, t) if len(q) <= len(t) else (t, q)
            if len(short) >= need and short in long_:
                best = max(best, len(short))
        if best:
            scored.append((best, ep))
    if not scored:
        return None, "找不到對應集數"
    scored.sort(key=lambda x: x[0], reverse=True)
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 2:
        return None, "對到多集，請改填集數 id"
    return scored[0][1], ""


def _metric_row(platform: str, date: str, views: str, watch_time: str, followers: str,
                likes: str, saves: str, comments: str, note: str) -> dict:
    return {"platform": platform, "date": date, "views": views, "watch_time": watch_time,
            "followers": followers, "likes": likes, "saves": saves, "comments": comments, "note": note}


def _metric_sig(m: dict) -> tuple:
    return tuple(str(m.get(k) or "").strip() for k in
                 ("platform", "date", "views", "watch_time", "followers", "likes", "saves", "comments", "note"))


@app.post("/api/insights/import-csv")
def insights_import_csv(body: dict = Body(...)):
    raw = (body.get("csv") or "").lstrip("\ufeff").strip()
    if not raw:
        raise HTTPException(400, "請貼上 CSV 內容")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV 缺少標題列")
    eps = store.list_episodes()
    imported = 0
    skipped: list[str] = []
    per_ep: dict[str, list[dict]] = {}
    seen: dict[str, set[tuple]] = {}
    for row_no, row in enumerate(reader, 2):
        norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
        if not any(norm.values()):
            continue
        target_q = _csv_val(norm, "episode")
        ep, why = _match_episode(target_q, eps)
        if not ep:
            skipped.append(f"第 {row_no} 行{why}：{target_q or '（空）'}")
            continue
        eid = ep["id"]
        if eid not in per_ep:
            per_ep[eid] = store.read_json(eid, "metrics.json", [])
            seen[eid] = {_metric_sig(m) for m in per_ep[eid] if isinstance(m, dict)}
        entry = _metric_row(
            _csv_val(norm, "platform") or "YouTube",
            _csv_val(norm, "date"),
            _csv_val(norm, "views"),
            _csv_val(norm, "watch_time"),
            _csv_val(norm, "followers"),
            _csv_val(norm, "likes"),
            _csv_val(norm, "saves"),
            _csv_val(norm, "comments"),
            _csv_val(norm, "note"),
        )
        sig = _metric_sig(entry)
        if sig in seen[eid]:
            skipped.append(f"第 {row_no} 行重複（這集已有同樣數據），略過")
            continue
        seen[eid].add(sig)
        per_ep[eid].append(entry)
        imported += 1
    for eid, rows in per_ep.items():
        store.write_json(eid, "metrics.json", rows)
    return {"imported": imported, "skipped": skipped}


# ---------- YouTube ----------

_CB_PAGE = """<!doctype html><meta charset="utf-8"><title>內容工廠・Google 登入</title>
<body style="font-family:system-ui,sans-serif;padding:40px;text-align:center">
<h2>{title}</h2><p>{msg}</p><p style="color:#888">這個視窗會自動關閉。</p>
<script>try{{window.opener&&window.opener.postMessage({{type:"youtube-login",ok:{ok}}},"*")}}catch(e){{}}
setTimeout(()=>window.close(),{delay});</script></body>"""


@app.get("/api/youtube/status")
def youtube_status():
    return youtube.status()


@app.get("/api/youtube/clients")
def youtube_clients():
    return youtube.find_client_files()


@app.get("/api/youtube/login")
def youtube_login(request: Request):
    try:
        url = youtube.begin_login(request.url.port or 8770)
    except youtube.YouTubeError as e:
        return HTMLResponse(_CB_PAGE.format(title="無法開始登入", msg=html.escape(str(e)), ok="false", delay=15000), 400)
    return RedirectResponse(url)


@app.get("/api/youtube/callback")
def youtube_callback(state: str = "", code: str = "", error: str = ""):
    if error:
        return HTMLResponse(_CB_PAGE.format(title="登入已取消", msg=html.escape(error), ok="false", delay=4000))
    try:
        tok = youtube.finish_login(state, code)
    except youtube.YouTubeError as e:
        return HTMLResponse(_CB_PAGE.format(title="登入失敗", msg=html.escape(str(e)), ok="false", delay=15000), 400)
    ch = (tok.get("channel") or {}).get("title") or "（此帳號尚未建立 YouTube 頻道）"
    return HTMLResponse(_CB_PAGE.format(title="登入成功", msg="頻道：" + html.escape(ch), ok="true", delay=1500))


@app.post("/api/youtube/logout")
def youtube_logout():
    youtube.logout()
    return youtube.status()


@app.post("/api/episodes/{eid}/youtube")
def youtube_upload(eid: str):
    ep = _ep(eid)
    if ep["status"] != "done":
        raise HTTPException(409, "成片核准後才能上傳")
    if (ep.get("youtube") or {}).get("status") in ("queued", "uploading"):
        raise HTTPException(409, "這一集已在上傳中")
    blocked = youtube.upload_blocked_reason(ep)
    if blocked:
        raise HTTPException(409, blocked)
    if not youtube.status()["logged_in"]:
        raise HTTPException(401, "還沒登入 Google 帳號")
    store.update_episode(eid, youtube={"status": "queued", "progress": 0.0})
    pipeline.enqueue("youtube_upload", eid)
    return store.get_episode(eid)


# ---------- files & SPA ----------

_FILES_ROOTS = ("episodes", "music", "sfx", "stock", "tmp")  # settings.json / youtube token / cost stay private


def _episode_id_from_path(rel: Path) -> str:
    """`episodes/<id>/...` -> `<id>`; anything else -> ""."""
    parts = rel.parts
    return parts[1] if len(parts) >= 3 and parts[0] == "episodes" else ""


@app.get("/files/{path:path}")
def files(path: str):
    p = (store.DATA / path).resolve()
    root = store.DATA.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404)
    rel = p.relative_to(root)
    if rel.parts[0] not in _FILES_ROOTS:
        raise HTTPException(404)
    # A per-episode file inherits that episode's visibility: an episode hidden by the NSFW switch
    # must not be reachable by knowing its path. Checking only the top-level folder let anyone
    # fetch /files/episodes/<id>/brief.json for a restricted episode.
    eid = _episode_id_from_path(rel)
    if eid and not store.visible_episode(eid):
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


class _RevalidatedStatic(StaticFiles):
    # 沒有 Cache-Control 時瀏覽器會啟發式快取 ES module，舊版 import 會讓 lib.js 載成兩份、state.META 變 null。
    # no-cache 仍可用 ETag 回 304，只是每次都先問伺服器。
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", _RevalidatedStatic(directory=STATIC), name="static")
