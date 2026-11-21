"""Offline demo responses so the whole pipeline (TTS, render, ffmpeg) can run without an LLM.
Content is clearly sample text; the UI labels mock mode."""
from __future__ import annotations

import json
import re


def _topic(prompt: str) -> str:
    m = re.search(r"# 題目\n(.+)", prompt)
    return m.group(1).strip() if m else "示範題目"


def respond(task: str, prompt: str) -> str:
    t = _topic(prompt)
    short = "直式短片" in prompt
    if task == "health":
        return "ok"
    if task == "radar":
        m = re.search(r"# 數量\n(\d+)–(\d+)", prompt)
        n = int(m.group(2)) if m else 5
        return json.dumps({"topics": [
            {"title": f"示範題目 {i}：本地 AI 工具新動態", "why": "示範模式產生", "source": "示範", "format": "short" if i % 2 else "long", "heat": "需求證"}
            for i in range(1, n + 1)]}, ensure_ascii=False)
    if task == "brief":
        return json.dumps({"directions": [
            {"id": k, "angle": f"{t}：{a}", "audience": "想跟上 AI 新聞的上班族", "why": "示範模式產生",
             "outline": ["發生了什麼", "為什麼重要", "你可以怎麼用"], "include": ["實際用法"], "exclude": ["過度技術細節"], "title_feel": a}
            for k, a in (("A", "三分鐘看懂重點"), ("B", "跟舊工具比一比"), ("C", "實際用起來怎麼樣"))],
            "stale_warnings": ["示範模式：內容未經查證"]}, ensure_ascii=False)
    if task in ("script", "revise"):
        n = 4 if short else 6
        styles = ["bigtype", "papercut", "corkboard", "clean"]
        tags = ["whoosh", "ding", "pop", "click"]
        scenes = []
        for i in range(n):
            scenes.append({
                "narration": f"這是示範講稿第 {i + 1} 段。我們用一句話講清楚{t}的第 {i + 1} 個重點，讓你不用花時間自己查。",
                "headline": f"重點 {i + 1}",
                "bullets": [f"示範要點 {i + 1}-1", f"示範要點 {i + 1}-2"],
                "style": styles[i % 4],
                "visual": "abstract technology illustration, soft studio light, clean background",
                "sfx": tags[i % len(tags)],
                "emotion": ["好奇", "沉穩", "興奮", "提醒"][i % 4],
            })
        return json.dumps({"working_title": f"{t}（示範）", "music": "warm lo-fi, soft piano, light drums, no vocals", "scenes": scenes}, ensure_ascii=False)
    if task.startswith("critique"):
        return json.dumps({"score": 8, "summary": "示範模式：自動通過", "issues": []}, ensure_ascii=False)
    if task == "package":
        return json.dumps({
            "titles": [{"text": f"{t}｜示範標題 {i}", "angle": a} for i, a in enumerate(["好奇", "數字", "衝突", "實用", "好奇", "實用"], 1)],
            "thumbnails": [{"main": "一次看懂", "sub": t[:12], "theme": th} for th in ("dark", "light", "dark", "light")],
            "description": f"{t}\n\n00:00 開場\n（示範說明欄）",
            "carousel": [{"heading": h, "body": "示範內容。"} for h in ("先看結論", "重點一", "重點二", "重點三", "追蹤看更多")],
            "fb_post": f"{t}（示範貼文）", "hashtags": ["#AI", "#示範"]}, ensure_ascii=False)
    if task == "pref_rule":
        m = re.search(r"# 使用者意見\n(.+)", prompt, re.S)
        return json.dumps({"category": "講稿語氣", "rule": (m.group(1).strip() if m else "")[:80]}, ensure_ascii=False)
    if task == "extract_style":
        m = re.search(r"# 指定風格名稱\n(.+)", prompt)
        name = m.group(1).strip() if m else "示範提煉風格"
        return json.dumps({
            "name": name,
            "icon": "🧪",
            "category": "科技數碼",
            "summary": "（示範模式提煉）直白切題、用具體實測場景取代抽象形容。",
            "tone": "像同事分享實測心得，句尾乾脆。",
            "opening": "先講遇到的真實卡關情境，再丟解法。",
            "structure": "痛點場景 → 工具解法 → 實測限制與結論。",
            "pacing": "短句推進，每 2 句給一個具體畫面或數字。",
            "words": ["老實說", "實測下來", "重點只有一個"],
            "avoid": ["在這個時代", "總而言之", "全方位賦能"],
        }, ensure_ascii=False)
    if task == "analyze_insights":
        return json.dumps({
            "headline": "（示範分析）實測痛點型短片互動密度較高，建議前 3 秒聚焦具體省時場景。",
            "suggestions": [
                {
                    "category": "開頭與節奏",
                    "rule": "短片前 3 秒直接丟出具體痛點情境，不鋪陳背景介紹。",
                    "evidence": "示範模式：痛點型題目完播與收藏表現最佳。",
                },
                {
                    "category": "標題",
                    "rule": "標題優先使用「痛點對比」或「可立即省下的步驟」角度。",
                    "evidence": "示範模式：疑問與實用角度點擊率高於純名詞介紹。",
                },
                {
                    "category": "縮圖",
                    "rule": "縮圖主標控制在 6 字以內，搭配對比鮮明的深色或淺色底。",
                    "evidence": "示範模式：字數精簡版本在資訊流辨識度更佳。",
                },
            ],
        }, ensure_ascii=False)
    return "{}"
