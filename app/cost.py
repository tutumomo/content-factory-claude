"""Paid cloud calls: a monthly cap, a per-call approval threshold, and a ledger.

Providers are recorded per call (one Lyria song = one unit). Price table lives in settings so a
provider's rate change is a settings edit, not a code change. The ledger is append-only JSONL.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import store


class CostDenied(RuntimeError):
    pass


def cfg() -> dict:
    return store.get_settings().get("cost") or {}


def dir_() -> Path:
    d = store.DATA / "cost"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path() -> Path:
    return dir_() / "ledger.jsonl"


def approvals_path() -> Path:
    return dir_() / "approvals.json"


def price(model: str) -> float:
    prices = cfg().get("prices") or {}
    return float(prices.get(model, 0.08))


def _month_prefix() -> str:
    return time.strftime("%Y-%m", time.localtime())


def month_sum() -> float:
    p = ledger_path()
    if not p.exists():
        return 0.0
    total = 0.0
    prefix = _month_prefix()
    for line in p.read_text("utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if str(row.get("ts", ""))[:7] == prefix:
            total += float(row.get("usd") or 0)
    return round(total, 4)


def decide(usd: float) -> str:
    cap = float(cfg().get("monthly_cap_usd") or 10.0)
    gate = float(cfg().get("per_call_approval_usd") or 0.5)
    if month_sum() + usd > cap:
        return "deny"
    if usd > gate:
        return "need_approval"
    return "allow"


def _approvals() -> dict:
    p = approvals_path()
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def approve(eid: str, usd: float) -> None:
    data = _approvals()
    data[eid] = {"ts": time.time(), "usd": usd}
    approvals_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def episode_approved(eid: str) -> bool:
    return eid in _approvals()


def consume(eid: str) -> None:
    data = _approvals()
    if data.pop(eid, None) is not None:
        approvals_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def record(provider: str, units: float, usd: float, eid: str = "", note: str = "") -> None:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "provider": provider, "units": units,
           "usd": round(float(usd), 4), "episode": eid, "note": note}
    with ledger_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def status() -> dict:
    c = cfg()
    return {"monthly_cap_usd": float(c.get("monthly_cap_usd") or 10.0),
            "per_call_approval_usd": float(c.get("per_call_approval_usd") or 0.5),
            "prices": c.get("prices") or {},
            "month": _month_prefix(), "spent_usd": month_sum(),
            "remaining_usd": round(float(c.get("monthly_cap_usd") or 10.0) - month_sum(), 4)}
