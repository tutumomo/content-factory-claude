"""Service health for the status page: one short probe per dependency, run in parallel.

States: `ok` (usable), `warn` (down, but the pipeline has a fallback), `off` (blocks the
pipeline). Probes never raise and never start a service; they only report what is there.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, wait as fut_wait

from . import comfy, media, render, sfx, sources, stock, store, video

PROBE_TIMEOUT_S = 8.0


# ---------- probes ----------

def _probe_llm() -> dict:
    cfg = store.get_settings()["llm"]
    p = (cfg.get("provider") or "").strip().lower()
    if p == "mock":
        return {"ok": True, "detail": "離線示範模式（內容是範例，不是真的生成）",
                "hint": "正式出片前改成 Claude CLI 或 OpenAI 相容端點"}
    if p == "claude_cli":
        exe = shutil.which("claude")
        if not exe:
            return {"ok": False, "detail": "找不到 claude CLI",
                    "hint": "安裝 Claude Code 並登入，或改用 OpenAI 相容端點"}
        return {"ok": True, "detail": f"{exe}・模型 {cfg.get('claude_model') or '預設'}"}
    base = (cfg.get("openai_base_url") or "").rstrip("/")
    if not base:
        return {"ok": False, "detail": "沒有設定 OpenAI 相容端點",
                "hint": "設定頁填 base URL，例如 http://127.0.0.1:1234/v1"}
    try:
        import httpx

        r = httpx.get(base + "/models", timeout=3)
        r.raise_for_status()
        ids = [str(m.get("id")) for m in (r.json().get("data") or [])]
    except Exception as e:  # noqa: BLE001 - a probe must never raise
        return {"ok": False, "detail": f"連不上 {base}：{type(e).__name__}",
                "hint": "啟動 LM Studio／Strata 或本機閘道"}
    want = (cfg.get("openai_model") or "").strip()
    if want and want not in ids and not any(want in i for i in ids):
        return {"ok": True, "detail": f"{base}・{len(ids)} 個模型，沒有 {want}",
                "hint": f"端點上沒有 {want}，出片時會失敗；改模型名稱或先載入它"}
    return {"ok": True, "detail": f"{base}・{len(ids)} 個模型" + (f"・{want}" if want else "")}


def _probe_audiocpp() -> dict:
    h = media.tts_health(timeout=3)
    if not h.get("ok"):
        return {"ok": False, "detail": h.get("detail") or "audio.cpp 沒回應",
                "hint": "先開 audiocpp-webui（:8090）；沒開會自動改用 Edge TTS，音色不同"}
    detail = f"模型 {h.get('model') or '—'} 就緒"
    if h.get("needs_voice_ref"):
        return {"ok": True, "detail": detail, "hint": "這個模型需要參考聲音，請到設定頁選一個"}
    return {"ok": True, "detail": detail}


def _probe_comfy() -> dict:
    st = comfy.status(ttl=0, timeout=2)
    used = [s for s in sources.chain("visuals") if s in ("comfy", "h3video")]
    if st.get("ok"):
        return {"ok": True, "detail": (st.get("detail") or "就緒")
                + ("・畫面來源會用到" if used else "・目前畫面來源不會用到")}
    return {"ok": False, "detail": st.get("detail") or "連不上 ComfyUI",
            "hint": "啟動 ComfyUI（:8188）；沒開會自動往素材庫／字卡降級"}


def _probe_ffmpeg() -> dict:
    exe = shutil.which("ffmpeg")
    if not exe:
        return {"ok": False, "detail": "找不到 ffmpeg",
                "hint": "brew install ffmpeg-full，然後 brew link --overwrite ffmpeg-full"}
    try:
        r = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=4)
        out = r.stdout
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"執行 ffmpeg 失敗：{type(e).__name__}"}
    if " subtitles " not in out:
        return {"ok": False, "detail": f"{exe} 沒有 libass（不能燒字幕）",
                "hint": "brew link --overwrite ffmpeg-full（Homebrew 的 ffmpeg 沒編 libass）"}
    return {"ok": True, "detail": f"{exe}・含 libass"}


def _probe_fonts() -> dict:
    try:
        f = render.font(12, "Bold")
        return {"ok": True, "detail": "・".join(f.getname())}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "detail": f"找不到 Noto Sans CJK（{type(e).__name__}）",
                "hint": "brew install --cask font-noto-sans-cjk"}


def _probe_remotion() -> dict:
    st = video.available()
    if st.get("ok"):
        return {"ok": True, "detail": st.get("detail") or "就緒"}
    return {"ok": False, "detail": st.get("detail") or "Remotion 不可用",
            "hint": "cd remotion && npm install；沒安裝會自動退回 ffmpeg"}


def _probe_ytdlp() -> dict:
    exe = shutil.which("yt-dlp")
    if exe:
        return {"ok": True, "detail": exe}
    if importlib.util.find_spec("yt_dlp"):
        return {"ok": True, "detail": "Python 套件 yt_dlp"}
    return {"ok": False, "detail": "找不到 yt-dlp",
            "hint": "pip install yt-dlp；YouTube 連結與參考影片分析會失敗"}


def _probe_stock() -> dict:
    st = stock.status()
    providers = st.get("providers") or []
    if providers:
        return {"ok": True, "detail": "金鑰就緒：" + "、".join(providers)}
    return {"ok": False, "detail": "沒有 Pexels／Pixabay 金鑰",
            "hint": "設定頁填入金鑰的環境變數名稱；沒有金鑰就用字卡／生圖"}


def _probe_sfx() -> dict:
    st = sfx.status()
    total = int(st.get("total") or 0)
    if total:
        return {"ok": True, "detail": f"{total} 個音效檔・{st.get('dir')}"}
    return {"ok": False, "detail": "音效庫是空的",
            "hint": "設定頁批次生成，或按「從 Freesound 補音效」"}


def _probe_youtube() -> dict:
    # Not youtube.status(): that globs ~/Downloads and Google Drive to find the client file,
    # which can take minutes. The status page only needs to know whether a token exists.
    tok = store.DATA / "youtube" / "token.json"
    try:
        data = json.loads(tok.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    if data.get("refresh_token"):
        return {"ok": True, "detail": "已登入" + (f"・{data['channel']}" if data.get("channel") else "")}
    hint = "設定 → YouTube → 用 Google 帳號登入"
    if not (store.get_settings()["youtube"].get("client_file") or "").strip():
        hint = "先在設定頁指定 Google OAuth Desktop 用戶端檔（client_secret_*.json），再登入"
    return {"ok": False, "detail": "尚未登入 Google", "hint": hint}


def _probe_worker() -> dict:
    from . import pipeline

    b = pipeline.busy()
    cur = (b.get("current") or {}).get("kind")
    if cur:
        return {"ok": True, "detail": f"正在跑 {cur}・佇列 {b.get('queued', 0)} 件"}
    return {"ok": True, "detail": f"閒置・佇列 {b.get('queued', 0)} 件"}


# Probes live in a dict so tests can swap one without rebuilding the table.
PROBES = {
    "llm": _probe_llm, "ffmpeg": _probe_ffmpeg, "fonts": _probe_fonts, "worker": _probe_worker,
    "audiocpp": _probe_audiocpp, "comfy": _probe_comfy, "remotion": _probe_remotion,
    "ytdlp": _probe_ytdlp, "stock": _probe_stock, "sfx": _probe_sfx, "youtube": _probe_youtube,
}

# (id, label, role, blocks-the-pipeline-when-down)
SERVICES = (
    ("llm", "LLM 模型", "寫稿、方向、包裝、復盤", True),
    ("ffmpeg", "ffmpeg", "剪輯、合成、燒字幕", True),
    ("fonts", "中文字型", "字卡、縮圖、字幕", True),
    ("worker", "背景 worker", "排隊與各階段執行", True),
    ("audiocpp", "audio.cpp", "配音、對齊、背景音樂", False),
    ("comfy", "ComfyUI", "生圖、MiniMax-H3 影片", False),
    ("remotion", "Remotion", "動畫成片引擎", False),
    ("ytdlp", "yt-dlp", "YouTube 連結、參考影片分析", False),
    ("stock", "實拍素材金鑰", "Pexels／Pixabay 搜尋", False),
    ("sfx", "音效庫", "每畫面墊音效", False),
    ("youtube", "YouTube 登入", "一鍵上傳（選用）", False),
)


def _call(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - one broken probe must not blank the panel
        return {"ok": False, "detail": f"探測失敗：{type(e).__name__}: {e}"}


def services() -> dict:
    """Every dependency with its state, plus counts for the summary line."""
    rows: list[dict] = []
    # Not a `with` block: its __exit__ joins every thread, so one stuck probe would hold the
    # request (and the page) hostage long after the timeout.
    ex = ThreadPoolExecutor(max_workers=len(SERVICES), thread_name_prefix="health")
    futs = {ex.submit(_call, PROBES[sid]): (sid, label, role, required)
            for sid, label, role, required in SERVICES}
    done, pending = fut_wait(futs, timeout=PROBE_TIMEOUT_S)
    ex.shutdown(wait=False, cancel_futures=True)
    for f in done:
        sid, label, role, required = futs[f]
        res = f.result()
        ok = bool(res.get("ok"))
        rows.append({
            "id": sid, "name": label, "role": role, "ok": ok,
            "state": "ok" if ok else ("off" if required else "warn"),
            "detail": res.get("detail") or "",
            "hint": "" if ok else (res.get("hint") or ""),
        })
    for f in pending:
        sid, label, role, required = futs[f]
        rows.append({"id": sid, "name": label, "role": role, "ok": False,
                     "state": "off" if required else "warn",
                     "detail": "探測逾時", "hint": ""})
    order = {sid: i for i, (sid, *_rest) in enumerate(SERVICES)}
    rows.sort(key=lambda r: order.get(r["id"], 0))
    summary = {s: sum(1 for r in rows if r["state"] == s) for s in ("ok", "warn", "off")}
    summary["total"] = len(rows)
    return {"services": rows, "summary": summary, "checked": time.time()}
