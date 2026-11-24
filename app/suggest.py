"""Suggest the episode settings from a topic, so the owner only has to add their angle.

Two stages, on purpose:

1. `heuristic()` is instant and pure. It runs the moment the dialog opens, so the controls are
   never blank while the model thinks.
2. `refine()` asks the model to judge the topic properly. It runs in the background with a short
   timeout: the local model can take minutes on a long prompt, and the dialog must not wait for it.

Everything the model returns is validated against the real vocabulary (`store.FORMS`,
`store.MODES`, the style cards, the channel ceiling). A suggestion that does not fit is dropped
rather than passed through: the dialog would otherwise pre-select something the API rejects.
"""
from __future__ import annotations

import re
from typing import Any

from . import editorial, llm, store

# --- signals -------------------------------------------------------------------------------

# Words that put a topic above `general`. Deliberately explicit: a false negative here means the
# owner has to raise the rating by hand once, which is far cheaper than a false positive.
# Explicit sexual content only. Bare "成人" is excluded on purpose: 「成人話題：界線與溝通」is
# a discussion, not pornography, and forcing it to `adult` would drop it from every platform.
_ADULT_WORDS = (
    "情色", "色情", "情慾", "裸", "性愛", "性行為", "做愛", "高潮", "呻吟", "調教", "肉體",
    "情色小說", "色情小說", "erotic", "nsfw", "18+", "限制級", "露點", "濕透", "成人小說",
)
_SUGGESTIVE_WORDS = (
    "曖昧", "情慾", "誘惑", "挑逗", "親密", "慾望", "性感", "偷情", "外遇", "一夜", "激情",
    "禁忌", "關係", "身體", "親吻",
)

# form keywords, most specific first
_FORM_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("comic", ("漫畫", "分格", "格子", "comic", "manga")),
    ("script", ("劇本", "分鏡", "腳本", "screenplay", "script")),
    ("radio_drama", ("廣播劇", "radio drama", "有聲劇")),
    ("asmr", ("asmr", "耳語", "白噪音", "環境音")),
    ("audiobook", ("有聲書", "朗讀", "mp3", "聽書", "有聲")),
    ("poem", ("詩", "新詩", "短詩", "極短篇", "俳句")),
    ("chat", ("訊息", "對話記錄", "聊天記錄", "私訊", "line 對話", "dm")),
    ("serial", ("連載", "長篇", "系列", "章節")),
    ("novel", ("小說", "故事", "短篇", "散文", "小品")),
    ("gallery", ("圖集", "寫真", "圖片", "相片", "攝影集", "圖文")),
    ("guide", ("教學", "指南", "怎麼", "如何", "步驟", "入門", "攻略")),
    ("talk", ("評論", "解析", "看法", "觀點", "復盤", "聊", "fta", "訪談")),
)

_NEWSY_WORDS = (
    "發布", "宣布", "推出", "發表", "回應", "爭議", "研究", "報告", "數據", "調查", "財報",
    "上市", "開源", "更新", "裁員", "收購", "訴訟", "政策", "規範", "評測",
)
_STORY_WORDS = ("故事", "小說", "劇本", "漫畫", "角色", "場景", "情節", "想像", "世界觀",
                "詩", "朗讀", "廣播劇", "耳語", "連載", "短篇", "散文", "對白", "台詞", "訊息體")
# forms that only make sense for invented content: picking one means the topic is a story
_FICTION_FORMS = ("novel", "serial", "poem", "chat", "script", "comic", "radio_drama", "asmr")
_LONG_WORDS = ("完整", "深入", "原理", "歷史", "指南", "教學", "解析", "比較", "全攻略", "系列")

_URL_RE = re.compile(r"https?://[^\s，。、）)」』\"']+")


def extract_urls(*texts: str) -> list[str]:
    """URLs already written in the topic or notes: those can be filled in without a search."""
    out: list[str] = []
    for t in texts:
        for u in _URL_RE.findall(t or ""):
            u = u.rstrip(".,;:!?")
            if u not in out:
                out.append(u)
    return out


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    low = (text or "").lower()
    return [w for w in words if w.lower() in low]


