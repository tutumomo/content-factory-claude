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
        return json.dumps({"topics": [
            {"title": f"示範題目 {i}：本地 AI 工具新動態", "why": "示範模式產生", "source": "示範", "format": "short" if i % 2 else "long", "heat": "需求證"}
            for i in range(1, 6)]}, ensure_ascii=False)
    if task == "brief":
        return json.dumps({"directions": [
            {"id": k, "angle": f"{t}：{a}", "audience": "想跟上 AI 新聞的上班族", "why": "示範模式產生",
             "outline": ["發生了什麼", "為什麼重要", "你可以怎麼用"], "include": ["實際用法"], "exclude": ["過度技術細節"], "title_feel": a}
            for k, a in (("A", "三分鐘看懂重點"), ("B", "跟舊工具比一比"), ("C", "實際用起來怎麼樣"))],
            "stale_warnings": ["示範模式：內容未經查證"]}, ensure_ascii=False)
    if task in ("script", "revise"):
        n = 4 if short else 6
        styles = ["bigtype", "papercut", "corkboard", "clean"]
        scenes = []
        for i in range(n):
            scenes.append({
                "narration": f"這是示範講稿第 {i + 1} 段。我們用一句話講清楚{t}的第 {i + 1} 個重點，讓你不用花時間自己查。",
                "headline": f"重點 {i + 1}",
                "bullets": [f"示範要點 {i + 1}-1", f"示範要點 {i + 1}-2"],
                "style": styles[i % 4],
            })
        return json.dumps({"working_title": f"{t}（示範）", "scenes": scenes}, ensure_ascii=False)
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
    return "{}"
