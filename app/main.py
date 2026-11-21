"""Content Factory web app (FastAPI)."""
from __future__ import annotations

import csv
import io
import shutil
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
    cur = store.get_insights_summary()  # a restart in the middle of an analysis leaves this flag set
    if cur.get("analyzing"):
        store.save_insights_summary({**cur, "analyzing": False, "error": "上次分析被伺服器重啟中斷，請重新分析"})
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


# ---------- meta & config ----------

@app.get("/api/meta")
def meta():
    return {
        "stages": pipeline.STAGES,
        "stage_label": pipeline.STAGE_LABEL,
        "wait_label": pipeline.WAIT_LABEL,
        "styles": prompts.STYLES,
        "critics": {k: v[0] for k, v in prompts.CRITICS.items()},
        "pref_cats": store.PREF_CATS,
        "style_categories": store.STYLE_CATEGORIES,
    }


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

@app.get("/api/styles")
def list_styles():
    return store.get_styles()


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


@app.post("/api/episodes")
def create_episode(body: dict = Body(...)):
    topic = (body.get("topic") or "").strip()
    if not topic:
        raise HTTPException(400, "請輸入題目")
    fmt = body.get("format") if body.get("format") in ("long", "short") else "short"
    urls = [u.strip() for u in (body.get("source_urls") or []) if str(u).strip().startswith("http")]
    ep = store.new_episode(
        topic,
        fmt,
        body.get("notes", ""),
        urls,
        style_id=body.get("style_id") or None,
        idea_id=body.get("idea_id") or None,
    )
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
    shutil.rmtree(store.ep_dir(eid))
    return {"ok": True}


@app.patch("/api/episodes/{eid}/schedule")
def set_schedule(eid: str, body: dict = Body(...)):
    _ep(eid)
    try:
        return store.update_schedule(eid, body.get("schedule"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


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
    pipeline.package_choice(
        eid,
        int(body.get("title", 0)),
        body.get("custom_title", ""),
        int(body.get("thumb", 0)),
        body.get("schedule", ""),
    )
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


# ---------- files & SPA ----------

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