def heuristic(topic: str, notes: str = "", allowed_rating: str = "adult") -> dict:
    """A fast, explainable first guess. Pure: same input, same output, no I/O."""
    text = f"{topic} {notes}".strip()
    reasons: list[str] = []

    # rating
    adult = _hits(text, _ADULT_WORDS)
    soft = _hits(text, _SUGGESTIVE_WORDS)
    rating = "adult" if adult else ("suggestive" if soft else "general")
    if not store.rating_at_or_below(rating, allowed_rating):
        rating = allowed_rating if store.rating_at_or_below(allowed_rating, "adult") else "general"
    if adult:
        reasons.append(f"提到「{adult[0]}」，判為成人分級")
    elif soft:
        reasons.append(f"提到「{soft[0]}」，判為暗示分級")

    # form first: several forms only make sense for invented content, and mode depends on that
    form = "video"
    for cand, words in _FORM_WORDS:
        hit = _hits(text, words)
        if hit:
            form = cand
            reasons.append(f"提到「{hit[0]}」，做成 {store.FORM_LABEL.get(cand, cand)}")
            break

    # mode: a rated topic is fiction; a story form is fiction; a newsy one stays news
    newsy = _hits(text, _NEWSY_WORDS)
    story = _hits(text, _STORY_WORDS)
    if rating != "general":
        mode = "fiction" if story or not newsy else "narrative"
        reasons.append("受限分級必須是虛構內容")
    elif (story and not newsy) or form in _FICTION_FORMS:
        mode = "fiction"
        if story:
            reasons.append(f"提到「{story[0]}」，判為自由創作")
        else:
            reasons.append(f"成品形態是「{store.FORM_LABEL.get(form, form)}」，判為自由創作")
    elif newsy:
        mode = "news"
        reasons.append(f"像可查證的題材（「{newsy[0]}」）")
    else:
        mode = "news"

    # length: depth words, or a form that is inherently long
    long_form = form in ("serial", "audiobook", "radio_drama", "script", "comic", "guide")
    fmt = "long" if long_form or _hits(text, _LONG_WORDS) else "short"

    return {"topic": topic, "mode": mode, "rating": rating, "form": form, "format": fmt,
            "source_urls": extract_urls(topic, notes), "reasons": reasons, "by": "rules"}


def _valid(ep: dict, ceiling: str) -> list[str]:
    """Drop anything that would be rejected at creation."""
    bad: list[str] = []
    if ep.get("mode") not in store.MODES:
        ep["mode"] = "news"
        bad.append("mode")
    if ep.get("rating") not in store.RATINGS or not store.rating_at_or_below(ep["rating"], ceiling):
        ep["rating"] = ceiling if store.rating_at_or_below(ceiling, "adult") else "general"
        bad.append("rating")
    if store.rating_conflict(ep["mode"], ep["rating"]):
        ep["mode"] = "narrative" if ep["rating"] != "general" else "news"
        bad.append("mode_conflict")
    if ep.get("form") not in store.FORMS:
        ep["form"] = "video"
        bad.append("form")
    if ep.get("format") not in ("short", "long"):
        ep["format"] = "short"
        bad.append("format")
    return bad


# Which categories suit which form. Used as a tie-break, not a hard filter: a poem belongs with
# narrative and sensual cards long before it belongs with a spec showdown.
_FORM_CATEGORY = {
    "poem": ("情慾敘事", "感官描寫", "敘事紀實", "電影質感"),
    "serial": ("情慾敘事", "敘事紀實", "觀點深度"),
    "novel": ("情慾敘事", "敘事紀實", "關係" ),
    "chat": ("角色關係", "情慾敘事", "社群短影音"),
    "audiobook": ("情慾敘事", "感官描寫", "敘事紀實"),
    "radio_drama": ("情慾敘事", "感官描寫", "角色關係", "動畫手繪"),
    "asmr": ("感官描寫", "角色關係"),
    "script": ("情慾敘事", "角色關係", "腳本格式", "電影質感"),
    "comic": ("腳本格式", "圖像寫真", "動畫手繪", "角色關係"),
    "gallery": ("圖像寫真", "感官描寫", "電影質感"),
    "guide": ("成人話題", "知識科普", "生活工具"),
    "talk": ("成人話題", "新聞快評", "觀點深度"),
    "video": (),
}

# Words in a card that say it is about adult material. Used so a general-topic episode does not
# get an adult card even when the rating allows one.
_RACY_CATEGORIES = ("情慾敘事", "感官描寫", "圖像寫真")


def _grams(text: str, n: int = 2) -> set[str]:
    """Character n-grams: CJK has no spaces, so whole-phrase splitting matches nothing."""
    clean = re.sub(r"[\s，。、,;：:！？!?（）()「」『』\"'…—]+", "", text or "")
    return {clean[i:i + n] for i in range(max(0, len(clean) - n + 1))}


