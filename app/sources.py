"""Ordered source chains for visuals, narration, music and sound effects.

Owner's rule: when a local generator is not running, move on to a stock library (free first) and
only then to online generation. Nothing here ever starts ComfyUI, LM Studio or Strata: they share
one GPU pool and loading two at once can freeze the box.

Each category has a chain of source ids, tried in order:

    畫面 visuals  h3video → comfy → stock → slides
    配音 voice    audiocpp → edge → gemini
    音樂 music    audiocpp → openverse → lyria
    音效 sfx      library → freesound

Old settings still work: `visuals.source`, `music.provider`, `tts.base_url` and
`sfx.stock_fallback` derive the default chain. A category's own `chain` list wins when set.

The assembly step probes every source once at start-up (2–4 s each, cached ~30 s), writes the
plan to the log and to verify.json, and keeps a per-episode breaker: a source that fails twice in
a row is skipped for the rest of the episode, so n scenes never cost n timeouts.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, wait as fut_wait

from . import comfy, cost, h3video, music, sfx, stock, stock_audio, store

KINDS = ["visuals", "voice", "music", "sfx"]

LABEL = {
    "h3video": "MiniMax-H3 影片", "comfy": "ComfyUI 生圖", "stock": "實拍素材", "slides": "字卡",
    "audiocpp": "audio.cpp", "edge": "Edge TTS", "gemini": "Gemini TTS",
    "openverse": "Openverse", "lyria": "Lyria",
    "library": "音效庫", "freesound": "Freesound",
}
KIND_LABEL = {"visuals": "畫面", "voice": "配音", "music": "音樂", "sfx": "音效"}

# Sources that cost money. They stay out of the chain unless the owner allows a paid fallback,
# and even then they go last and only after cost.decide says yes.
PAID = {"lyria": "music", "gemini": "voice"}

DEFAULT_CHAINS = {
    "visuals": ["h3video", "comfy", "stock", "slides"],
    "voice": ["audiocpp", "edge", "gemini"],
    "music": ["audiocpp", "openverse", "lyria"],
    "sfx": ["library", "freesound"],
}

PROBE_TIMEOUT_S = 4.0      # per probe; short enough that a dead local server costs nothing
PROBE_TTL_S = 30.0         # probe results reused within this window
BREAK_AFTER = 2            # consecutive failures before a source is skipped for the episode

_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _tmo() -> float:
    try:
        return min(10.0, max(1.0, float(cfg().get("probe_timeout_s") or PROBE_TIMEOUT_S)))
    except (TypeError, ValueError):
        return PROBE_TIMEOUT_S


def _ttl() -> float:
    try:
        return max(1.0, float(cfg().get("probe_ttl_s") or PROBE_TTL_S))
    except (TypeError, ValueError):
        return PROBE_TTL_S


# ---------- configuration ----------

def cfg() -> dict:
    return store.get_settings().get("sources") or {}


def allow_paid(kind: str) -> bool:
    c = cfg()
    val = c.get(f"{kind}_allow_paid")
    if val is None:
        val = c.get("allow_paid_fallback")
    return bool(val)


def _legacy(kind: str) -> list[str]:
    """Chain derived from the older single-source settings."""
    s = store.get_settings()
    if kind == "visuals":
        v = (s["visuals"].get("source") or "slides").lower()
        if v == "h3video":
            return ["h3video", "comfy", "stock", "slides"]
        if v == "comfy":
            return ["comfy", "stock", "slides"]
        if v in ("stock", "mix"):
            return ["stock", "comfy", "slides"] if v == "mix" else ["stock", "slides"]
        return ["slides"]
    if kind == "voice":
        if (s["tts"].get("base_url") or "").strip():
            return ["audiocpp", "edge", "gemini"]
        return ["edge", "gemini"]
    if kind == "music":
        p = (s["music"].get("provider") or "audiocpp").lower()
        if p == "lyria":
            return ["lyria", "openverse"]
        if p == "openverse":
            return ["openverse", "audiocpp"]
        return ["audiocpp", "openverse", "lyria"]
    if kind == "sfx":
        return ["library", "freesound"] if s["sfx"].get("stock_fallback", True) else ["library"]
    return []


SECTION = {"visuals": "visuals", "voice": "tts", "music": "music", "sfx": "sfx"}

# 分級 → 該分級下不能用的來源。免費實拍素材（Pexels／Pixabay）的授權不涵蓋成人或暗示性用途，
# 而且那兩個庫是公開可搜尋的，所以 suggestive 以上一律排除。
RATING_BLOCKED = {
    "suggestive": {"stock"},
    "adult": {"stock"},
}


def rating_allowed(src: str, rating: str) -> bool:
    """這個來源在這個分級下能不能用。"""
    return src not in RATING_BLOCKED.get((rating or "general").strip().lower(), set())


def _raw_chain(kind: str) -> list[str]:
    """The configured chain, with paid sources kept out unless the owner allowed them.

    Accepted places for the list: `sources.<kind>.chain` (settings page), `sources.chains.<kind>`,
    or the section's own field (`visuals.chain`, `tts.chain`, `music.chain`, `sfx.chain`).
    """
    raw = ((cfg().get(kind) or {}).get("chain")
           or (cfg().get("chains") or {}).get(kind)
           or (store.get_settings().get(SECTION[kind]) or {}).get("chain"))
    out = [str(x).strip().lower() for x in (raw or _legacy(kind)) if str(x).strip()]
    out = [x for i, x in enumerate(out) if x in LABEL and x not in out[:i]]
    if not allow_paid(kind):
        # an explicitly chosen paid source (e.g. music.provider = lyria) stays; it still goes
        # through cost.decide and the approval gate. Paid sources only as a fallback need the switch.
        out = [x for x in out if PAID.get(x) != kind or x == out[0]]
    if kind == "visuals" and not out:
        out = ["slides"]           # slides always works: Pillow needs no service
    return out


def chain(kind: str, rating: str = "general") -> list[str]:
    """The chain for one category at one rating: configured sources minus the ones this rating blocks."""
    return [s for s in _raw_chain(kind) if rating_allowed(s, rating)]


def excluded_by_rating(kind: str, rating: str) -> list[str]:
    """Which configured sources this rating removes from the chain (recorded in the episode's plan)."""
    return [s for s in _raw_chain(kind) if not rating_allowed(s, rating)]



# ---------- probes ----------

def _probe_visuals(src: str) -> dict:
    if src == "slides":
        return {"ok": True, "detail": "免服務（Pillow 字卡）"}
    if src == "stock":
        st = stock.status()
        return {"ok": bool(st["providers"]), "detail": ("金鑰就緒：" + "、".join(st["providers"]))
                if st["providers"] else "沒有 Pexels／Pixabay 金鑰"}
    if src == "comfy":
        return comfy.health(timeout=_tmo())
    if src == "h3video":
        if not h3video.cfg().get("enabled", True):
            return {"ok": False, "detail": "MiniMax-H3 影片已在設定關閉"}
        return comfy.health(timeout=_tmo())
    return {"ok": False, "detail": "未知來源"}


def _probe_voice(src: str) -> dict:
    if src == "audiocpp":
        h = store.get_settings()["tts"]
        try:
            import httpx
            r = httpx.get(h["base_url"].rstrip("/") + "/v1/models", timeout=_tmo())
            r.raise_for_status()
            ids = [m.get("id") for m in r.json().get("data", [])]
        except Exception as e:  # noqa: BLE001 - any failure means "not usable"
            return {"ok": False, "detail": f"audio.cpp 連不上：{type(e).__name__}"}
        return {"ok": h["model"] in ids, "detail": "就緒" if h["model"] in ids else f"伺服器上沒有 {h['model']}"}
    if src == "edge":
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return {"ok": False, "detail": "沒有 edge-tts 套件（pip install edge-tts）"}
        return {"ok": True, "detail": "免金鑰（微軟 Edge 端點；聲音與 audio.cpp 不同）"}
    if src == "gemini":
        key, name = _gemini_key()
        return {"ok": bool(key), "detail": "金鑰就緒（計費）" if key else f"沒有環境變數 {name}"}
    return {"ok": False, "detail": "未知來源"}


def _probe_music(src: str) -> dict:
    if src == "audiocpp":
        try:
            import httpx
            base = (music.cfg().get("base_url") or store.get_settings()["tts"]["base_url"]).rstrip("/")
            r = httpx.get(base + "/v1/models", timeout=_tmo())
            r.raise_for_status()
            rows = r.json().get("data", [])
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": f"audio.cpp 連不上：{type(e).__name__}"}
        # same rule as music.model_id: any installed music generator (not the sfx model) will do
        mus = [m for m in rows if m.get("task") == "gen" and (m.get("family") or "") != "moss_soundeffect"]
        model = music.model_id(base)
        return {"ok": bool(mus), "detail": f"模型 {model}" if mus else f"伺服器上沒有音樂模型 {model}"}
    if src == "openverse":
        # No request here: the anonymous quota is 20/min and 200/day, so keep it for real fetches.
        return {"ok": True, "detail": "免金鑰（授權曲庫；抓不到會往下一順位）"}
    if src == "lyria":
        key, name = music.lyria_key()
        return {"ok": bool(key), "detail": "金鑰就緒（計費）" if key else f"沒有環境變數 {name}"}
    return {"ok": False, "detail": "未知來源"}


def _probe_sfx(src: str) -> dict:
    if src == "library":
        return {"ok": True, "detail": f"音效庫 {sum(len(v) for v in sfx.index().values())} 個檔"}
    if src == "freesound":
        key = stock_audio.keys().get("freesound") or ""
        return {"ok": bool(key), "detail": "金鑰就緒" if key else "沒有 FREESOUND_API_KEY"}
    return {"ok": False, "detail": "未知來源"}


_PROBES = {"visuals": _probe_visuals, "voice": _probe_voice, "music": _probe_music, "sfx": _probe_sfx}


def _probe_one(kind: str, src: str) -> dict:
    key = (kind, src)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _ttl():
        return dict(hit[1])
    try:
        res = _PROBES[kind](src)
    except Exception as e:  # noqa: BLE001 - a probe must never raise
        res = {"ok": False, "detail": f"探測失敗：{type(e).__name__}: {e}"}
    res.setdefault("ok", False)
    res.setdefault("detail", "")
    _cache[key] = (time.time(), dict(res))
    return res


def _probe_pairs(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """Probe (kind, source) pairs in parallel: one 2–4 s budget for the whole set."""
    out: dict[tuple[str, str], dict] = {}
    if not pairs:
        return out
    with ThreadPoolExecutor(max_workers=len(pairs), thread_name_prefix="probe") as ex:
        futs = {ex.submit(_probe_one, k, s): (k, s) for k, s in pairs}
        done, pending = fut_wait(futs, timeout=_tmo() + 2)
        for f in done:
            try:
                out[futs[f]] = f.result()
            except Exception as e:  # noqa: BLE001
                out[futs[f]] = {"ok": False, "detail": f"探測失敗：{e}"}
        for f in pending:
            out[futs[f]] = {"ok": False, "detail": "探測逾時"}
    return out


def probe(kind: str, chain_: list[str] | None = None) -> dict[str, dict]:
    """Probe every source of a category in parallel; returns {source: {ok, detail}}."""
    srcs = chain_ if chain_ is not None else chain(kind)
    got = _probe_pairs([(kind, s) for s in srcs])
    return {s: got[(kind, s)] for s in srcs}  # keep chain order


# ---------- per-episode state ----------

class Breaker:
    """Same-episode circuit breaker: BREAK_AFTER consecutive failures and the source is out."""

    def __init__(self, limit: int = BREAK_AFTER):
        self.limit = limit
        self._n: dict[str, int] = {}
        self._open: set[str] = set()

    def ok(self, src: str) -> bool:
        return src not in self._open

    def fail(self, src: str) -> None:
        self._n[src] = self._n.get(src, 0) + 1
        if self._n[src] >= self.limit:
            self._open.add(src)

    def success(self, src: str) -> None:
        self._n[src] = 0

    def trip(self, src: str) -> None:
        """Open at once, for failures that will not heal within the episode."""
        self._open.add(src)

    def open_sources(self) -> list[str]:
        return sorted(self._open)


class Plan:
    """What was probed at start-up and which source each category will try first."""

    def __init__(self, chains: dict[str, list[str]], probes: dict[str, dict[str, dict]],
                 excluded: dict[str, list[str]] | None = None):
        self.chains = chains
        self.probes = probes
        # sources the episode's rating removed from the chain (recorded so the plan shows why)
        self.excluded = excluded or {}

    def usable(self, kind: str) -> list[str]:
        pr = self.probes.get(kind) or {}
        return [s for s in self.chains.get(kind, []) if (pr.get(s) or {}).get("ok")]

    def chosen(self, kind: str) -> str:
        u = self.usable(kind)
        return u[0] if u else ""

    def line(self, kind: str) -> str:
        pr = self.probes.get(kind) or {}
        rows = [f"{LABEL.get(s, s)} {'✓' if (pr.get(s) or {}).get('ok') else '✗'}" for s in self.chains.get(kind, [])]
        c = self.chosen(kind)
        out = f"{KIND_LABEL[kind]}：" + (" → ".join(rows) or "（無來源）") + \
              (f"；本集先用 {LABEL.get(c, c)}" if c else "；沒有可用來源")
        ex = self.excluded.get(kind) or []
        if ex:
            out += f"；分級限制排除 {'、'.join(LABEL.get(s, s) for s in ex)}"
        return out

    def summary(self) -> str:
        return "；".join(self.line(k) for k in KINDS if self.chains.get(k))

    def to_dict(self) -> dict:
        return {k: {"chain": self.chains.get(k, []), "probe": self.probes.get(k, {}),
                    "chosen": self.chosen(k), "excluded": self.excluded.get(k, [])}
                for k in KINDS if self.chains.get(k)}



class Report:
    """What each category actually used, and every fallback that happened."""

    def __init__(self, first: dict[str, str] | None = None):
        self.used: dict[str, dict[str, int]] = {}
        self.notes: list[str] = []
        self.first_failed: list[str] = []
        self.first: dict[str, str] = dict(first or {})   # the source the owner's setting asked for

    def set_first(self, kind: str, src: str) -> None:
        if src:
            self.first.setdefault(kind, src)

    def wanted(self, kind: str, plan: "Plan") -> str:
        """The intended source: whatever the setting named, else the first one that was up."""
        if self.first.get(kind):
            return self.first[kind]
        return next((s for s in plan.chains.get(kind, [])
                     if (plan.probes.get(kind, {}).get(s) or {}).get("ok")), "")

    def use(self, kind: str, src: str, n: int = 1) -> None:
        if not src or n <= 0:
            return
        d = self.used.setdefault(kind, {})
        d[src] = d.get(src, 0) + n

    def note(self, msg: str) -> None:
        if msg and msg not in self.notes:
            self.notes.append(msg)

    def primary_failed(self, src: str) -> None:
        if src and src not in self.first_failed:
            self.first_failed.append(src)

    def fallbacks(self, kind: str, plan: Plan) -> list[dict]:
        """One row per source that handled part of the work and was not the intended first pick."""
        used = self.used.get(kind) or {}
        first_ok = self.wanted(kind, plan)
        rows = []
        for src, n in used.items():
            if src == first_ok:
                continue
            why = ""
            probe = (plan.probes.get(kind) or {}).get(first_ok) or {}
            if src in self.first_failed:
                why = "中途失敗"
            elif first_ok and not probe.get("ok", True):
                why = "未開"
            rows.append({"source": src, "label": LABEL.get(src, src), "n": n, "reason": why})
        return rows

    def badges(self, plan: Plan, total: int) -> list[dict]:
        """Human line per category, e.g. 「畫面：ComfyUI 未開，改用實拍素材 8/10」."""
        out = []
        for kind in KINDS:
            used = self.used.get(kind) or {}
            if not used:
                continue
            first_ok = self.wanted(kind, plan)
            ok_part, groups = [], {}
            for src, n in used.items():
                label = LABEL.get(src, src) + ("" if kind == "music" else f" {n}/{total}")
                if src == first_ok:
                    ok_part.append(label)
                    continue
                probe = (plan.probes.get(kind) or {}).get(first_ok) or {}
                if src in self.first_failed:
                    why = f"{LABEL.get(first_ok or src, first_ok or src)} 中途失敗"
                elif first_ok and not probe.get("ok", True):
                    why = f"{LABEL.get(first_ok, first_ok)} 未開"
                elif kind == "sfx" and src == "freesound":
                    why = "音效庫缺這個標籤"
                else:
                    why = "降級"
                groups.setdefault(why, []).append(label)
            parts = ok_part + [f"{why}，改用{'、'.join(v)}" for why, v in groups.items()]
            if groups:
                out.append({"kind": kind, "label": KIND_LABEL[kind], "text": "；".join(parts)})
        return out


def _gemini_key() -> tuple[str, str]:
    name = ((store.get_settings().get("tts") or {}).get("gemini_key_env") or "GEMINI_API_KEY").strip()
    return os.environ.get(name, ""), name


def start(kinds: list[str] | None = None, rating: str = "general") -> tuple[Plan, Breaker]:
    """Probe the chains once, before any expensive work. Returns the plan and a fresh breaker.

    `rating` removes the sources that rating may not use (free stock footage above general);
    the removed ones are recorded in the plan so the episode shows why.
    """
    kinds = kinds or KINDS
    chains = {k: chain(k, rating) for k in kinds}
    excluded = {k: excluded_by_rating(k, rating) for k in kinds}
    excluded = {k: v for k, v in excluded.items() if v}
    got = _probe_pairs([(k, s) for k in kinds for s in chains[k]])  # every category at once
    probes = {k: {s: got[(k, s)] for s in chains[k]} for k in kinds}
    return Plan(chains, probes, excluded), Breaker(int(cfg().get("breaker_after") or BREAK_AFTER))


def overview(probe_all: bool = False) -> dict:
    """Settings page: the chains plus (optionally) live health of every source."""
    chains = {k: chain(k) for k in KINDS}
    if probe_all:  # one pass over every category, so the settings page waits ~one probe, not four
        got = _probe_pairs([(k, s) for k in KINDS for s in chains[k]])
        probes = {k: {s: got[(k, s)] for s in chains[k]} for k in KINDS}
    else:
        probes = {k: {} for k in KINDS}
    kinds = {}
    for k in KINDS:
        kinds[k] = {"label": KIND_LABEL[k], "chain": chains[k], "allow_paid": allow_paid(k),
                    "probe": probes[k],
                    # which sources this rating removes from the chain (per rating)
                    "blocked_by_rating": {r: [s for s in chains[k] if s in RATING_BLOCKED.get(r, set())]
                                          for r in store.RATINGS if RATING_BLOCKED.get(r)}}
    return {"kinds": kinds, "probe_timeout_s": _tmo(), "probe_ttl_s": _ttl(),
            "breaker_after": int(cfg().get("breaker_after") or BREAK_AFTER),
            "allow_paid_fallback": bool(cfg().get("allow_paid_fallback", False))}


# ---------- visuals ----------

def visual_batches(plan: Plan, br: Breaker, scenes: list[dict], vertical: bool,
                   fetch: dict, log, eid: str, report: "Report | None" = None) -> dict:
    """Fill scene backgrounds from the chain, one source for all remaining scenes at a time.

    `fetch` is the pipeline's per-source callable dict; this module only decides the order.
    Returns {index: {"kind": "h3video"|"stock"|"comfy", "path": Path, "meta": dict}}.
    `report` (optional) is credited with one use per scene and per source.
    """
    got: dict[int, dict] = {}
    for src in plan.chains.get("visuals", []):
        todo = [i for i in range(len(scenes)) if i not in got]
        if not todo or src == "slides":
            break
        pr = plan.probes["visuals"].get(src) or {}
        if not pr.get("ok") or not br.ok(src):
            if not pr.get("ok"):
                log(eid, f"畫面來源 {LABEL[src]} 不可用（{pr.get('detail') or '未探測'}），跳過")
            continue
        fn = fetch.get(src)
        if not fn:
            continue
        log(eid, f"畫面：{LABEL[src]} 處理 {len(todo)}/{len(scenes)} 段")
        for i in todo:
            if not br.ok(src):
                log(eid, f"{LABEL[src]} 連續失敗，本集剩下的段落跳過它")
                break
            try:
                r = fn(scenes[i], i)
            except Exception as e:  # noqa: BLE001 - a dead source must never kill the episode
                br.fail(src)
                if report and src == report.wanted("visuals", plan):
                    report.primary_failed(src)
                log(eid, f"畫面 {i + 1} 用 {LABEL[src]} 失敗：{e}")
                continue
            if r:
                br.success(src)
                got[i] = r
                if report:
                    report.use("visuals", r["kind"])
            else:
                # "nothing found" is not a service failure: no breaker hit
                log(eid, f"畫面 {i + 1}：{LABEL[src]} 沒有可用結果")
        if src == "stock":
            found = sum(1 for v in got.values() if v["kind"] == "stock")
            log(eid, f"實拍素材 {found}/{len(scenes)} 段")
    return got


# ---------- narration ----------

class Narrator:
    """Speaks every chunk of the episode from one source, moving down the voice chain on failure."""

    def __init__(self, plan: Plan, br: Breaker, log, eid: str, total_chars: int = 0):
        self.plan = plan
        self.br = br
        self.log = log
        self.eid = eid
        self.order = [s for s in plan.usable("voice") if br.ok(s)]
        self.cur = self.order[0] if self.order else ""
        self.reason = ""
        self.paid_ok: dict[str, bool] = {}
        self.total_chars = total_chars
        self.used_chars = 0
        self._tried: set[str] = set()

    def usable(self) -> bool:
        return bool(self.cur)

    def _paid(self, src: str) -> tuple[bool, str]:
        """Gemini is paid: decide once per episode, and never wait for an approval."""
        if src in self.paid_ok:
            return self.paid_ok[src], ""
        key, name = _gemini_key()
        if not key:
            self.paid_ok[src] = False
            return False, f"沒有環境變數 {name}"
        model = ((store.get_settings().get("tts") or {}).get("gemini_model") or "gemini-2.5-flash-preview-tts").strip()
        usd = estimate_gemini_tts(self.total_chars or 1000, model)
        dec = cost.decide(usd)
        if dec == "allow":
            self.paid_ok[src] = True
            return True, ""
        self.paid_ok[src] = False
        why = ("本月雲端花費已達上限" if dec == "deny"
               else f"每集約 ${usd:.2f} 需要核准（門檻 ${float(cost.cfg().get('per_call_approval_usd') or 0.5):.2f}）")
        self.log(self.eid, f"配音：Gemini TTS {why}，這一集不用它")
        return False, why

    def say(self, text: str, out, emotion: str = ""):
        """Synthesise one chunk to `out`; falls through the chain and stays on the new source."""
        from . import media
        errors = []
        tries: dict[str, int] = {}
        prev = self.cur
        while self.order:
            self.order = [s for s in self.order if self.br.ok(s)]
            if not self.order:
                break
            src = self.cur if self.cur in self.order else self.order[0]
            if PAID.get(src) == "voice":
                ok, why = self._paid(src)
                if not ok:
                    errors.append(f"{LABEL[src]}：{why}")
                    self.order.remove(src)
                    continue
            try:
                p = media.tts_with(src, text, out, emotion=emotion)
            except media.MediaError as e:
                tries[src] = tries.get(src, 0) + 1
                errors.append(f"{LABEL[src]}：{e}")
                self.log(self.eid, f"配音來源 {LABEL[src]} 失敗：{e}")
                self.br.fail(src)
                if tries[src] >= 2:  # one retry per chunk, then move on even if the breaker is closed
                    self.order.remove(src)
                    self.reason = f"{LABEL[src]} 失敗"
                    self.cur = self.order[0] if self.order else ""
                continue
            self.br.success(src)
            self.used_chars += len(text)
            if PAID.get(src) == "voice":
                model = ((store.get_settings().get("tts") or {}).get("gemini_model")
                         or "gemini-2.5-flash-preview-tts").strip()
                try:  # accounting must never fail the render
                    cost.record("gemini_tts", 1, estimate_gemini_tts(len(text), model), self.eid, model)
                except Exception:  # noqa: BLE001
                    pass
            if src != prev:
                self.reason = self.reason or f"{LABEL.get(prev or src, prev or src)} 失敗"
                self.log(self.eid, f"配音改用 {LABEL[src]}（{self.reason}）")
            self.cur = src
            return src, p
        raise media.MediaError("配音沒有可用來源：" + "；".join(errors[-3:]))


def estimate_gemini_tts(chars: int, model: str = "") -> float:
    """Gemini TTS is billed per audio token; ~14 chars per second of speech. Default $0.06 per 1k chars."""
    prices = (cost.cfg().get("tts_prices") or {})
    per_1k = float(prices.get(model) or prices.get("gemini") or 0.06)
    return max(0.01, round(chars / 1000.0 * per_1k, 3))


# ---------- music ----------

def pick_music(plan: Plan, br: Breaker, seconds: float, style: str, eid: str, log,
               preapproved: str = "", report: "Report | None" = None) -> tuple:
    """Walk the music chain. Returns (path, source). Lyria only runs after cost.decide says yes."""
    errors = []
    for src in plan.chains.get("music", []):
        pr = plan.probes.get("music", {}).get(src) or {}
        if not pr.get("ok"):
            log(eid, f"音樂來源 {LABEL[src]} 未開（{pr.get('detail') or '未探測'}），跳過")
            continue
        if not br.ok(src):
            continue
        if PAID.get(src) == "music" and preapproved != src:
            usd = cost.price((music.cfg().get("lyria_model") or "lyria-3-clip-preview").strip())
            dec = "allow" if cost.episode_approved(eid) else cost.decide(usd)
            if dec != "allow":
                why = "本月雲端花費已達上限" if dec == "deny" else f"每首 ${usd:.2f} 需要核准"
                log(eid, f"音樂：{LABEL[src]} {why}，改用免費來源")
                errors.append(f"{LABEL[src]}：{why}")
                continue
        try:
            p = music.generate(seconds, style, eid=eid, source=src)
            br.success(src)
            return p, src
        except music.MusicError as e:
            errors.append(f"{LABEL[src]}：{e}")
            log(eid, f"音樂來源 {LABEL[src]} 失敗：{e}")
            br.fail(src)
            if report and src == report.wanted("music", plan):
                report.primary_failed(src)
    raise music.MusicError("；".join(errors[-3:]) or "沒有可用的音樂來源")


# ---------- sound effects ----------

def fill_sfx_tag(tag: str, br: Breaker, tried: set[str], log, eid: str, misses: dict | None = None) -> bool:
    """Library miss → fetch that one tag from Freesound right now (free, CC0)."""
    if not tag or tag in tried or not stock_audio.keys().get("freesound") or not br.ok("freesound"):
        return False
    tried.add(tag)
    try:
        got = stock_audio.fetch_sfx(tag, sfx.lib_dir())
    except Exception as e:  # noqa: BLE001 - network/API trouble: count it, stop after a few
        br.fail("freesound")
        log(eid, f"音效 {tag} 從 Freesound 補檔失敗：{e}")
        return False
    if got:
        br.success("freesound")
        log(eid, f"音效 {tag} 音效庫沒有，已從 Freesound 補檔")
        return True
    # "no suitable CC0 sound" is an answer, not an outage: only repeated misses close the breaker
    if misses is not None:
        misses["freesound"] = misses.get("freesound", 0) + 1
        if misses["freesound"] >= 3:
            br.trip("freesound")
    return False
