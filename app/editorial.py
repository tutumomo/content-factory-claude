"""選題與求證的編輯方法論。

提示詞與判斷規則改寫自 AIHOT（https://github.com/KKKKhazix/AIHOT，MIT）的
`industry/prompts/`：寬召回預篩、事件注意力評分、同事件聚類、防幻覺與自足標題。
這裡只放可測試的流程與正規化；實際文字在 `prompts.py`，授權與改動說明見
`THIRD_PARTY.md`。
"""
from __future__ import annotations

import re
from typing import Callable

from . import llm, prompts

CompleteJSON = Callable[[str, str, str], object]

PREFILTER_LABELS = ("PASS", "BLOCK", "UNKNOWN")
SAME_EVENT_RELATIONS = ("SAME_OCCURRENCE", "SAME_STORY")
GROUP_MIN_CONFIDENCE = 0.6
TEASER_ONLY = (
    "重磅", "最新動態", "引發關注", "震驚", "必看", "劃時代", "顛覆",
    "Day 1", "Coming soon", "Just dropped",
)


def _call(complete: CompleteJSON | None, task: str, sys: str, pr: str):
    if complete is not None:
        return complete(task, sys, pr)
    return llm.complete_json(task, sys, pr)


def clamp_score(value) -> int | None:
    """0–100 integer, or None when the model did not give a usable number."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return max(0, min(100, n))


def normalize_prefilter(data) -> dict:
    """Any unexpected label falls back to UNKNOWN: keep the material for the owner."""
    if not isinstance(data, dict):
        return {"label": "UNKNOWN", "reason": "預篩沒有回覆，待補"}
    label = str(data.get("label") or "").strip().upper()
    if label not in PREFILTER_LABELS:
        label = "UNKNOWN"
    reason = str(data.get("reason") or "").strip()[:60]
    return {"label": label, "reason": reason or "沒有提供依據"}


def normalize_candidate(raw, idx: int) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = re.sub(r"\s+", " ", str(raw.get("title") or "")).strip()
    if not title:
        return None
    summary = re.sub(r"\s+", " ", str(raw.get("summary") or "")).strip()
    url = str(raw.get("url") or "").strip()
    source = str(raw.get("source") or "").strip()
    fmt = raw.get("format") if raw.get("format") in ("long", "short") else "short"
    return {
        "id": f"C{idx}",
        "title": title[:160],
        "summary": summary[:900],
        "source": source[:120] or ("來源不明" if not url else url),
        "url": url if url.startswith("http") else "",
        "format": fmt,
    }


def extract_candidates(text: str, n: int, complete: CompleteJSON | None = None) -> list[dict]:
    sys, pr = prompts.radar_candidates(text, n)
    data = _call(complete, "radar_candidates", sys, pr)
    rows = data.get("candidates") if isinstance(data, dict) else data
    out, seen = [], set()
    for raw in rows if isinstance(rows, list) else []:
        cand = normalize_candidate(raw, len(out) + 1)
        if not cand:
            continue
        key = cand["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
        if len(out) >= n:
            break
    return out


def prefilter_candidate(cand: dict, complete: CompleteJSON | None = None) -> dict:
    sys, pr = prompts.prefilter(cand)
    try:
        data = _call(complete, "prefilter", sys, pr)
    except llm.LLMError:
        return {"label": "UNKNOWN", "reason": "預篩失敗，待補"}
    return normalize_prefilter(data)


def score_candidate(cand: dict, complete: CompleteJSON | None = None) -> dict:
    sys, pr = prompts.selection_score(cand)
    try:
        data = _call(complete, "selection_score", sys, pr)
    except llm.LLMError:
        return {"attention_score": None, "score_reason": "評分失敗，待補"}
    if not isinstance(data, dict):
        return {"attention_score": None, "score_reason": "評分格式錯誤，待補"}
    score = clamp_score(data.get("attentionScore"))
    reason = re.sub(r"\s+", " ", str(data.get("reason") or "")).strip()[:80]
    if score is None:
        return {"attention_score": None, "score_reason": reason or "評分失敗，待補"}
    return {"attention_score": score, "score_reason": reason or "模型沒有留下依據"}


def _score_key(cand: dict) -> tuple[int, float]:
    s = cand.get("attention_score")
    return (1, -s) if isinstance(s, int) else (0, 0.0)


def group_candidates(cands: list[dict], complete: CompleteJSON | None = None) -> list[dict]:
    """Greedy clustering: compare each candidate with the groups built so far.

    SAME_OCCURRENCE and SAME_STORY both join the group (a follow-up belongs to the
    same story); UNRELATED and ROUNDUP start a new group. Returns groups with an
    `id`, a representative title/summary, and every member plus its relation.
    """
    groups: list[dict] = []
    for cand in sorted(cands, key=_score_key):
        best = None
        if groups:
            sys, pr = prompts.group_batch(cand, groups)
            try:
                data = _call(complete, "group_batch", sys, pr)
            except llm.LLMError:
                data = {}
            decisions = data.get("decisions") if isinstance(data, dict) else []
            for d in decisions if isinstance(decisions, list) else []:
                if not isinstance(d, dict):
                    continue
                gid = str(d.get("id") or "")
                rel = str(d.get("relation") or "").strip().upper()
                try:
                    conf = float(d.get("confidence"))
                except (TypeError, ValueError):
                    conf = 0.0
                if rel not in SAME_EVENT_RELATIONS or conf < GROUP_MIN_CONFIDENCE:
                    continue
                if not any(g["id"] == gid for g in groups):
                    continue
                if best is None or conf > best[1]:
                    best = (gid, conf, rel)
        if best:
            gid, conf, rel = best
            group = next(g for g in groups if g["id"] == gid)
            group["members"].append({**cand, "relation": rel, "confidence": round(conf, 2)})
        else:
            groups.append({
                "id": f"G{len(groups) + 1}",
                "title": cand["title"],
                "summary": cand.get("summary", ""),
                "members": [{**cand, "relation": "NEW", "confidence": 1.0}],
            })
    return groups


def title_lint(text: str) -> list[str]:
    """Cheap self-contained-title lint; returned to the owner, never blocks."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    issues: list[str] = []
    if len(t) < 8:
        issues.append("太短，可能沒交代主體與動作")
    if re.fullmatch(r"v?\d+(?:\.\d+)+", t, re.I):
        issues.append("只有版本號，沒有主體")
    for word in TEASER_ONLY:
        if t == word or (t.startswith(word) and len(t) <= len(word) + 6):
            issues.append("只有 teaser，沒有主體與動作")
            break
    if t.endswith("？") and len(t) <= 12:
        issues.append("只有疑問，沒有主體與事實")
    return issues


