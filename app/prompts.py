"""Prompt builders. Every task returns JSON; the shapes are documented in each system prompt."""
from __future__ import annotations

import json

from . import store

STYLES = {
    "bigtype": "大字直接砸下來：新聞快訊、數字震撼",
    "papercut": "美勞課色紙剪貼：輕鬆解說、概念說明",
    "corkboard": "剪報貼在軟木板：整理多方說法、事件脈絡",
    "clean": "乾淨資訊卡：步驟、比較、清單",
}


def channel_block() -> str:
    c = store.get_channel()
    return (
        f"頻道名稱：{c['name'] or '（未填）'}\n主題：{c['topic']}\n目標觀眾：{c['audience']}\n"
        f"語氣：{c['tone']}\n對標帳號：{c['benchmarks']}\n禁區：{c['taboo']}"
    )


def base_system() -> str:
    return (
        "你是一人自媒體「內容工廠」裡的專業 agent。用繁體中文（台灣用語）寫作。"
        "你做苦工，使用者做決定：給選項時要讓使用者「只需要挑一個」。"
        "事實要有依據，不確定或可能過時的資訊要標出來，不要編造數字、日期或引言。\n\n"
        f"# 頻道定位\n{channel_block()}\n\n# 使用者品味紀錄（必須遵守）\n{store.prefs_text()}"
    )


def radar(seeds: str) -> tuple[str, str]:
    sys = base_system() + """

# 任務：選題雷達
從使用者提供的線索（連結內容、筆記、熱門話題）整理候選題目。
輸出：{"topics":[{"title":"題目","why":"為什麼適合本頻道","source":"來源或依據","format":"long|short","heat":"熱度依據"}]}
給 5–8 個，依推薦程度排序。沒有依據的熱度不要編，寫「需求證」。"""
    return sys, f"# 線索\n{seeds}"


def brief(ep: dict, sources: str) -> tuple[str, str]:
    sys = base_system() + """

# 任務：方向簡報
同一個題目可以做成很不一樣的內容。給 3–4 個切入方向。
輸出：{"directions":[{"id":"A","angle":"一句話切角","audience":"給誰看","why":"為什麼適合本頻道","outline":["段落1","段落2"],"include":["要講"],"exclude":["不講"],"title_feel":"標題感"}],"stale_warnings":["可能過時或需求證的資訊"]}"""
    prompt = f"# 題目\n{ep['topic']}\n\n# 格式\n{fmt_desc(ep)}\n\n# 使用者筆記\n{ep.get('notes') or '（無）'}\n\n# 蒐集到的資料\n{sources or '（無外部資料，請依常識並標註需求證之處）'}"
    return sys, prompt


def fmt_desc(ep: dict) -> str:
    if ep["format"] == "short":
        return "直式短片 30–90 秒（講稿約 150–300 字），4–7 個畫面，第一句就要有鉤子。"
    return "橫式長片 3–8 分鐘（講稿約 900–2000 字），8–16 個畫面，開頭 15 秒內交代為什麼要看。"


SCRIPT_SHAPE = """輸出：{"working_title":"暫定標題","scenes":[{"narration":"這個畫面要念的講稿（口語、短句）","headline":"畫面大標（12 字內）","bullets":["畫面重點，最多 3 條，每條 18 字內"],"style":"bigtype|papercut|corkboard|clean"}]}
畫面風格可選：""" + "；".join(f"{k}={v}" for k, v in STYLES.items()) + """。
講稿要像真人說話：短句、口語、具體例子；不要 AI 腔、不要套話、不要過度排比。英文專有名詞保留原文。"""


