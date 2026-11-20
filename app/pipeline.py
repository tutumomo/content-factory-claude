"""SOP stages and a single background worker. Agents do the work; users decide at the gates."""
from __future__ import annotations

import html
import json
import queue
import re
import shutil
import threading
import traceback
from pathlib import Path

import httpx

from . import llm, media, prompts, render, store

STAGES = ["sources", "brief", "script", "critique", "assemble", "package", "review", "approved"]
STAGE_LABEL = {
    "sources": "蒐集資料", "brief": "方向簡報", "script": "寫講稿", "critique": "多模型互審",
    "assemble": "配音／畫面／字幕", "package": "標題／縮圖／貼文", "review": "成片審核", "approved": "已核准",
}
WAIT_LABEL = {"direction": "挑方向", "script": "看講稿", "package": "挑標題與縮圖", "approval": "看成片並核准"}

_q: "queue.Queue[tuple]" = queue.Queue()
_current: dict = {}


def enqueue(kind: str, *args) -> None:
    _q.put((kind, args))


def busy() -> dict:
    return {"current": dict(_current), "queued": _q.qsize()}


def _worker() -> None:
    while True:
        kind, args = _q.get()
        _current.clear()
        _current.update({"kind": kind, "args": list(args)})
        try:
            if kind == "episode":
                run_episode(*args)
            elif kind == "radar":
                run_radar(*args)
        except Exception as e:  # never kill the worker
            if kind == "episode":
                store.update_episode(args[0], status="error", error=f"{type(e).__name__}: {e}")
                store.log(args[0], "錯誤：" + traceback.format_exc()[-800:])
        finally:
            _current.clear()
            _q.task_done()


def start_worker() -> None:
    threading.Thread(target=_worker, daemon=True, name="cf-worker").start()


# ---------- helpers ----------

def fetch_text(url: str, limit: int = 6000) -> str:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 content-factory"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        return f"（抓取失敗：{e}）"
    t = r.text
    t = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", t)
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = html.unescape(re.sub(r"\s+", " ", t)).strip()
    return (f"標題：{html.unescape(title.group(1).strip())}\n" if title else "") + t[:limit]


def sources_text(eid: str) -> str:
    p = store.ep_dir(eid) / "sources.md"
    return p.read_text("utf-8")[:20000] if p.exists() else ""


def size_for(ep: dict) -> tuple[int, int]:
    return (1080, 1920) if ep["format"] == "short" else (1920, 1080)


def set_stage(eid: str, stage: str) -> None:
    store.update_episode(eid, stage=stage, status="running", waiting_for=None, error=None)
    store.log(eid, f"開始：{STAGE_LABEL[stage]}")


def wait(eid: str, what: str) -> None:
    store.update_episode(eid, status="waiting", waiting_for=what)
    store.log(eid, f"等待使用者：{WAIT_LABEL[what]}")


# ---------- stages ----------

def st_sources(ep: dict) -> bool:
    eid = ep["id"]
    parts = [f"# 題目\n{ep['topic']}\n", f"# 使用者筆記\n{ep.get('notes') or '（無）'}\n"]
    for u in ep.get("source_urls", []):
        store.log(eid, f"抓取 {u}")
        parts.append(f"## 來源：{u}\n{fetch_text(u)}\n")
    store.write_text(eid, "sources.md", "\n".join(parts))
    n_ok = sum(1 for p in parts[2:] if "抓取失敗" not in p)
    store.update_episode(eid, checks={**ep.get("checks", {}), "sources": {"ok": True, "value": f"{n_ok}/{len(ep.get('source_urls', []))} 個來源可讀"}})
    return True


def st_brief(ep: dict) -> bool:
    eid = ep["id"]
    if ep.get("direction"):
        return True
    sys, pr = prompts.brief(ep, sources_text(eid))
    data = llm.complete_json("brief", sys, pr)
    store.write_json(eid, "brief.json", data)
    wait(eid, "direction")
    return False


def st_script(ep: dict) -> bool:
    eid = ep["id"]
    sys, pr = prompts.script(ep, ep["direction"], sources_text(eid))
    scr = llm.complete_json("script", sys, pr)
    _validate_script(scr)
    store.write_json(eid, "script.json", scr)
    store.log(eid, f"講稿 {len(scr['scenes'])} 個畫面，{sum(len(s['narration']) for s in scr['scenes'])} 字")
    return True


