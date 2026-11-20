"""Content Factory web app (FastAPI)."""
from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import llm, media, pipeline, prompts, store

app = FastAPI(title="內容工廠")
STATIC = store.ROOT / "static"
store.DATA.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
def _startup() -> None:
    pipeline.start_worker()
    for ep in store.list_episodes():  # resume work interrupted by a restart
        if ep["status"] in ("queued", "running"):
            store.log(ep["id"], "伺服器重啟，重新排入佇列")
            pipeline.enqueue("episode", ep["id"])


def _ep(eid: str) -> dict:
    try:
        ep = store.get_episode(eid)
    except ValueError:
        ep = None
    if not ep:
        raise HTTPException(404, "找不到這一集")
    return ep


# ---------- meta ----------

@app.get("/api/meta")
def meta():
    return {"stages": pipeline.STAGES, "stage_label": pipeline.STAGE_LABEL, "wait_label": pipeline.WAIT_LABEL,
            "styles": prompts.STYLES, "critics": {k: v[0] for k, v in prompts.CRITICS.items()}}


@app.get("/api/health")
def health(llm_check: bool = False):
    out = {"tts": media.tts_health(), "worker": pipeline.busy(), "provider": store.get_settings()["llm"]["provider"]}
    if llm_check:
        out["llm"] = llm.health()
    return out


@app.get("/api/settings")
def get_settings():
    return store.get_settings()


@app.put("/api/settings")
def put_settings(s: dict = Body(...)):
    return store.save_settings(s)


@app.get("/api/channel")
def get_channel():
    return store.get_channel()


@app.put("/api/channel")
def put_channel(c: dict = Body(...)):
    return store.save_channel(c)


@app.get("/api/preferences")
def get_prefs():
    return store.get_prefs()


@app.put("/api/preferences")
def put_prefs(p: list = Body(...)):
    return store.save_prefs(p)


# ---------- radar ----------

@app.get("/api/radar")
def radar():
    return store.get_radar()


@app.post("/api/radar/scan")
def radar_scan(body: dict = Body(...)):
    seeds = (body.get("seeds") or "").strip()
    if not seeds:
        raise HTTPException(400, "請貼上線索（連結、熱門話題或筆記）")
    pipeline.enqueue("radar", seeds)
    return {"ok": True}


@app.delete("/api/radar/{idx}")
def radar_delete(idx: int):
    items = store.get_radar()
    if 0 <= idx < len(items):
        items.pop(idx)
        store.save_radar(items)
    return items


# ---------- episodes ----------

@app.get("/api/episodes")
def episodes():
    return store.list_episodes()


@app.post("/api/episodes")
def create_episode(body: dict = Body(...)):
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "請輸入題目")
    fmt = body.get("format") if body.get("format") in ("long", "short") else "short"
    urls = [u.strip() for u in (body.get("source_urls") or []) if u.strip().startswith("http")]
    ep = store.new_episode(topic, fmt, body.get("notes", ""), urls)
    pipeline.enqueue("episode", ep["id"])
    return ep


@app.get("/api/episodes/{eid}")
def episode(eid: str):
    ep = _ep(eid)
    files = {}
    for name in ("brief.json", "script.json", "critique.json", "package.json", "output/verify.json"):
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
    import shutil
    shutil.rmtree(store.ep_dir(eid))
    return {"ok": True}


def _need_wait(ep: dict, what: str) -> None:
    if ep["status"] != "waiting" or ep["waiting_for"] != what:
        raise HTTPException(409, f"這一集目前不是在等「{pipeline.WAIT_LABEL[what]}」")


@app.post("/api/episodes/{eid}/direction")
def direction(eid: str, body: dict = Body(...)):
    _need_wait(_ep(eid), "direction")
    pipeline.choose_direction(eid, body["id"], body.get("notes", ""))
    return {"ok": True}


@app.post("/api/episodes/{eid}/script")
def script(eid: str, body: dict = Body(...)):
    _need_wait(_ep(eid), "script")
    pipeline.script_decision(eid, bool(body.get("approve")), body.get("feedback", ""), body.get("script"))
    return {"ok": True}


@app.post("/api/episodes/{eid}/package")
def package(eid: str, body: dict = Body(...)):
    _need_wait(_ep(eid), "package")
    pipeline.package_choice(eid, int(body.get("title", 0)), body.get("custom_title", ""), int(body.get("thumb", 0)),
                            body.get("schedule", ""))
    return {"ok": True}


@app.post("/api/episodes/{eid}/approve")
def approve(eid: str):
    _need_wait(_ep(eid), "approval")
    pipeline.approve(eid)
    return {"ok": True}


@app.post("/api/episodes/{eid}/reject")
def reject(eid: str, body: dict = Body(...)):
    ep = _ep(eid)
    if ep["status"] != "waiting":
        raise HTTPException(409, "只有在等你決定時才能退件")
    back = body.get("back_to")
    if back not in pipeline.REJECT_TO:
        raise HTTPException(400, "退回階段不正確")
    if not (body.get("reason") or "").strip():
        raise HTTPException(400, "請留一句退件理由，系統會記下來")
    pipeline.reject(eid, back, body["reason"])
    return {"ok": True}


@app.post("/api/episodes/{eid}/retry")
def retry(eid: str):
    ep = _ep(eid)
    if ep["status"] != "error":
        raise HTTPException(409, "只有出錯的集數可以重試")
    store.update_episode(eid, status="queued", error=None)
    pipeline.enqueue("episode", eid)
    return {"ok": True}


@app.post("/api/episodes/{eid}/metrics")
def add_metrics(eid: str, body: dict = Body(...)):
    _ep(eid)
    m = store.read_json(eid, "metrics.json", [])
    m.append({k: body.get(k) for k in ("platform", "date", "views", "watch_time", "followers", "note")})
    store.write_json(eid, "metrics.json", m)
    return m


# ---------- files ----------

@app.get("/files/{path:path}")
def files(path: str):
    p = (store.DATA / path).resolve()
    if store.DATA.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