def script(ep: dict, direction: dict, sources: str) -> tuple[str, str]:
    sys = base_system() + "\n\n# 任務：寫講稿\n依使用者選定的方向寫完整講稿，拆成畫面。\n" + SCRIPT_SHAPE
    prompt = (
        f"# 題目\n{ep['topic']}\n\n# 格式\n{fmt_desc(ep)}\n\n# 選定方向\n{json.dumps(direction, ensure_ascii=False)}\n\n"
        f"# 使用者補充（最優先）\n{ep.get('direction_notes') or '（無）'}\n\n# 資料\n{sources or '（無）'}"
    )
    return sys, prompt


CRITICS = {
    "fact": ("事實查核", "逐一檢查講稿的主張是否有資料支持，抓幻覺、過時資訊、無來源數字。"),
    "audience": ("觀眾理解", "以目標觀眾身份讀，標出聽不懂、跳太快、需要例子或比較的地方。"),
    "pacing": ("節奏", "檢查開頭鉤子、段落長短、無聊段落、結尾收束。"),
    "ai_voice": ("AI 腔獵人", "抓空話、套話、過度排比、翻譯腔、說教語氣，以及違反品味紀錄的句子。"),
}


def critique(role: str, ep: dict, scr: dict, sources: str) -> tuple[str, str]:
    name, job = CRITICS[role]
    sys = base_system() + f"""

# 任務：審稿（角色：{name}）
{job}
你只負責這個角色，不要評其他面向。嚴格打分，8 分以上代表可以直接上線。
輸出：{{"score":1-10 的整數,"summary":"一句話結論","issues":[{{"quote":"引用原句","problem":"問題","fix":"具體改法"}}]}}"""
    prompt = f"# 格式\n{fmt_desc(ep)}\n\n# 講稿\n{json.dumps(scr, ensure_ascii=False)}\n\n# 資料\n{sources or '（無）'}"
    return sys, prompt


def revise(ep: dict, scr: dict, reviews: dict, extra: str = "") -> tuple[str, str]:
    sys = base_system() + "\n\n# 任務：依審稿意見修稿\n保留好的部分，只修被指出的問題。\n" + SCRIPT_SHAPE
    prompt = (
        f"# 格式\n{fmt_desc(ep)}\n\n# 原講稿\n{json.dumps(scr, ensure_ascii=False)}\n\n"
        f"# 審稿意見\n{json.dumps(reviews, ensure_ascii=False)}\n\n# 使用者意見（最優先）\n{extra or '（無）'}"
    )
    return sys, prompt


def package(ep: dict, scr: dict, n_titles: int, n_thumbs: int) -> tuple[str, str]:
    sys = base_system() + f"""

# 任務：包裝
做標題候選、縮圖文案、說明欄、IG 輪播、FB 貼文。標題要與內容相符、不誇大、不騙點擊。
輸出：{{"titles":[{{"text":"標題","angle":"好奇|數字|衝突|實用"}}]（{n_titles} 個）,
"thumbnails":[{{"main":"縮圖大字 4–10 字","sub":"小字 12 字內","theme":"dark|light"}}]（{n_thumbs} 個，深淺都要有）,
"description":"YouTube 說明欄（含重點段落與時間軸佔位）",
"carousel":[{{"heading":"每頁標題","body":"每頁 1–3 句"}}]（5–7 頁，第一頁是封面鉤子，最後一頁是行動呼籲）,
"fb_post":"Facebook 貼文","hashtags":["#標籤"]}}"""
    prompt = f"# 題目\n{ep['topic']}\n\n# 格式\n{fmt_desc(ep)}\n\n# 定稿\n{json.dumps(scr, ensure_ascii=False)}"
    return sys, prompt


def pref_rule(stage: str, reason: str) -> tuple[str, str]:
    sys = """你把使用者的退件意見抽象成一條「下次可重用」的規則，用繁體中文，一句話，具體可檢查。
分類只能是：選題、方向與觀點、講稿語氣、開頭與節奏、畫面風格、標題、縮圖、配音與字幕。
輸出：{"category":"分類","rule":"規則"}"""
    return sys, f"# 階段\n{stage}\n\n# 使用者意見\n{reason}"