def _validate_script(scr: dict) -> None:
    if not isinstance(scr, dict) or not scr.get("scenes"):
        raise llm.LLMError("講稿缺少 scenes")
    for s in scr["scenes"]:
        s["narration"] = (s.get("narration") or "").strip()
        s.setdefault("headline", "")
        s["bullets"] = [b for b in (s.get("bullets") or []) if isinstance(b, str)][:3]
        if s.get("style") not in prompts.STYLES:
            s["style"] = "clean"
    scr["scenes"] = [s for s in scr["scenes"] if s["narration"]]
    if not scr["scenes"]:
        raise llm.LLMError("講稿沒有可念的內容")


def st_critique(ep: dict) -> bool:
    eid = ep["id"]
    cfg = store.get_settings()["pipeline"]
    rounds = []
    scr = store.read_json(eid, "script.json")
    src = sources_text(eid)
    if ep.get("revise_feedback"):
        store.log(eid, "依使用者意見修稿")
        sys, pr = prompts.revise(ep, scr, {}, ep["revise_feedback"])
        scr = llm.complete_json("revise", sys, pr)
        _validate_script(scr)
        store.write_json(eid, "script.json", scr)
        store.update_episode(eid, revise_feedback=None)
    for rnd in range(1, cfg["critique_max_rounds"] + 1):
        reviews = {}
        for role in prompts.CRITICS:
            sys, pr = prompts.critique(role, ep, scr, src)
            r = llm.complete_json(f"critique_{role}", sys, pr)
            r["score"] = int(r.get("score") or 0)
            reviews[role] = r
            store.log(eid, f"第 {rnd} 輪 {prompts.CRITICS[role][0]}：{r['score']} 分")
        rounds.append({"round": rnd, "reviews": reviews})
        store.write_json(eid, "critique.json", {"rounds": rounds})
        if all(r["score"] >= cfg["critique_threshold"] for r in reviews.values()):
            break
        if rnd == cfg["critique_max_rounds"]:
            store.log(eid, "已達修稿上限，交給使用者決定")
            break
        sys, pr = prompts.revise(ep, scr, reviews)
        scr = llm.complete_json("revise", sys, pr)
        _validate_script(scr)
        store.write_json(eid, "script.json", scr)
    last = rounds[-1]["reviews"]
    passed = all(r["score"] >= cfg["critique_threshold"] for r in last.values())
    ep = store.get_episode(eid)
    ep["checks"]["critique"] = {"ok": passed, "value": "、".join(f"{prompts.CRITICS[k][0]} {v['score']}" for k, v in last.items())}
    store.save_episode(ep)
    if cfg["review_script"] or not passed:
        if not ep.get("script_approved"):
            wait(eid, "script")
            return False
    return True


