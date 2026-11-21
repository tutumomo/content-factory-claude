"""SOP stages and a single background worker. Agents do the work; users decide at the gates."""
from __future__ import annotations

import html
import json
import queue
import re
import shutil
import threading
import time
import traceback
from pathlib import Path

import httpx

from . import comfy, cost, llm, media, music, prompts, render, sfx, stock, store, video

STAGES = ["sources", "brief", "script", "critique", "storyboard", "assemble", "package", "review", "approved"]
STAGE_LABEL = {
    "sources": "蒐集資料", "brief": "方向簡報", "script": "寫講稿", "critique": "多模型互審",
    "storyboard": "分鏡確認", "assemble": "配音／畫面／字幕", "package": "標題／縮圖／貼文",
    "review": "成片審核", "approved": "已核准",
}
WAIT_LABEL = {"direction": "挑方向", "script": "看講稿", "storyboard": "看分鏡", "cost": "核准花費",
              "package": "挑標題與縮圖", "approval": "看成片並核准"}

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
            elif kind == "insights_analyze":
                run_insights_analyze()
            elif kind == "youtube_upload":
                from . import youtube
                youtube.upload_episode(*args)
        except Exception as e:  # never kill the worker
            if kind == "episode":
                store.update_episode(args[0], status="error", error=f"{type(e).__name__}: {e}")
                store.log(args[0], "錯誤：" + traceback.format_exc()[-800:])
            elif kind == "insights_analyze":
                cur = store.get_insights_summary()
                store.save_insights_summary({**cur, "analyzing": False, "error": f"{type(e).__name__}: {e}"})
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
        s["visual"] = str(s.get("visual") or "").strip()
        s["stock_query"] = str(s.get("stock_query") or "").strip()[:80]
        s["emotion"] = str(s.get("emotion") or "").strip()[:8]
        s["sfx"] = sfx.normalize(str(s.get("sfx") or ""))
    m = scr.get("music")
    if isinstance(m, dict):
        scr["music"] = str(m.get("style") or "").strip()
    elif m is not None:
        scr["music"] = str(m).strip()
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


def _render_ffmpeg(clips: list[Path], ass: Path, out: Path, assets: Path, bgm: Path | None,
                   t0: float, mc: dict) -> Path:
    """Static clips + burned subtitles; the music bed is mixed in after normalising, if any."""
    if bgm:
        plain = media.concat_and_burn(clips, ass, assets / "nosub.mp4", assets, loudnorm=False)
        return music.mix(plain, bgm, out, t0, gain_db=float(mc.get("gain_db", -20)),
                         duck=bool(mc.get("duck", True)))
    return media.concat_and_burn(clips, ass, out, assets)


def _render_remotion(eid: str, clips: list[Path], scenes: list[dict], durs: list[float],
                     cues: list[dict], size: tuple[int, int], assets: Path, out: Path,
                     bgm: Path | None, t0: float, mc: dict, channel: str,
                     imgs: list[str] | None = None) -> Path:
    """Animated composition: soundtrack is prepared first, the React render supplies the picture."""
    chk = video.available()
    if not chk["ok"]:
        raise video.VideoError(chk["detail"])
    store.log(eid, "Remotion：準備音軌")
    joined = media.join_clips(clips, assets / "joined_nosub.mp4", assets)
    if bgm:
        mixed = music.mix(joined, bgm, assets / "mixed.mp4", t0, gain_db=float(mc.get("gain_db", -20)),
                          duck=bool(mc.get("duck", True)))
    else:
        mixed = media.loudnorm_copy(joined, assets / "mixed.mp4")
    track = media.extract_audio(mixed, assets / "track.m4a")
    store.log(eid, f"Remotion：渲染 {len(scenes)} 個畫面的動畫")
    props = video.build_props(scenes, cues, size, durs, channel=channel, imgs=imgs)
    vid = video.render(assets, props, assets / "remotion.mp4")
    return media.mux_audio(vid, track, out, t0)


