"""JSON file storage for channel, settings, styles, preferences, ideas and episodes."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# CF_DATA lets a second instance (tests, smoke runs) use its own data folder instead of the live one.
DATA = Path(os.environ["CF_DATA"]).expanduser().resolve() if os.environ.get("CF_DATA") else ROOT / "data"
EPISODES = DATA / "episodes"
_lock = threading.RLock()

PREF_CATS = ["選題", "方向與觀點", "講稿語氣", "開頭與節奏", "畫面風格", "標題", "縮圖", "配音與字幕"]
STYLE_CATEGORIES = ["科技數碼", "新聞快評", "知識科普", "觀點深度", "生活工具"]

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
        "voice_ref": "",                  # 參考音檔路徑；index-tts2.5 / zonos3-mini 必填
        "ref_voice": "",                  # 參考聲音庫名稱（audio.cpp /v1/audio/voices；clon 模型用，優先於 voice）
        "emotion": "",                    # index-tts2.5 的情緒示範文字
        "emotion_alpha": 1.0,             # 0–1，情緒強度
        "per_scene_emotion": False,       # 逐段套用講稿情緒；Qwen3 的語氣指令會讓聲音聽起來像換人，預設關
        "convert_simplified": True,       # 送 TTS 前把繁體轉簡體（audio.cpp 讀繁常常出錯）
        "align_model": "qwen3-forced-aligner-0.6b",
        "align_language": "Chinese",
    },
    "visuals": {
        "source": "slides",                # slides = 字卡；comfy = 生圖當底；h3video = MiniMax-H3 生影片
        "comfy_url": "http://127.0.0.1:8188",
        "unet": "kromaKrea2_opd.safetensors",
        "clip": "Huihui-Qwen3-VL-4B-Instruct-abliterated-fp8_scaled.safetensors",
        "clip_type": "krea2",
        "encode": "",                      # qwen21 preset 會設成 qwen21（改用 TextEncodeQwenImage21）
        "vae": "qwen_image_vae.safetensors",
        "lora": "",                        # 例：Krea 2/KREA2turboNSFW.safetensors
        "lora_strength": 0.8,
        "steps": 8,
        "cfg": 1.0,
        "sampler": "euler",                # h3/moss/qwen21 preset 會換成對應最佳取樣器
        "timeout_s": 600,
        "free_after": True,                # 建完圖釋放 ComfyUI 模型，把 GPU 還給別的工作
        "style_hint": "cinematic editorial illustration, soft natural light, shallow depth of field, high detail",
        "pexels_key_env": "PEXELS_API_KEY",   # 只存名稱；實拍素材（Pexels）
        "pixabay_key_env": "PIXABAY_API_KEY", # 只存名稱；實拍素材（Pixabay）
    },
    "h3video": {
        "enabled": True,
        "recipe": "flex",                  # flex = Pika H3 Flex 6 步；native = 原生 res_multistep 25 步
        "unet": "minimax_h3_fl2va_pruned_int8_convrot_ssd.safetensors",   # 本機 SSD 副本；gdrive 原檔載入要 150–380 秒
        "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",          # ComfyUI 的 fast_disk 會自己快取到本機
        "vae": "minimax_h3_video_vae_int8_convrot_ssd.safetensors",
        "audio_vae": "minimax_h3_audio_vae_fp32_ssd.safetensors",  # H3 同時生環境音
        "ambient_gain_db": -14,            # H3 環境音相對旁白的音量；≤ -60 = 靜音
        "lora": "MiniMax H3/pika_h3_flex_fl2va_v1_noprefix.safetensors",
        "lora_strength": 1.0,
        "lora_node": "turbo",              # turbo = MiniMax-H3-Turbo 轉接器（快）；stock = LoraLoaderModelOnly
        "lora_merge": False,               # True = 併進權重（省 VRAM、量化基底較鈍）；False = bypass（銳利）
        "sigmas": "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0",
        "sampler": "lcm",                  # flex 固定 lcm；native 才用這個值
        "steps": 25,                       # 只有 native 配方會用到
        "max_seconds": 6,                  # 單段最長秒數（H3 一次約 5–6 秒最自然）
        "megapixels": 0.4,                 # 生成面積 ≈ 0.4 × 1024²（依畫框比例取整到 32 的倍數）
        "timeout_s": 1800,                 # 單段逾時
        "style_hint": "cinematic live-action photography, soft natural light, shallow depth of field, realistic texture",
    },
    "sfx": {
        "enabled": True,
        "gain_db": -16,                    # 音效相對旁白的音量
        "library_dir": "",                 # 空 = data/sfx
        "model_path": "",                  # 空 = 內建 MOSS-SoundEffect-v2 路徑
        "freesound_key_env": "FREESOUND_API_KEY",   # 只存名稱；Freesound 免費音效
        "freesound_license": "cc0",        # cc0 = 免標註；by = CC BY（成片說明自動標註）
        "stock_fallback": True,            # 本機模型生成失敗時，改抓 Freesound
    },
    "music": {
        "enabled": True,
        "provider": "audiocpp",            # audiocpp = YuE2；lyria = Google Lyria 3；openverse = Openverse 授權曲庫（免金鑰）
        "lyria_model": "lyria-3-clip-preview",  # 或 lyria-3-pro-preview
        "lyria_key_env": "GEMINI_API_KEY",  # 只存環境變數名稱，金鑰不進設定檔
        "openverse_license": "cc0",        # cc0 = 免標註；by = CC BY（成片說明自動標註）
        "base_url": "",                    # 空 = 跟 tts 同一個 audio.cpp 伺服器
        "model": "yue2",                   # audio.cpp 裡的 YuE2 3B 音樂模型
        "style": "",                       # 空 = 內建 lo-fi 風格；講稿的 music 欄位優先
        "seed": 1234,
        "steps": 8,
        "gain_db": -20,                    # 背景音樂相對旁白的音量
        "duck": True,                      # 旁白講話時自動壓低音樂
        "timeout_s": 3600,
        "cache_dir": "",                   # 空 = data/music
    },
    "cost": {
        "monthly_cap_usd": 10.0,           # 雲端付費呼叫月上限（Lyria／未來雲端生圖）
        "per_call_approval_usd": 0.5,      # 單筆超過此金額要先核准
        "prices": {                        # 每首歌單價；改價只改這裡
            "lyria-3-clip-preview": 0.04,
            "lyria-3-pro-preview": 0.08,
        },
    },
    "render": {
        "engine": "ffmpeg",                # ffmpeg = 直接燒字幕；remotion = React 動畫合成
        "fallback_ffmpeg": True,           # Remotion 失敗時自動退回 ffmpeg
        "remotion_dir": "",                # 空 = app 旁邊的 remotion/
    },
    "pipeline": {
        "review_script": True,             # gate: user reviews script before assembly
        "review_storyboard": True,         # gate: cheap scene preview before TTS/render
        "critique_threshold": 8,
        "critique_max_rounds": 3,
        "title_count": 6,
        "thumbnail_count": 4,
        "radar_min": 4,                    # each radar scan returns radar_min..radar_max topics
        "radar_max": 8,
        "radar_prefilter": True,           # wide-recall PASS/BLOCK/UNKNOWN prefilter
        "radar_scoring": True,             # 0–100 event-attention score + same-event grouping
        "radar_grouping": True,
        "radar_candidates_max": 12,        # candidates extracted from one scan
        "source_audit": True,              # LLM checks whether the fetched material supports the topic
        "source_gate": True,               # stop for the owner when no first-hand source is readable
        "source_min_readable": 1,
        "slideshow_risk_max": 0.7,         # 幀對「幾乎無變化」比例上限；超過記警告（畫面變化檢查）
    },
    "ui": {
        "nav_layout": "top",               # top | side
    },
    "youtube": {
        "client_file": "",                 # Google OAuth Desktop client_secret_*.json; empty = auto-detect
        "privacy": "private",              # private | unlisted | public (scheduled uploads are always private + publishAt)
        "category_id": "28",               # 28 = Science & Technology
        "language": "zh-Hant",
        "made_for_kids": False,
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

PRESET_STYLES: list[dict[str, Any]] = [
    {
        "id": "preset-tech-decode",
        "name": "科技口語拆解",
        "icon": "⚡",
        "category": "科技數碼",
        "summary": "把複雜的 AI／工程概念拆成一般上班族一聽就懂的日常比喻。",
        "tone": "像懂技術的朋友在咖啡店聊天，口語、直接、不賣弄名詞。",
        "opening": "前 3 秒直接丟出一個大家每天都遇過的痛點或反直覺事實。",
        "structure": "痛點共鳴 → 一句話講清楚是什麼 → 2～3 個實際情境 → 結論與限制。",
        "pacing": "短句為主，每段不超過 3 句就換一個視覺重點。",
        "words": ["白話說", "簡單講", "實測下來", "重點是"],
        "avoid": ["賦能", "顛覆", "革命性", "在這個快速發展的時代"],
        "preset": True,
        "source": "內建預設",
    },
    {
        "id": "preset-news-flash",
        "name": "快節奏新聞短評",
        "icon": "🔥",
        "category": "新聞快評",
        "summary": "60 秒內講完最新事件脈絡與關鍵影響，節奏緊湊不廢話。",
        "tone": "俐落、敏銳、有明確立場但事實依據清楚。",
        "opening": "第一句直接下結論或點出衝突，不鋪陳背景。",
        "structure": "事件核心 → 為什麼突然爆紅／重要 → 對一般人的影響 → 一句收尾問題。",
        "pacing": "句句帶資訊量，數字與時間點明確。",
        "words": ["剛發生", "關鍵在", "這代表", "注意一點"],
        "avoid": ["大家最近應該都有聽說", "總而言之", "讓我們一起看下去"],
        "preset": True,
        "source": "內建預設",
    },
    {
        "id": "preset-easy-guide",
        "name": "輕鬆生活科普",
        "icon": "🧩",
        "category": "知識科普",
        "summary": "用生活例子與清楚步驟解釋背後原理，降低理解門檻。",
        "tone": "親切、好奇、像帶觀眾一起動手實驗。",
        "opening": "從一個具體的生活疑問或常見誤解切入。",
        "structure": "常見疑問 → 真實原因／原理 → 生活類比 → 可帶走的實用做法。",
        "pacing": "中速穩健，重要觀念會先鋪個生活比喻。",
        "words": ["其實是這樣", "舉個例子", "換個方式想", "你可以這樣試"],
        "avoid": ["艱深術語連發", "居高臨下說教"],
        "preset": True,
        "source": "內建預設",
    },
    {
        "id": "preset-deep-take",
        "name": "觀點深度長評",
        "icon": "🎯",
        "category": "觀點深度",
        "summary": "拆開表面熱鬧，提出具辨識度的第二層思考與產業脈絡。",
        "tone": "冷靜、克制、有邏輯推進與明確主張。",
        "opening": "先指出多數人看錯的地方，再拋出核心問題。",
        "structure": "主流看法與盲點 → 歷史／數據脈絡 → 三個關鍵推論 → 留給觀眾的思考。",
        "pacing": "長短句交替，關鍵轉折前留白停頓。",
        "words": ["真正的問題是", "退一步看", "代價在於", "這背後反映的是"],
        "avoid": ["情緒化誇大", "沒有依據的陰謀論", "空洞雞湯"],
        "preset": True,
        "source": "內建預設",
    },
    {
        "id": "preset-tool-review",
        "name": "實測工具種草",
        "icon": "🛠️",
        "category": "生活工具",
        "summary": "實事求是評測工具好不好用，同時講優點與踩坑點。",
        "tone": "誠實、務實、像同事分享自己真正在用的工作流。",
        "opening": "先講這工具幫你省下什麼麻煩，或直接看實測結果。",
        "structure": "解決什麼痛點 → 實際操作步驟 → 優點與真的卡住的地方 → 適合誰用。",
        "pacing": "步驟清楚，畫面與動作一一對應。",
        "words": ["我實測了", "老實說", "真正好用的是", "不過要注意"],
        "avoid": ["完美無缺", "最強神器", "業配感誇張讚美"],
        "preset": True,
        "source": "內建預設",
    },
]


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
        merged = _merge(DEFAULT_SETTINGS, _read(DATA / "settings.json", {}))
        if merged["ui"].get("nav_layout") not in ("top", "side"):
            merged["ui"]["nav_layout"] = "top"
        _fix_radar_range(merged["pipeline"])
        return merged


def _clamp_topic_count(val: Any, default: int) -> int:
    try:
        return min(12, max(3, int(val)))
    except (TypeError, ValueError):
        return default


def _fix_radar_range(p: dict) -> None:
    lo = _clamp_topic_count(p.get("radar_min"), 4)
    hi = _clamp_topic_count(p.get("radar_max"), 8)
    if lo > hi:
        lo, hi = hi, lo
    p["radar_min"], p["radar_max"] = lo, hi


def save_settings(s: dict) -> dict:
    with _lock:
        merged = _merge(DEFAULT_SETTINGS, s)
        if merged["ui"].get("nav_layout") not in ("top", "side"):
            merged["ui"]["nav_layout"] = "top"
        _fix_radar_range(merged["pipeline"])
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


def _norm_pref(p: dict, idx: int = 0) -> dict | None:
    if not isinstance(p, dict):
        return None
    rule = str(p.get("rule") or "").strip()
    if not rule:
        return None
    cat = str(p.get("category") or "講稿語氣").strip() or "講稿語氣"
    date = str(p.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    pid = str(p.get("id") or "").strip()
    if not pid:
        digest = hashlib.sha1(f"{cat}|{rule}|{date}|{idx}".encode("utf-8")).hexdigest()[:8]
        pid = f"pref-{digest}"
    status = p.get("status")
    if status not in ("active", "paused", "proposed"):
        status = "active"
    source = p.get("source")
    if source not in ("seed", "manual", "reject", "insights"):
        source = "seed" if date == "預設" else "manual"
    return {
        "id": pid,
        "category": cat,
        "rule": rule,
        "date": date,
        "status": status,
        "source": source,
        "evidence": str(p.get("evidence") or "").strip(),
    }


def _norm_pref_list(items: list[dict]) -> list[dict]:
    out = []
    for idx, item in enumerate(items):
        norm = _norm_pref(item, idx)
        if norm:
            out.append(norm)
    return out


def get_prefs() -> list[dict]:
    with _lock:
        raw = _read(DATA / "preferences.json", SEED_PREFS)
        return _norm_pref_list(raw if isinstance(raw, list) else [])


def save_prefs(p: list[dict]) -> list[dict]:
    with _lock:
        norm = _norm_pref_list(p)
        _write(DATA / "preferences.json", norm)
        return norm


def add_pref(
    category: str,
    rule: str,
    *,
    status: str = "active",
    source: str = "manual",
    evidence: str = "",
) -> dict:
    with _lock:
        clean_rule = (rule or "").strip()
        clean_cat = (category or "講稿語氣").strip() or "講稿語氣"
        if status not in ("active", "paused", "proposed"):
            status = "active"
        if source not in ("seed", "manual", "reject", "insights"):
            source = "manual"
        items = get_prefs()
        for existing in items:
            if existing["rule"].strip() == clean_rule:
                existing["category"] = clean_cat
                existing["status"] = status
                existing["source"] = source
                if evidence.strip():
                    existing["evidence"] = evidence.strip()
                existing["date"] = datetime.now().strftime("%Y-%m-%d")
                save_prefs(items)
                return existing
        entry = {
            "id": f"pref-{uuid.uuid4().hex[:8]}",
            "category": clean_cat,
            "rule": clean_rule,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "status": status,
            "source": source,
            "evidence": (evidence or "").strip(),
        }
        if not clean_rule:
            return entry
        items.append(entry)
        save_prefs(items)
        return entry


def update_pref(pid: str, patch: dict) -> dict | None:
    with _lock:
        items = get_prefs()
        for item in items:
            if item["id"] == pid:
                if "category" in patch and str(patch["category"]).strip():
                    item["category"] = str(patch["category"]).strip()
                if "rule" in patch and str(patch["rule"]).strip():
                    item["rule"] = str(patch["rule"]).strip()
                if patch.get("status") in ("active", "paused", "proposed"):
                    item["status"] = patch["status"]
                if "evidence" in patch:
                    item["evidence"] = str(patch["evidence"] or "").strip()
                save_prefs(items)
                return item
        return None


def delete_pref(pid: str) -> bool:
    with _lock:
        items = get_prefs()
        kept = [item for item in items if item["id"] != pid]
        if len(kept) == len(items):
            return False
        save_prefs(kept)
        return True


def prefs_text() -> str:
    lines = [
        f"- [{p['category']}] {p['rule']}"
        for p in get_prefs()
        if p.get("status", "active") == "active"
    ]
    return "\n".join(lines) if lines else "（尚無）"


# ---------- radar & ideas ----------

def _norm_idea(item: dict, idx: int = 0) -> dict | None:
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or "").strip()
    notes = str(item.get("notes") or "").strip()
    urls = [str(u).strip() for u in (item.get("urls") or []) if str(u).strip()]
    source = str(item.get("source") or "").strip()
    if not urls and source.startswith("http"):
        urls = [source]
    if not title and not notes and not urls:
        return None
    if not title:
        title = (notes.splitlines()[0] if notes else urls[0])[:60]
    found = item.get("found")
    try:
        found_ts = float(found) if found is not None else time.time()
    except (TypeError, ValueError):
        found_ts = time.time()
    iid = str(item.get("id") or "").strip()
    if not iid:
        digest = hashlib.sha1(f"{title}|{found_ts}|{idx}".encode("utf-8")).hexdigest()[:8]
        iid = f"idea-{digest}"
    kind = item.get("kind")
    if kind not in ("radar", "note", "link", "quote"):
        kind = "radar"
    fmt = item.get("format") if item.get("format") in ("long", "short") else "short"
    tags = [str(t).strip() for t in (item.get("tags") or []) if str(t).strip()]
    return {
        "id": iid,
        "kind": kind,
        "title": title,
        "why": str(item.get("why") or "").strip(),
        "source": source or (urls[0] if urls else ""),
        "format": fmt,
        "heat": str(item.get("heat") or "").strip(),
        "found": found_ts,
        "urls": urls,
        "notes": notes,
        "tags": tags,
        "episode_id": item.get("episode_id") or None,
        **_norm_idea_radar(item),
    }


def _norm_idea_radar(item: dict) -> dict:
    """Radar-only fields; old ideas saved before this existed get neutral defaults."""
    score = item.get("attention_score")
    try:
        score = max(0, min(100, int(round(float(score))))) if score is not None else None
    except (TypeError, ValueError):
        score = None
    group = str(item.get("group") or "").strip()
    members = []
    for m in item.get("members") or []:
        if not isinstance(m, dict):
            continue
        members.append({
            "title": str(m.get("title") or "").strip(),
            "source": str(m.get("source") or "").strip(),
            "url": str(m.get("url") or "").strip(),
            "attention_score": m.get("attention_score") if isinstance(m.get("attention_score"), int) else None,
            "prefilter": str(m.get("prefilter") or "").strip(),
            "relation": str(m.get("relation") or "").strip(),
        })
    try:
        group_size = max(1, int(item.get("group_size") or len(members) or 1))
    except (TypeError, ValueError):
        group_size = max(1, len(members))
    return {
        "attention_score": score,
        "score_reason": str(item.get("score_reason") or "").strip(),
        "prefilter": str(item.get("prefilter") or "").strip(),
        "needs_more": bool(item.get("needs_more")),
        "group": group,
        "group_size": group_size,
        "members": members,
    }


IDEA_LIMIT = 300      # 使用者自己記的靈感：超過才從最舊的開始丟
RADAR_LIMIT = 60      # 雷達掃回來的題目：只留最新的


def _norm_idea_list(items: list[dict]) -> list[dict]:
    kept = []
    for idx, item in enumerate(items):
        norm = _norm_idea(item, idx)
        if norm:
            kept.append(norm)
    manual = [x for x in kept if x["kind"] != "radar"]
    radar = [x for x in kept if x["kind"] == "radar"]
    radar = sorted(radar, key=lambda x: x["found"], reverse=True)[:RADAR_LIMIT]
    manual = sorted(manual, key=lambda x: x["found"], reverse=True)[:IDEA_LIMIT]
    return sorted(manual + radar, key=lambda x: x["found"], reverse=True)


def get_radar() -> list[dict]:
    with _lock:
        raw = _read(DATA / "radar.json", [])
        return _norm_idea_list(raw if isinstance(raw, list) else [])


list_ideas = get_radar


def save_radar(items: list[dict]) -> None:
    with _lock:
        _write(DATA / "radar.json", _norm_idea_list(items))


def add_idea(data: dict) -> dict:
    with _lock:
        items = get_radar()
        candidate = dict(data)
        candidate.setdefault("id", f"idea-{uuid.uuid4().hex[:8]}")
        candidate.setdefault("found", time.time())
        norm = _norm_idea(candidate, 0)
        if not norm:
            raise ValueError("靈感內容不能為空")
        items.insert(0, norm)
        save_radar(items)
        return norm


def update_idea(iid: str, patch: dict) -> dict | None:
    with _lock:
        items = get_radar()
        for idx, item in enumerate(items):
            if item["id"] == iid:
                merged = {**item, **patch, "id": iid}
                norm = _norm_idea(merged, idx)
                if not norm:
                    return None
                items[idx] = norm
                save_radar(items)
                return norm
        return None


def delete_idea(iid: str) -> bool:
    with _lock:
        items = get_radar()
        kept = [item for item in items if item["id"] != iid]
        if len(kept) == len(items):
            return False
        save_radar(kept)
        return True


# ---------- styles (multi-style cards) ----------

def _norm_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return [x.strip() for x in re.split(r"[、,，\n]+", val) if x.strip()]
    return []


def _norm_style(s: dict) -> dict:
    return {
        "id": str(s.get("id") or f"style-{uuid.uuid4().hex[:8]}").strip(),
        "name": str(s.get("name") or "未命名風格").strip(),
        "icon": str(s.get("icon") or "✨").strip() or "✨",
        "category": str(s.get("category") or STYLE_CATEGORIES[0]).strip(),
        "summary": str(s.get("summary") or "").strip(),
        "tone": str(s.get("tone") or "").strip(),
        "opening": str(s.get("opening") or "").strip(),
        "structure": str(s.get("structure") or "").strip(),
        "pacing": str(s.get("pacing") or "").strip(),
        "words": _norm_list(s.get("words")),
        "avoid": _norm_list(s.get("avoid")),
        "preset": bool(s.get("preset", False)),
        "source": str(s.get("source") or ("內建預設" if s.get("preset") else "自訂")).strip(),
    }


def _bootstrap_styles() -> dict:
    items = [_norm_style(p) for p in PRESET_STYLES]
    active_id = PRESET_STYLES[0]["id"]
    ch = get_channel()
    if (ch.get("tone") or "").strip() or (ch.get("name") or "").strip():
        custom = _norm_style({
            "id": "my-channel-style",
            "name": f"{ch['name']}預設風格" if ch.get("name") else "我的頻道風格",
            "icon": "🎙️",
            "category": STYLE_CATEGORIES[0],
            "summary": ch.get("topic") or "依頻道定位產生的預設風格卡。",
            "tone": ch.get("tone") or "口語、清楚、有觀點",
            "opening": "開頭直接點題或拋出觀眾會在意的疑問。",
            "structure": "核心觀點 → 實例說明 → 可執行的結論。",
            "pacing": "節奏明快，避免冗長鋪陳。",
            "words": [],
            "avoid": [ch["taboo"]] if (ch.get("taboo") or "").strip() else [],
            "preset": False,
            "source": "由頻道定位建立",
        })
        items.insert(0, custom)
        active_id = custom["id"]
    data = {"active_id": active_id, "items": items}
    _write(DATA / "styles.json", data)
    return data


def get_styles() -> dict:
    with _lock:
        path = DATA / "styles.json"
        if not path.exists():
            return _bootstrap_styles()
        raw = _read(path, {})
        items = [_norm_style(x) for x in raw.get("items", []) if isinstance(x, dict)]
        by_id = {x["id"]: x for x in items}
        changed = False
        for preset in PRESET_STYLES:
            if preset["id"] not in by_id:
                norm_p = _norm_style(preset)
                items.append(norm_p)
                by_id[norm_p["id"]] = norm_p
                changed = True
        active_id = raw.get("active_id")
        if active_id not in by_id:
            active_id = items[0]["id"] if items else PRESET_STYLES[0]["id"]
            changed = True
        out = {"active_id": active_id, "items": items}
        if changed:
            _write(path, out)
        return out


def get_style(sid: str | None = None) -> dict | None:
    data = get_styles()
    target = sid or data["active_id"]
    for item in data["items"]:
        if item["id"] == target:
            return item
    return None


def create_style(data: dict, activate: bool = False) -> dict:
    with _lock:
        cur = get_styles()
        card = _norm_style({**data, "id": f"style-{uuid.uuid4().hex[:8]}", "preset": False})
        cur["items"].insert(0, card)
        if activate:
            cur["active_id"] = card["id"]
        _write(DATA / "styles.json", cur)
        return card


def update_style(sid: str, patch: dict) -> dict | None:
    with _lock:
        cur = get_styles()
        for idx, item in enumerate(cur["items"]):
            if item["id"] == sid:
                updated = _norm_style({
                    **item,
                    **patch,
                    "id": sid,
                    "preset": item["preset"],
                    "source": item["source"] if item["preset"] else (patch.get("source") or item["source"]),
                })
                cur["items"][idx] = updated
                _write(DATA / "styles.json", cur)
                return updated
        return None


def delete_style(sid: str) -> bool:
    with _lock:
        cur = get_styles()
        target = next((x for x in cur["items"] if x["id"] == sid), None)
        if not target:
            return False
        if target.get("preset"):
            raise ValueError("內建風格卡不能刪除")
        cur["items"] = [x for x in cur["items"] if x["id"] != sid]
        if cur["active_id"] == sid:
            cur["active_id"] = cur["items"][0]["id"] if cur["items"] else PRESET_STYLES[0]["id"]
        _write(DATA / "styles.json", cur)
        return True


def activate_style(sid: str) -> dict:
    with _lock:
        cur = get_styles()
        if not any(x["id"] == sid for x in cur["items"]):
            raise KeyError("找不到這張風格卡")
        cur["active_id"] = sid
        _write(DATA / "styles.json", cur)
        return cur


def style_block(style_id: str | None = None) -> str:
    card = get_style(style_id) or get_style()
    if not card:
        return "（無）"
    lines = [
        f"風格名稱：{card['icon']} {card['name']}（{card['category']}）",
        f"簡介：{card['summary'] or '（無）'}",
        f"語氣：{card['tone'] or '（無）'}",
        f"開頭方式：{card['opening'] or '（無）'}",
        f"結構節奏：{card['structure'] or '（無）'}；{card['pacing'] or ''}".rstrip("；"),
    ]
    if card["words"]:
        lines.append("常用詞／口頭禪：" + "、".join(card["words"]))
    if card["avoid"]:
        lines.append("絕對避開：" + "、".join(card["avoid"]))
    return "\n".join(lines)


# ---------- episodes ----------

def slugify(text: str) -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", text).strip("-")[:30]
    return s or "episode"


def ep_dir(eid: str) -> Path:
    if not re.fullmatch(r"[\w一-鿿-]+", eid):
        raise ValueError("bad episode id")
    return EPISODES / eid


def new_episode(
    topic: str,
    fmt: str,
    notes: str = "",
    sources: list[str] | None = None,
    style_id: str | None = None,
    idea_id: str | None = None,
) -> dict:
    with _lock:
        eid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + slugify(topic)
        chosen_style = style_id or get_styles()["active_id"]
        ep = {
            "id": eid,
            "topic": topic,
            "format": fmt,                 # long | short
            "notes": notes,
            "source_urls": sources or [],
            "style_id": chosen_style,
            "idea_id": idea_id or None,
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
        if idea_id:
            update_idea(idea_id, {"episode_id": eid})
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


def update_check(eid: str, key: str, check: dict) -> dict:
    """Set one entry of ep["checks"] under the lock, so a concurrent HTTP update is not lost (B4)."""
    with _lock:
        ep = get_episode(eid)
        ep.setdefault("checks", {})[key] = check
        save_episode(ep)
        return ep


def claim_episode(eid: str, status: str, waiting_for: str | None = None) -> dict | None:
    """Check and move an episode to "queued" in one locked step.

    Returns the episode as it was before the claim, or None when it is not in `status`
    (and, if given, not waiting for `waiting_for`). Two clicks on the same gate, or two
    tabs, can therefore never both pass and start the pipeline twice.
    """
    with _lock:
        ep = get_episode(eid)
        if not ep or ep.get("status") != status:
            return None
        if waiting_for is not None and ep.get("waiting_for") != waiting_for:
            return None
        before = json.loads(json.dumps(ep))
        ep.update(status="queued", waiting_for=None, error=None)
        save_episode(ep)
        return before


def update_schedule(eid: str, schedule: str | None) -> dict:
    with _lock:
        clean = (schedule or "").strip() or None
        if clean:
            clean = clean.replace(" ", "T")
            try:
                datetime.fromisoformat(clean)
            except ValueError as e:
                raise ValueError("排期時間格式要像 2026-11-25T20:00") from e
        ep = update_episode(eid, schedule=clean)
        meta_path = ep_dir(eid) / "publish" / "metadata.json"
        if meta_path.exists():
            meta = _read(meta_path, {})
            meta["schedule"] = clean
            _write(meta_path, meta)
        return ep


def log(eid: str, msg: str) -> None:
    with _lock:
        ep = get_episode(eid)
        ep["log"].append({"t": time.time(), "msg": msg})
        ep["log"] = ep["log"][-300:]
        save_episode(ep)


def _parse_int(val: Any) -> int:
    if val is None or isinstance(val, bool):
        return 0
    if isinstance(val, (int, float)):
        return max(0, int(round(val)))
    s = str(val).strip().replace(",", "").replace(" ", "")
    if not s:
        return 0
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*([萬万wWkK億亿])?", s)
    if not m:
        digits = re.sub(r"[^\d.]", "", s)
        try:
            return max(0, int(float(digits))) if digits else 0
        except ValueError:
            return 0
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    mult = {"萬": 10000, "万": 10000, "w": 10000, "k": 1000, "億": 100000000, "亿": 100000000}.get(unit, 1)
    return max(0, int(round(num * mult)))


def _episode_thumb(eid: str, ep: dict) -> str | None:
    pk_path = ep_dir(eid) / "package.json"
    if not pk_path.exists():
        return None
    try:
        pk = json.loads(pk_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    thumbs = pk.get("thumbnails") or []
    if not thumbs:
        return None
    choice = (ep.get("package_choice") or {}).get("thumb")
    if isinstance(choice, int) and 0 <= choice < len(thumbs):
        return thumbs[choice].get("file")
    return thumbs[0].get("file")


def list_episodes() -> list[dict]:
    with _lock:
        out = []
        if EPISODES.exists():
            for d in EPISODES.iterdir():
                f = d / "episode.json"
                if f.exists():
                    ep = json.loads(f.read_text("utf-8"))
                    ep.pop("log", None)
                    eid = ep["id"]
                    ep["thumb"] = _episode_thumb(eid, ep)
                    metrics_path = d / "metrics.json"
                    if metrics_path.exists():
                        try:
                            ms = json.loads(metrics_path.read_text("utf-8"))
                        except (OSError, json.JSONDecodeError):
                            ms = []
                    else:
                        ms = []
                    ep["metrics_count"] = len(ms)
                    ep["total_views"] = sum(_parse_int(m.get("views")) for m in ms if isinstance(m, dict))
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


# ---------- insights ----------

DEFAULT_INSIGHTS_SUMMARY = {
    "headline": "",
    "updated": None,
    "analyzing": False,
    "error": None,
}


def get_insights_summary() -> dict:
    with _lock:
        return _merge(DEFAULT_INSIGHTS_SUMMARY, _read(DATA / "insights_summary.json", {}))


def save_insights_summary(data: dict) -> dict:
    with _lock:
        merged = _merge(DEFAULT_INSIGHTS_SUMMARY, data)
        _write(DATA / "insights_summary.json", merged)
        return merged


def _valid_iso_date(val: str) -> str | None:
    s = (val or "").strip()[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return None


def aggregate_insights(days: int = 30, platform: str = "all") -> dict:
    eps = list_episodes()
    cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d") if days > 0 else None
    plat_filter = (platform or "all").strip().lower()

    platforms_available: set[str] = set()
    all_rows: list[dict] = []

    for ep in eps:
        eid = ep["id"]
        ms = read_json(eid, "metrics.json", [])
        if not isinstance(ms, list):
            continue
        ep_title = (ep.get("package_choice") or {}).get("title") or ep["topic"]
        ep_date = datetime.fromtimestamp(ep.get("created") or time.time()).strftime("%Y-%m-%d")
        for idx, raw in enumerate(ms):
            if not isinstance(raw, dict):
                continue
            plat = str(raw.get("platform") or "未指定").strip() or "未指定"
            platforms_available.add(plat)
            raw_date = str(raw.get("date") or "").strip()
            eff_date = _valid_iso_date(raw_date) or ep_date
            if cutoff and eff_date < cutoff:
                continue
            if plat_filter != "all" and plat.lower() != plat_filter:
                continue
            views = _parse_int(raw.get("views"))
            followers = _parse_int(raw.get("followers"))
            likes = _parse_int(raw.get("likes"))
            saves = _parse_int(raw.get("saves"))
            comments = _parse_int(raw.get("comments"))
            engaged = likes + saves + comments
            all_rows.append({
                "episode_id": eid,
                "episode_title": ep_title,
                "episode_format": ep.get("format", "short"),
                "episode_thumb": ep.get("thumb"),
                "idx": idx,
                "platform": plat,
                "date": raw_date or eff_date,
                "eff_date": eff_date,
                "views": views,
                "watch_time": str(raw.get("watch_time") or "").strip(),
                "followers": followers,
                "likes": likes,
                "saves": saves,
                "comments": comments,
                "engaged": engaged,
                "note": str(raw.get("note") or "").strip(),
            })

    total_views = sum(r["views"] for r in all_rows)
    total_followers = sum(r["followers"] for r in all_rows)
    total_likes = sum(r["likes"] for r in all_rows)
    total_saves = sum(r["saves"] for r in all_rows)
    total_comments = sum(r["comments"] for r in all_rows)
    total_engaged = sum(r["engaged"] for r in all_rows)
    ep_ids = {r["episode_id"] for r in all_rows}
    avg_views = round(total_views / len(ep_ids)) if ep_ids else 0

    daily_map: dict[str, dict] = {}
    plat_map: dict[str, dict] = {}
    ep_map: dict[str, dict] = {}

    for r in all_rows:
        d = daily_map.setdefault(r["eff_date"], {"date": r["eff_date"], "views": 0, "followers": 0, "engaged": 0, "count": 0})
        d["views"] += r["views"]
        d["followers"] += r["followers"]
        d["engaged"] += r["engaged"]
        d["count"] += 1

        pm = plat_map.setdefault(r["platform"], {
            "platform": r["platform"], "views": 0, "followers": 0,
            "likes": 0, "saves": 0, "comments": 0, "engaged": 0, "count": 0,
        })
        pm["views"] += r["views"]
        pm["followers"] += r["followers"]
        pm["likes"] += r["likes"]
        pm["saves"] += r["saves"]
        pm["comments"] += r["comments"]
        pm["engaged"] += r["engaged"]
        pm["count"] += 1

        em = ep_map.setdefault(r["episode_id"], {
            "id": r["episode_id"],
            "title": r["episode_title"],
            "format": r["episode_format"],
            "thumb": r["episode_thumb"],
            "views": 0,
            "followers": 0,
            "engaged": 0,
            "platforms": set(),
        })
        em["views"] += r["views"]
        em["followers"] += r["followers"]
        em["engaged"] += r["engaged"]
        em["platforms"].add(r["platform"])

    daily = sorted(daily_map.values(), key=lambda x: x["date"])
    by_platform = sorted(plat_map.values(), key=lambda x: (x["views"], x["engaged"], x["count"]), reverse=True)
    top_episodes = []
    for em in sorted(ep_map.values(), key=lambda x: (x["views"], x["engaged"], x["followers"]), reverse=True)[:5]:
        top_episodes.append({**em, "platforms": sorted(em["platforms"])})

    records = sorted(
        [{k: v for k, v in r.items() if k not in ("eff_date", "episode_format", "episode_thumb")} for r in all_rows],
        key=lambda x: x["date"],
        reverse=True,
    )

    proposed_rules = [p for p in get_prefs() if p.get("status") == "proposed"]

    return {
        "totals": {
            "views": total_views,
            "followers": total_followers,
            "likes": total_likes,
            "saves": total_saves,
            "comments": total_comments,
            "engaged": total_engaged,
            "records": len(all_rows),
            "episodes_with_metrics": len(ep_ids),
            "avg_views": avg_views,
        },
        "platforms_available": sorted(platforms_available),
        "daily": daily,
        "by_platform": by_platform,
        "top_episodes": top_episodes,
        "records": records,
        "summary": get_insights_summary(),
        "proposed_rules": proposed_rules,
    }