def st_assemble(ep: dict) -> bool:
    eid = ep["id"]
    d = store.ep_dir(eid)
    assets, out = d / "assets", d / "output"
    shutil.rmtree(assets, ignore_errors=True)
    assets.mkdir(parents=True)
    out.mkdir(exist_ok=True)
    scr = store.read_json(eid, "script.json")
    size = size_for(ep)
    vertical = size[1] > size[0]
    channel = store.get_channel()["name"]
    h = media.tts_health()
    if not h["ok"]:
        raise media.MediaError(h["detail"])
    clips, all_cues, t0, n = [], [], 0.0, len(scr["scenes"])
    for i, sc in enumerate(scr["scenes"]):
        store.log(eid, f"畫面 {i + 1}/{n}：配音中")
        parts = []
        for j, chunk in enumerate(media.split_for_tts(sc["narration"])):
            parts.append(media.tts(chunk, assets / f"s{i:02d}_{j:02d}.wav"))
        wav = media.concat_wavs(parts, assets / f"s{i:02d}.wav") if len(parts) > 1 else parts[0].rename(assets / f"s{i:02d}.wav")
        dur = media.wav_duration(wav)
        words = media.align(wav, sc["narration"])
        cues = media.cues_for_scene(sc["narration"], words, dur, 12 if vertical else 22)
        sc["_aligned"] = bool(words)
        all_cues += [{**c, "start": c["start"] + t0, "end": c["end"] + t0} for c in cues]
        img = render.slide(sc, size, assets / f"s{i:02d}.jpg", channel, i, n)
        clip_dur = media.scene_clip(img, wav, assets / f"s{i:02d}.mp4")
        clips.append(assets / f"s{i:02d}.mp4")
        t0 += clip_dur
        # per-step check: narration length vs. text length (catches truncated or runaway TTS)
        rate = len(re.sub(r"\s", "", sc["narration"])) / max(dur, 0.1)
        if not 2.0 <= rate <= 9.0:
            store.log(eid, f"⚠ 畫面 {i + 1} 語速異常：{rate:.1f} 字/秒（可能漏念或拖長）")
            sc["_rate_warning"] = round(rate, 1)
    store.write_json(eid, "assets/scenes.json", scr)
    ass = media.write_ass(all_cues, size, assets / "subs.ass")
    media.write_srt(all_cues, out / "subtitles.srt")
    store.log(eid, "合成成片、燒字幕、音量正規化")
    final = media.concat_and_burn(clips, ass, out / "final.mp4", assets)
    v = media.verify_video(final, size, t0, assets)
    aligned = sum(1 for s in scr["scenes"] if s.get("_aligned"))
    rate_warn = [i + 1 for i, s in enumerate(scr["scenes"]) if s.get("_rate_warning")]
    v["checks"]["字幕對齊"] = {"ok": aligned == n, "value": f"{aligned}/{n} 個畫面用強制對齊，其餘按字數估算"}
    v["checks"]["語速"] = {"ok": not rate_warn, "value": "正常" if not rate_warn else f"畫面 {rate_warn} 異常"}
    store.write_json(eid, "output/verify.json", v)
    ep = store.get_episode(eid)
    ep["checks"]["assemble"] = {"ok": all(c["ok"] for c in v["checks"].values()), "value": f"{v['duration']:.1f} 秒"}
    store.save_episode(ep)
    store.log(eid, "成片完成：" + "；".join(f"{k} {'✓' if c['ok'] else '✗'} {c['value']}" for k, c in v["checks"].items()))
    return True


def st_package(ep: dict) -> bool:
    eid = ep["id"]
    if ep.get("package_choice"):
        return True
    cfg = store.get_settings()["pipeline"]
    scr = store.read_json(eid, "script.json")
    sys, pr = prompts.package(ep, scr, cfg["title_count"], cfg["thumbnail_count"])
    pk = llm.complete_json("package", sys, pr)
    d = store.ep_dir(eid)
    shutil.rmtree(d / "thumbs", ignore_errors=True)
    shutil.rmtree(d / "carousel", ignore_errors=True)
    thumbs = []
    for i, t in enumerate(pk.get("thumbnails", [])[: cfg["thumbnail_count"]]):
        p = render.thumbnail(t.get("main", ""), t.get("sub", ""), t.get("theme", "dark"), i, d / "thumbs" / f"thumb_{i}.jpg",
                             vertical=ep["format"] == "short")
        thumbs.append({**t, "file": str(p.relative_to(store.DATA))})
    pk["thumbnails"] = thumbs
    cards, car = [], pk.get("carousel", [])
    for i, c in enumerate(car):
        p = render.carousel_card(c.get("heading", ""), c.get("body", ""), i, len(car), d / "carousel" / f"card_{i}.jpg",
                                 store.get_channel()["name"])
        cards.append({**c, "file": str(p.relative_to(store.DATA))})
    pk["carousel"] = cards
    store.write_json(eid, "package.json", pk)
    wait(eid, "package")
    return False


def st_review(ep: dict) -> bool:
    if ep.get("approved"):
        return True
    wait(ep["id"], "approval")
    return False