def st_storyboard(ep: dict) -> bool:
    """Cheap preview of every scene before paying for TTS and renders."""
    eid = ep["id"]
    cfg = store.get_settings()["pipeline"]
    if not cfg.get("review_storyboard", True) or ep.get("storyboard_approved"):
        return True
    scr = store.read_json(eid, "script.json")
    d = store.ep_dir(eid)
    sb = d / "output/storyboard"
    sb.mkdir(parents=True, exist_ok=True)
    size = size_for(ep)
    thumb = (540, 960) if ep["format"] == "short" else (960, 540)
    channel = store.get_channel()["name"]
    total = len(scr["scenes"])
    items, est_total = [], 0.0
    for i, sc in enumerate(scr["scenes"]):
        img = sb / f"sb{i:02d}.jpg"
        try:
            render.slide(sc, thumb, img, channel, i, total)
        except Exception as e:  # a missing thumbnail must not block the gate
            store.log(eid, f"分鏡縮圖 {i + 1} 失敗：{e}")
        chars = len(re.sub(r"\s", "", sc["narration"]))
        secs = round(chars / 4.6 + 0.7, 1)
        est_total += secs
        items.append({"index": i, "headline": sc.get("headline", ""), "narration": sc["narration"],
                      "est_seconds": secs, "sfx": sc.get("sfx", ""), "visual": sc.get("visual", ""),
                      "thumb": f"storyboard/sb{i:02d}.jpg" if img.exists() else ""})
    store.write_json(eid, "output/storyboard.json",
                     {"scenes": items, "est_total": round(est_total, 1), "size": list(size),
                      "format": ep["format"], "created": time.time()})
    ep = store.get_episode(eid)
    ep["checks"]["storyboard"] = {"ok": True, "value": f"{total} 個畫面，預估 {est_total:.0f} 秒"}
    store.save_episode(ep)
    store.log(eid, f"分鏡就緒：{total} 個畫面，預估 {est_total:.0f} 秒")
    wait(eid, "storyboard")
    return False


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
    rc = store.get_settings()["render"]
    engine = (rc.get("engine") or "ffmpeg").lower()
    h = media.tts_health()
    if not h["ok"]:
        raise media.MediaError(h["detail"])

    # 0) paid cloud music budget gate (checked before the expensive TTS pass)
    mc = store.get_settings()["music"]
    if mc.get("enabled", True) and music.provider() == "lyria":
        usd = cost.price((mc.get("lyria_model") or "lyria-3-clip-preview").strip())
        dec = cost.decide(usd)
        if dec == "deny":
            store.log(eid, f"本月雲端花費已達上限（已用 ${cost.month_sum():.2f}），本次不加音樂")
            mc = {**mc, "enabled": False}
        elif dec == "need_approval" and not cost.episode_approved(eid):
            gate = float((store.get_settings().get("cost") or {}).get("per_call_approval_usd") or 0.5)
            store.log(eid, f"Lyria 每首 ${usd:.2f} 超過核准門檻 ${gate:.2f}，等你核准")
            wait(eid, "cost")
            return False
        else:
            cost.consume(eid)

    # 1) scene backgrounds (stock footage, ComfyUI, or Pillow cards)
    scenes = scr["scenes"]
    vis = store.get_settings()["visuals"]
    src = (vis.get("source") or "slides").lower()
    bgs: dict[int, Path] = {}
    clip_bgs: dict[int, Path] = {}
    stock_sources: list[dict] = []
    if src in ("stock", "mix"):
        st = stock.status()
        if st["providers"]:
            store.log(eid, f"找實拍素材：{len(scenes)} 段（{'、'.join(st['providers'])}）")
            for i, sc in enumerate(scenes):
                q = stock.scene_query(sc)
                got = stock.fetch(q, vertical)
                if got:
                    clip_bgs[i] = got["path"]
                    stock_sources.append(got)
                else:
                    store.log(eid, f"畫面 {i + 1} 找不到素材（{q or '無關鍵詞'}），改用字卡或生圖")
            store.log(eid, f"實拍素材 {len(clip_bgs)}/{len(scenes)} 段")
            stock.save_sources(assets, stock_sources)
        else:
            store.log(eid, "素材來源沒有金鑰，改用字卡／生圖：" + st["detail"])
    if src in ("comfy", "mix"):
        ch = comfy.health()
        if ch["ok"]:
            todo = [i for i in range(len(scenes)) if i not in clip_bgs]
            store.log(eid, f"ComfyUI 生畫面：{len(todo)} 張（{vis.get('unet')}）")
            for i in todo:
                sc = scenes[i]
                desc = (sc.get("visual") or sc.get("headline") or "").strip()
                prompt = f"{desc}, {vis.get('style_hint')}, absolutely no text, no letters, no watermark"
                try:
                    bgs[i] = comfy.generate(prompt, size, assets / f"bg{i:02d}.jpg", seed=1000 + i)
                except comfy.ComfyError as e:
                    store.log(eid, f"畫面 {i + 1} 生圖失敗，改用字卡：{e}")
            if vis.get("free_after", True):
                comfy.free()
                store.log(eid, "已請 ComfyUI 釋放模型記憶體")
        else:
            store.log(eid, f"{ch['detail']}；改用字卡畫面")

    # 2) narration, subtitles, per-scene clips
    sfxc = store.get_settings()["sfx"]
    sfx_on = bool(sfxc.get("enabled", True))
    sfx_gain = float(sfxc.get("gain_db", -16))
    per_emo = bool(store.get_settings()["tts"].get("per_scene_emotion"))
    clips, all_cues, t0, n = [], [], 0.0, len(scenes)
    durs: list[float] = []
    rm_imgs: list[str] = []
    used_sfx, missing_sfx = 0, set()
    for i, sc in enumerate(scenes):
        # Qwen3 的語氣指令會把聲音帶走（同一段文字換語氣聽起來像換人）；逐段情緒要使用者主動打開才套用
        emo = sc.get("emotion", "") if per_emo else ""
        store.log(eid, f"畫面 {i + 1}/{n}：配音中" + (f"（{emo}）" if emo else ""))
        parts = []
        for j, chunk in enumerate(media.split_for_tts(sc["narration"])):
            parts.append(media.tts(chunk, assets / f"s{i:02d}_{j:02d}.wav", emotion=emo))
        wav = media.concat_wavs(parts, assets / f"s{i:02d}.wav") if len(parts) > 1 else parts[0].rename(assets / f"s{i:02d}.wav")
        dur = media.wav_duration(wav)
        words = media.align(wav, sc["narration"])
        cues = media.cues_for_scene(sc["narration"], words, dur, 12 if vertical else 22)
        sc["_aligned"] = bool(words)
        all_cues += [{**c, "start": c["start"] + t0, "end": c["end"] + t0} for c in cues]
        img = assets / f"s{i:02d}.jpg"
        if i in clip_bgs:
            sc["_visual"] = "stock"
        elif i in bgs:
            render.scene_with_bg(sc, size, bgs[i], img, channel, i, n)
            sc["_visual"] = "comfy"
        else:
            render.slide(sc, size, img, channel, i, n)
            sc["_visual"] = "slide"
        if engine == "remotion":
            # the React composition draws the text itself, so it needs a text-free plate
            rm = assets / f"p{i:02d}.jpg"
            if i in clip_bgs:
                media.frame(clip_bgs[i], 1.0, rm)  # Remotion gets a still from the footage
            elif i in bgs:
                shutil.copy2(bgs[i], rm)
            else:
                render.plate(sc, size, rm, i)
            rm_imgs.append(rm.name)
        tag = (sc.get("sfx") or "").strip().lower()
        fx = sfx.pick(tag, f"{eid}-{i}") if (sfx_on and tag) else None
        if fx:
            used_sfx += 1
            sc["_sfx"] = fx.name
        elif tag:
            missing_sfx.add(tag)
            sc.pop("_sfx", None)
        if i in clip_bgs:
            clip_dur = media.scene_clip_video(clip_bgs[i], wav, assets / f"s{i:02d}.mp4", size,
                                              sfx=fx, sfx_gain=sfx_gain)
        else:
            clip_dur = media.scene_clip(img, wav, assets / f"s{i:02d}.mp4", sfx=fx, sfx_gain=sfx_gain)
        clips.append(assets / f"s{i:02d}.mp4")
        durs.append(clip_dur)
        t0 += clip_dur
        # per-step check: narration length vs. text length (catches truncated or runaway TTS)
        rate = len(re.sub(r"\s", "", sc["narration"])) / max(dur, 0.1)
        if not 2.0 <= rate <= 9.0:
            store.log(eid, f"⚠ 畫面 {i + 1} 語速異常：{rate:.1f} 字/秒（可能漏念或拖長）")
            sc["_rate_warning"] = round(rate, 1)
    store.write_json(eid, "assets/scenes.json", scr)
    if missing_sfx:
        store.log(eid, "音效庫沒有這些標籤，那些畫面只留旁白：" + "、".join(sorted(missing_sfx)))
    ass = media.write_ass(all_cues, size, assets / "subs.ass")
    media.write_srt(all_cues, out / "subtitles.srt")

    # 3) background music (YuE2 or Lyria, cached per provider/style/length)
    bgm, bgm_note = None, "已關閉"
    if mc.get("enabled", True):
        style = music.style_of(scr)
        music_engine = "Lyria 3" if music.provider() == "lyria" else "YuE2"
        store.log(eid, f"背景音樂：{music_engine} 生成 {t0:.0f} 秒（{style[:48]}）")
        try:
            bgm = music.generate(t0, style, eid=eid)
            bgm_note = f"{music.duration(bgm):.0f} 秒，{mc.get('gain_db', -20)} dB" + ("，自動閃避旁白" if mc.get("duck", True) else "")
            store.log(eid, f"背景音樂就緒：{bgm.name}")
        except music.MusicError as e:
            bgm_note = f"生成失敗，成片不加音樂：{e}"
            store.log(eid, bgm_note)

    store.log(eid, "合成成片、燒字幕、音量正規化")
    final_note = "ffmpeg"
    if engine == "remotion":
        try:
            final = _render_remotion(eid, clips, scr["scenes"], durs, all_cues, size, assets, out / "final.mp4",
                                     bgm, t0, mc, channel, rm_imgs)
            final_note = "Remotion"
            store.log(eid, "Remotion 渲染完成")
        except Exception as e:
            if not rc.get("fallback_ffmpeg", True):
                raise
            store.log(eid, f"Remotion 失敗，退回 ffmpeg：{e}")
            final = _render_ffmpeg(clips, ass, out / "final.mp4", assets, bgm, t0, mc)
    else:
        final = _render_ffmpeg(clips, ass, out / "final.mp4", assets, bgm, t0, mc)
    v = media.verify_video(final, size, t0, assets,
                           slideshow_risk_max=float(store.get_settings()["pipeline"].get("slideshow_risk_max", 0.7)))
    aligned = sum(1 for s in scr["scenes"] if s.get("_aligned"))
    rate_warn = [i + 1 for i, s in enumerate(scr["scenes"]) if s.get("_rate_warning")]
    v["checks"]["字幕對齊"] = {"ok": aligned == n, "value": f"{aligned}/{n} 個畫面用強制對齊，其餘按字數估算"}
    v["checks"]["語速"] = {"ok": not rate_warn, "value": "正常" if not rate_warn else f"畫面 {rate_warn} 異常"}
    parts = []
    if clip_bgs:
        parts.append(f"實拍素材 {len(clip_bgs)} 段")
    if bgs:
        parts.append(f"ComfyUI 生圖 {len(bgs)} 張")
    slides = n - len(clip_bgs) - len(bgs)
    if slides:
        parts.append(f"字卡 {slides} 張")
    v["checks"]["畫面來源"] = {"ok": True, "value": ("、".join(parts) or "字卡")}
    v["checks"]["音效"] = {"ok": True, "value": (f"{used_sfx}/{n} 個畫面有音效" if sfx_on else "已關閉")}
    v["checks"]["背景音樂"] = {"ok": bool(bgm) or not mc.get("enabled", True), "value": bgm_note}
    v["checks"]["成片引擎"] = {"ok": True, "value": "Remotion 動畫" if final_note == "Remotion" else "ffmpeg 字幕"}
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
    srcs_p = d / "assets" / "sources.json"
    if srcs_p.exists():
        try:
            rows = json.loads(srcs_p.read_text("utf-8"))
            if rows:
                pk["description"] = (pk.get("description") or "").rstrip() + "\n\n實拍素材來源：\n" + stock.credits(rows)
        except (ValueError, OSError):
            pass
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
    # short-form package: a 9:16 copy plus platform captions (upload is still manual)
    tags = [str(t).strip() for t in (pk.get("hashtags") or []) if str(t).strip()]
    tag_line = " ".join(tags[:6])
    caption = f"{ch['title']}\n\n{tag_line}".rstrip()
    shorts = pub / "shorts"
    shorts.mkdir(exist_ok=True)
    if ep["format"] == "short":
        shutil.copy(d / "output" / "final.mp4", shorts / "vertical_9x16.mp4")
    (shorts / "caption_tiktok.txt").write_text(caption[:2100], "utf-8")
    (shorts / "caption_instagram.txt").write_text(caption[:2100], "utf-8")
    meta["shorts"] = {"vertical": ep["format"] == "short", "caption_tiktok": caption[:2100],
                      "caption_instagram": caption[:2100]}
    (pub / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
    (pub / "description.txt").write_text(f"{ch['title']}\n\n{pk.get('description', '')}\n\n{' '.join(pk.get('hashtags', []))}", "utf-8")
    store.update_episode(eid, status="done", waiting_for=None)
    store.log(eid, f"已核准，發布包輸出到 {pub}")
    return True


RUNNERS = {"sources": st_sources, "brief": st_brief, "script": st_script, "critique": st_critique,
           "storyboard": st_storyboard,
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
    rng = store.get_settings()["pipeline"]
    lo, hi = rng["radar_min"], rng["radar_max"]
    sys, pr = prompts.radar(text, lo, hi)
    data = llm.complete_json("radar", sys, pr)
    items = store.get_radar()
    now = time.time()
    for t in reversed([t for t in data.get("topics", []) if isinstance(t, dict)][:hi]):  # keep model's ranking on top
        t["found"] = now
        t["kind"] = "radar"
        items.insert(0, t)
    store.save_radar(items)


def run_insights_analyze() -> None:
    eps = store.list_episodes()
    ep_payload = []
    for ep in eps:
        ms = store.read_json(ep["id"], "metrics.json", [])
        if not ms:
            continue
        style_card = store.get_style(ep.get("style_id"))
        ep_payload.append({
            "title": (ep.get("package_choice") or {}).get("title") or ep["topic"],
            "format": ep.get("format"),
            "direction": (ep.get("direction") or {}).get("angle", ""),
            "style": style_card["name"] if style_card else "",
            "metrics": ms,
        })
    if not ep_payload:
        cur = store.get_insights_summary()
        store.save_insights_summary({**cur, "analyzing": False, "error": "請先錄入至少一筆成效數據"})
        return
    active_rules = [p for p in store.get_prefs() if p.get("status", "active") == "active"]
    payload = {"episodes": ep_payload, "active_rules": [{"category": r["category"], "rule": r["rule"]} for r in active_rules]}
    sys, pr = prompts.analyze_insights(payload)
    res = llm.complete_json("analyze_insights", sys, pr)
    headline = str(res.get("headline") or "").strip()
    store.save_insights_summary({
        "headline": headline,
        "updated": time.time(),
        "analyzing": False,
        "error": None,
    })
    for sug in (res.get("suggestions") or [])[:4]:
        if not isinstance(sug, dict):
            continue
        rule = str(sug.get("rule") or "").strip()
        if not rule:
            continue
        cat = str(sug.get("category") or "").strip()
        if cat not in store.PREF_CATS:
            cat = "選題"
        evidence = str(sug.get("evidence") or "").strip()
        store.add_pref(cat, rule, status="proposed", source="insights", evidence=evidence)


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
        cfg = store.get_settings()["pipeline"]
        nxt = "storyboard" if cfg.get("review_storyboard", True) else "assemble"
        store.update_episode(eid, script_approved=True, stage=nxt, storyboard_approved=False)
        store.log(eid, "使用者核准講稿")
    else:
        _remember(eid, "講稿", feedback)
        store.update_episode(eid, script_approved=False, stage="critique", revise_feedback=feedback)
    enqueue("episode", eid)


def storyboard_decision(eid: str, approve: bool, notes: str = "") -> None:
    if approve:
        store.update_episode(eid, storyboard_approved=True, stage="assemble")
        store.log(eid, "使用者核准分鏡")
    else:
        _remember(eid, "畫面風格", notes or "分鏡需要調整")
        store.update_episode(eid, storyboard_approved=False, stage="critique", revise_feedback=notes or "")
        store.log(eid, "分鏡退回，重新修稿")
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
        store.add_pref(r.get("category") or stage, r.get("rule") or reason, status="active", source="reject")
        store.log(eid, f"寫回品味紀錄：{r.get('rule') or reason}")
    except llm.LLMError:
        store.add_pref(stage, reason, status="active", source="reject")