def pick_style(styles: list[dict], rating: str, form: str, text: str,
               category: str | None = None) -> tuple[str, str]:
    """The card that best matches this topic, or ("", reason) when none fits."""
    rank = {"general": 0, "suggestive": 1, "adult": 2}
    want = rank.get(rating, 0)
    topic_grams = _grams(text)
    preferred = _FORM_CATEGORY.get(form, ())
    active = store.get_styles().get("active_id")
    best, best_score, best_why = "", -1.0, ""
    for card in styles:
        # a card must fit the rating and the form, exactly like the picker in the dialog
        if rank.get(card.get("rating_min") or "general", 0) > want:
            continue
        forms = card.get("forms") or []
        if forms and form not in forms:
            continue
        hay = " ".join(str(card.get(k) or "") for k in ("name", "category", "summary", "tone", "words"))
        overlap = len(topic_grams & _grams(hay))
        score = float(overlap)
        cat = card.get("category") or ""
        if cat in preferred:
            score += 4.0
        if category and cat == category:
            score += 3.0
        # an adult card only wins on an adult topic; a general topic keeps a general card
        if cat in _RACY_CATEGORIES:
            score += 6.0 if want >= 2 else -5.0
        if card.get("id") == active:
            score += 0.5
        if score > best_score:
            best, best_score, best_why = card["id"], score, card.get("name") or ""
    if not best or best_score <= 0:
        fallback = active or (styles[0]["id"] if styles else "")
        return fallback, "沒有特別吻合的風格卡，先用目前使用中的"
    return best, f"最接近的風格卡：{best_why}"


def refine(topic: str, notes: str = "", urls: list[str] | None = None, timeout: float = 45.0) -> dict | None:
    """Ask the model to judge the topic. Returns None when it cannot or is too slow.

    A short timeout is deliberate: this runs while the owner is looking at the dialog.
    """
    if not (topic or "").strip():
        return None
    sys = f"""你是內容企劃，依題目判斷這一集該怎麼設定。只輸出 JSON。
可選值：
- format：「short」直式短片 30–90 秒、「long」橫式長片 3–8 分鐘
- mode：news 新聞（需查證）、narrative 敘事（虛構但貼近現實）、fiction 自由創作（完全原創）
- rating：general 一般、suggestive 暗示、adult 成人
- form：{ "、".join(f"{k}={v}" for k, v in store.FORM_LABEL.items()) }
- source_urls：題目或筆記裡已經出現的網址，原樣列出；沒有就空陣列
- reasons：兩到三句說明你的判斷依據（給人看）
判斷原則：
- 題目若是在講已發生的事實、發布、數據、爭議 → mode=news。
- 題目若是虛構情境、角色、慾望、關係 → narrative 或 fiction。
- 只有明確的成人題材才給 adult；不確定就用 general，寧可保守。
- 成品形態要看題目本身適合什麼；沒有特別線索就用 video。
輸出：{{"format":"short|long","mode":"news|narrative|fiction","rating":"general|suggestive|adult",
"form":"<form>","source_urls":["..."],"reasons":["..."]}}"""
    prompt = f"# 題目\n{topic}\n\n# 使用者筆記\n{notes or '（無）'}\n\n# 已知連結\n" + "\n".join(urls or []) or "（無）"
    cfg = store.get_settings()["llm"]
    prev = cfg.get("timeout_s")
    try:
        # bound this call without touching the saved setting
        store.save_settings({**store.get_settings(), "llm": {**cfg, "timeout_s": timeout}})
        data = llm.complete_json("suggest", sys, prompt)
    except (llm.LLMError, ValueError, KeyError):
        return None
    finally:
        cur = store.get_settings()
        store.save_settings({**cur, "llm": {**cur["llm"], "timeout_s": prev}})
    if not isinstance(data, dict):
        return None
    return data


def suggest(topic: str, notes: str = "", urls: list[str] | None = None,
            idea_format: str | None = None, deep: bool = False) -> dict:
    """The settings to pre-fill: instant rules, optionally refined by the model."""
    ceiling = (store.get_channel().get("max_rating") or "general").strip().lower()
    base = heuristic(topic, notes, ceiling)
    if idea_format in ("short", "long"):
        base["format"] = idea_format
    given = [u for u in (urls or []) if str(u).startswith("http")]
    base["source_urls"] = list(dict.fromkeys(given + base["source_urls"]))

    out = dict(base)
    if deep:
        got = refine(topic, notes, base["source_urls"])
        if got:
            merged = {**base}
            for key in ("format", "mode", "rating", "form"):
                if got.get(key):
                    merged[key] = str(got[key]).strip().lower()
            if isinstance(got.get("reasons"), list):
                merged["reasons"] = [str(r)[:120] for r in got["reasons"]][:3]
            merged["by"] = "model"
            _valid(merged, ceiling)
            if merged.get("source_urls") is None:
                merged["source_urls"] = base["source_urls"]
            extra = [u for u in (got.get("source_urls") or []) if str(u).startswith("http")]
            merged["source_urls"] = list(dict.fromkeys(base["source_urls"] + extra))
            out = merged

    _valid(out, ceiling)
    styles = store.get_styles()["items"]
    style_id, why = pick_style(styles, out["rating"], out["form"], f"{topic} {notes}")
    out["style_id"] = style_id
    if not out.get("reasons"):
        out["reasons"] = []
    if why:
        out["reasons"] = [*out["reasons"], why]
    return out