def st_approved(ep: dict) -> bool:
    eid = ep["id"]
    d = store.ep_dir(eid)
    pub = d / "publish"
    shutil.rmtree(pub, ignore_errors=True)
    pub.mkdir()
    pk = store.read_json(eid, "package.json")
    ch = ep["package_choice"]
    shutil.copy(d / "output" / "final.mp4", pub / "video.mp4")
    shutil.copy(d / "output" / "subtitles.srt", pub / "subtitles.srt")
    shutil.copy(store.DATA / pk["thumbnails"][ch["thumb"]]["file"], pub / "thumbnail.jpg")
    for c in pk.get("carousel", []):
        shutil.copy(store.DATA / c["file"], pub / Path(c["file"]).name)
    meta = {"title": ch["title"], "description": pk.get("description", ""), "hashtags": pk.get("hashtags", []),
            "fb_post": pk.get("fb_post", ""), "schedule": ep.get("schedule"), "platforms": store.get_channel()["platforms"]}
    (pub / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    (pub / "description.txt").write_text(f"{ch['title']}\n\n{pk.get('description', '')}\n\n{' '.join(pk.get('hashtags', []))}", "utf-8")
    store.update_episode(eid, status="done", waiting_for=None)
    store.log(eid, f"已核准，發布包輸出到 {pub}")
    return True


RUNNERS = {"sources": st_sources, "brief": st_brief, "script": st_script, "critique": st_critique,
           "assemble": st_assemble, "package": st_package, "review": st_review, "approved": st_approved}


def run_episode(eid: str) -> None:
    ep = store.get_episode(eid)
    stage = ep["stage"]
    while True:
        set_stage(eid, stage)
        ok = RUNNERS[stage](store.get_episode(eid))
        if not ok:
            return
        i = STAGES.index(stage)
        if i + 1 >= len(STAGES):
            return
        stage = STAGES[i + 1]


def run_radar(seeds: str) -> None:
    urls = re.findall(r"https?://\S+", seeds)
    text = seeds + "\n\n" + "\n\n".join(f"## {u}\n{fetch_text(u, 3000)}" for u in urls[:8])
    sys, pr = prompts.radar(text)
    data = llm.complete_json("radar", sys, pr)
    items = store.get_radar()
    import time as _t
    for t in data.get("topics", []):
        t["found"] = _t.time()
        items.insert(0, t)
    store.save_radar(items[:60])


# ---------- user decisions ----------

def choose_direction(eid: str, direction_id: str, notes: str) -> None:
    brief = store.read_json(eid, "brief.json")
    d = next(x for x in brief["directions"] if x["id"] == direction_id)
    store.update_episode(eid, direction=d, direction_notes=notes, stage="script")
    store.log(eid, f"使用者選方向 {direction_id}")
    enqueue("episode", eid)


def script_decision(eid: str, approve: bool, feedback: str, edited: dict | None) -> None:
    if edited:
        _validate_script(edited)
        store.write_json(eid, "script.json", edited)
        store.log(eid, "使用者直接修改講稿")
    if approve:
        store.update_episode(eid, script_approved=True, stage="assemble")
        store.log(eid, "使用者核准講稿")
    else:
        _remember(eid, "講稿", feedback)
        store.update_episode(eid, script_approved=False, stage="critique", revise_feedback=feedback)
    enqueue("episode", eid)


def package_choice(eid: str, title_idx: int, custom_title: str, thumb_idx: int, schedule: str) -> None:
    pk = store.read_json(eid, "package.json")
    title = custom_title.strip() or pk["titles"][title_idx]["text"]
    store.update_episode(eid, package_choice={"title": title, "thumb": thumb_idx}, schedule=schedule or None, stage="review")
    store.log(eid, f"使用者選標題「{title}」、縮圖 {thumb_idx + 1}")
    enqueue("episode", eid)


def approve(eid: str) -> None:
    store.update_episode(eid, approved=True, stage="approved")
    enqueue("episode", eid)


REJECT_TO = {"brief": "brief", "script": "script", "assemble": "assemble", "package": "package"}


def reject(eid: str, back_to: str, reason: str) -> None:
    _remember(eid, {"brief": "方向", "script": "講稿", "assemble": "畫面與配音", "package": "標題與縮圖"}[back_to], reason)
    reset = {"approved": False, "stage": REJECT_TO[back_to]}
    if back_to == "brief":
        reset.update(direction=None, script_approved=False, package_choice=None)
    elif back_to == "script":
        reset.update(script_approved=False, package_choice=None, direction_notes=(store.get_episode(eid).get("direction_notes") or "") + f"\n退件意見：{reason}")
    elif back_to == "package":
        reset.update(package_choice=None)
    store.update_episode(eid, **reset)
    store.log(eid, f"退件回「{STAGE_LABEL[back_to]}」：{reason}")
    enqueue("episode", eid)


def _remember(eid: str, stage: str, reason: str) -> None:
    """Principle 3: turn every complaint into a reusable rule."""
    if not reason.strip():
        return
    try:
        sys, pr = prompts.pref_rule(stage, reason)
        r = llm.complete_json("pref_rule", sys, pr)
        store.add_pref(r.get("category") or stage, r.get("rule") or reason)
        store.log(eid, f"寫回品味紀錄：{r.get('rule') or reason}")
    except llm.LLMError:
        store.add_pref(stage, reason)