def _unique(values) -> list[str]:
    seen, out = set(), []
    for v in values:
        v = str(v or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def build_radar_items(groups: list[dict], hi: int) -> list[dict]:
    items = []
    for g in groups:
        members = g["members"]
        rep = max(members, key=lambda m: m.get("attention_score") if isinstance(m.get("attention_score"), int) else -1)
        score = rep.get("attention_score")
        label = "PASS" if any(m.get("prefilter") == "PASS" for m in members) else "UNKNOWN"
        items.append({
            "title": rep["title"],
            "why": rep.get("score_reason") or "",
            "source": rep.get("source") or "",
            "urls": _unique(m.get("url") for m in members),
            "format": rep.get("format") or "short",
            "heat": f"注意力 {score}/100" if isinstance(score, int) else "待補（資料不足）",
            "attention_score": score,
            "score_reason": rep.get("score_reason") or "",
            "prefilter": label,
            "needs_more": label == "UNKNOWN",
            "group": g["id"],
            "group_size": len(members),
            "members": [
                {
                    "title": m["title"],
                    "source": m.get("source") or "",
                    "url": m.get("url") or "",
                    "attention_score": m.get("attention_score"),
                    "prefilter": m.get("prefilter") or "UNKNOWN",
                    "relation": m.get("relation") or "",
                }
                for m in sorted(members, key=_score_key)
            ],
        })
    items.sort(key=lambda x: (x["attention_score"] is None, -(x["attention_score"] or 0)))
    return items[:hi]


def radar_scored(seeds: str, lo: int, hi: int, cfg: dict | None = None,
                 complete: CompleteJSON | None = None) -> list[dict]:
    """Candidate → prefilter → attention score → same-event clustering → rank."""
    cfg = cfg or {}
    n = max(int(cfg.get("radar_candidates_max") or 12), hi)
    cands = extract_candidates(seeds, n, complete)
    if not cands:
        return []
    for cand in cands:
        if cfg.get("radar_prefilter", True):
            pre = prefilter_candidate(cand, complete)
        else:
            pre = {"label": "PASS", "reason": "預篩已關閉"}
        cand["prefilter"] = pre["label"]
        cand["prefilter_reason"] = pre["reason"]
    kept = [c for c in cands if c["prefilter"] != "BLOCK"]
    for cand in kept:
        cand.update(score_candidate(cand, complete))
    if cfg.get("radar_grouping", True):
        groups = group_candidates(kept, complete)
    else:
        groups = [{"id": f"G{i}", "title": c["title"], "summary": c.get("summary", ""),
                   "members": [{**c, "relation": "NEW", "confidence": 1.0}]}
                  for i, c in enumerate(kept, 1)]
    return build_radar_items(groups, hi)


def source_verdict(ep: dict, fetched: list[dict], cfg: dict | None = None,
                   complete: CompleteJSON | None = None) -> dict:
    """Decide whether the collected material is enough to write from.

    `fetched` rows are `{"url", "text", "failed"}`. A readable first-hand source or
    substantial user notes make the material sufficient; the LLM audit can only add
    gaps, never invent support. With `source_gate` on, the caller stops at the gate.
    """
    cfg = cfg or {}
    readable = [f for f in fetched if not f.get("failed") and len((f.get("text") or "").strip()) >= 200]
    notes = str(ep.get("notes") or "").strip()
    notes_ok = len(notes) >= 80
    min_readable = max(1, int(cfg.get("source_min_readable") or 1))
    sufficient = len(readable) >= min_readable or notes_ok
    if fetched:
        auto = sum(1 for f in readable if f.get("auto"))
        value = (f"{len(readable)}/{len(fetched)} 個連結可讀" + (f"（含自動搜尋 {auto} 個）" if auto else "")
                 + ("，另有使用者筆記" if notes_ok else ""))
    else:
        value = "沒有提供來源連結" + ("，只有使用者筆記" if notes_ok else "")
    gaps: list[str] = [] if sufficient else ["沒有可讀的一手來源，內容只能標註需求證"]
    note = ""
    audit: dict = {}
    if cfg.get("source_audit", True) and (fetched or notes):
        try:
            sys, pr = prompts.sources_audit(ep, fetched)
            data = _call(complete, "sources_audit", sys, pr)
            if isinstance(data, dict):
                audit = data
        except llm.LLMError:
            audit = {}
    if audit:
        # The audit cannot declare sufficiency without material to stand on.
        sufficient = bool(audit.get("sufficient")) and (len(readable) >= min_readable or notes_ok)
        gaps = _unique(list(audit.get("gaps") or []) + gaps)[:8]
        note = str(audit.get("note") or "").strip()[:200]
        failed = _unique(audit.get("failed") or [])
        if failed:
            value += f"，抓取失敗 {len(failed)} 個"
    if not sufficient and not gaps:
        gaps = ["沒有可讀的一手來源，內容只能標註需求證"]
    return {
        "ok": sufficient,
        "value": value,
        "gaps": gaps,
        "note": note,
        "readable": len(readable),
        "total": len(fetched),
    }
