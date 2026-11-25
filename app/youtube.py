"""YouTube: one-click Google sign-in (OAuth 2.0 loopback + PKCE) and resumable video upload.

Uses a Google OAuth *Desktop* client file (client_secret_*.json, "installed" type).
Tokens live in data/youtube/token.json (mode 600) and never leave this machine."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from . import store

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"

TOKEN_DIR = store.DATA / "youtube"
TOKEN_FILE = TOKEN_DIR / "token.json"
CHUNK = 8 * 1024 * 1024  # multiple of 256 KiB, as resumable uploads require

_pending: dict[str, dict] = {}   # state -> {verifier, redirect, client_file, t}
_lock = threading.Lock()


class YouTubeError(RuntimeError):
    pass


# ---------- client file ----------

def find_client_files() -> list[dict]:
    """Desktop OAuth client files found in the usual download / Drive folders."""
    home = Path.home()
    roots = [home / "下載", home / "Downloads", home / "GoogleDrive", store.DATA / "youtube"]
    seen, out = set(), []
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.glob("**/client_secret*.json"))[:50]:
            if p in seen or len(p.relative_to(root).parts) > 4:
                continue
            seen.add(p)
            info = _read_client(p)
            if info:
                out.append({"path": str(p), "project_id": info.get("project_id", "")})
    return out


def _read_client(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    c = d.get("installed")  # "web" clients need a registered redirect URI; only Desktop works here
    return c if c and c.get("client_id") and c.get("client_secret") else None


def _client(path: str | None = None) -> tuple[dict, str]:
    cfg = store.get_settings()["youtube"]
    path = path or cfg.get("client_file") or ""
    if not path:
        found = find_client_files()
        if not found:
            raise YouTubeError("找不到 Google OAuth 用戶端檔（client_secret_*.json，Desktop 類型）。"
                               "請到 Google Cloud Console 建立「電腦版應用程式」憑證並下載，再到設定填路徑。")
        path = found[0]["path"]
    c = _read_client(Path(path))
    if not c:
        raise YouTubeError(f"{path} 不是 Desktop 類型的 OAuth 用戶端檔")
    return c, path


# ---------- tokens ----------

def _load_token() -> dict | None:
    try:
        return json.loads(TOKEN_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _save_token(tok: dict) -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(tok, f, ensure_ascii=False)
    tmp.replace(TOKEN_FILE)


def _access_token() -> str:
    tok = _load_token()
    if not tok or not tok.get("refresh_token"):
        raise YouTubeError("還沒登入 Google 帳號，請先到 設定 → YouTube 按「用 Google 帳號登入」")
    if tok.get("access_token") and tok.get("expires_at", 0) > time.time() + 60:
        return tok["access_token"]
    c, _ = _client(tok.get("client_file"))
    r = httpx.post(TOKEN_URL, data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                                    "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200:
        err = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""
        if err == "invalid_grant":
            raise YouTubeError("Google 登入已失效（可能被撤銷，或 OAuth 同意畫面仍在「測試」狀態，權杖 7 天過期）。請重新登入。")
        raise YouTubeError(f"更新 Google 權杖失敗 HTTP {r.status_code}：{r.text[:200]}")
    j = r.json()
    tok.update(access_token=j["access_token"], expires_at=time.time() + int(j.get("expires_in", 3600)))
    _save_token(tok)
    return tok["access_token"]


# ---------- sign-in ----------

def begin_login(port: int) -> str:
    c, path = _client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    redirect = f"http://127.0.0.1:{port}/api/youtube/callback"
    with _lock:
        for k in [k for k, v in _pending.items() if v["t"] < time.time() - 900]:
            del _pending[k]
        _pending[state] = {"verifier": verifier, "redirect": redirect, "client_file": path, "t": time.time()}
    return AUTH_URL + "?" + urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent select_account",
        "include_granted_scopes": "true", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


def finish_login(state: str, code: str) -> dict:
    with _lock:
        p = _pending.pop(state, None)
    if not p:
        raise YouTubeError("登入流程已過期或來源不符，請回到內容工廠重新按登入")
    c, _ = _client(p["client_file"])
    r = httpx.post(TOKEN_URL, data={"client_id": c["client_id"], "client_secret": c["client_secret"], "code": code,
                                    "code_verifier": p["verifier"], "redirect_uri": p["redirect"],
                                    "grant_type": "authorization_code"}, timeout=30)
    if r.status_code != 200:
        raise YouTubeError(f"換取 Google 權杖失敗 HTTP {r.status_code}：{r.text[:300]}")
    j = r.json()
    if not j.get("refresh_token"):
        raise YouTubeError("Google 沒有回傳 refresh token，請到 Google 帳號的第三方存取權移除此應用程式後再登入")
    tok = {"refresh_token": j["refresh_token"], "access_token": j["access_token"],
           "expires_at": time.time() + int(j.get("expires_in", 3600)), "scope": j.get("scope", ""),
           "client_file": p["client_file"], "project_id": c.get("project_id", ""), "logged_in_at": time.time()}
    _save_token(tok)
    try:
        tok["channel"] = _my_channel()
    except YouTubeError as e:
        tok["channel"] = None
        tok["channel_error"] = str(e)
    _save_token(tok)
    return tok


def _my_channel() -> dict | None:
    r = httpx.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                  headers={"Authorization": f"Bearer {_access_token()}"}, timeout=30)
    _raise_api(r, "讀取頻道")
    items = r.json().get("items", [])
    if not items:
        return None
    sn = items[0]["snippet"]
    return {"id": items[0]["id"], "title": sn.get("title", ""), "thumb": sn.get("thumbnails", {}).get("default", {}).get("url", "")}


def status() -> dict:
    tok = _load_token()
    try:
        _, path = _client()
        client = {"ok": True, "path": path}
    except YouTubeError as e:
        client = {"ok": False, "error": str(e)}
    if not tok or not tok.get("refresh_token"):
        return {"logged_in": False, "client": client}
    return {"logged_in": True, "client": client, "channel": tok.get("channel"), "channel_error": tok.get("channel_error"),
            "project_id": tok.get("project_id"), "logged_in_at": tok.get("logged_in_at")}


def logout() -> None:
    tok = _load_token()
    if tok and tok.get("refresh_token"):
        try:
            httpx.post(REVOKE_URL, data={"token": tok["refresh_token"]}, timeout=15)
        except httpx.HTTPError:
            pass
    TOKEN_FILE.unlink(missing_ok=True)


# ---------- upload ----------

def _raise_api(r: httpx.Response, what: str) -> None:
    if r.status_code < 300:
        return
    reason, msg = "", r.text[:300]
    try:
        e = r.json()["error"]
        msg = e.get("message", msg)
        reason = (e.get("errors") or [{}])[0].get("reason", "")
    except (ValueError, KeyError, TypeError):
        pass
    if reason in ("accessNotConfigured", "SERVICE_DISABLED") or "has not been used" in msg:
        msg = "這個 Google Cloud 專案還沒啟用 YouTube Data API v3，請到 Cloud Console 的 API 程式庫啟用後重試。"
    elif reason == "quotaExceeded":
        msg = "YouTube API 今日配額用完（每次上傳約耗 1600 單位，預設每日 10000），明天再試。"
    elif reason == "uploadLimitExceeded":
        msg = "這個頻道今天上傳數量已達上限。"
    raise YouTubeError(f"{what}失敗 HTTP {r.status_code}：{msg}")


def video_id_from_url(url: str) -> str:
    """Video id from a YouTube URL the owner pasted (manual uploads do not set one)."""
    from . import yt_page

    return (yt_page.parse_url(url or "") or {}).get("id") or ""


def _count(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def video_stats(video_ids: list[str]) -> dict[str, dict]:
    """Public statistics for up to 50 videos per call: {video_id: {views, likes, comments}}."""
    ids = [v for v in dict.fromkeys(video_ids) if v]
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        r = httpx.get(f"{API}/videos", params={"part": "statistics", "id": ",".join(ids[i:i + 50])},
                      headers={"Authorization": f"Bearer {_access_token()}"}, timeout=30)
        _raise_api(r, "讀取影片成效")
        for item in r.json().get("items", []):
            s = item.get("statistics") or {}
            out[item.get("id") or ""] = {"views": _count(s.get("viewCount")),
                                         "likes": _count(s.get("likeCount")),
                                         "comments": _count(s.get("commentCount"))}
    return out


def _clean(s: str, n: int) -> str:
    return re.sub(r"[<>]", "", s or "").strip()[:n]


def _tags(hashtags: list[str]) -> list[str]:
    out, total = [], 0
    for h in hashtags or []:
        t = _clean(h.lstrip("#"), 60)
        if t and total + len(t) + 1 <= 480:
            out.append(t)
            total += len(t) + 1
    return out


def _publish_at(schedule: str | None) -> str | None:
    if not schedule:
        return None
    try:
        dt = datetime.fromisoformat(schedule)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive = this machine's local time
    if dt.timestamp() < time.time() + 15 * 60:  # YouTube rejects past / too-near publishAt
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _set_state(eid: str, **kw) -> None:
    ep = store.get_episode(eid)
    yt = {**(ep.get("youtube") or {}), **kw}
    store.update_episode(eid, youtube=yt)


def upload_blocked_reason(ep: dict) -> str:
    """Why this episode may not be auto-uploaded to YouTube; empty string when it may.

    YouTube's Data API has no writable 18+ field (`contentDetails.contentRating.ytRating`
    is ignored or rejected), and the platform's rules forbid this kind of content outright:
    an age restriction is not permission to publish. So the block is in code, not a setting.
    """
    rating = (ep.get("rating") or "general").strip().lower()
    if rating == "general":
        return ""
    return ("這一集的分級是「成人」，不支援自動上傳 YouTube：YouTube Data API 沒有可寫的 18+ "
            "欄位，而且平台規範禁止這類內容（設年齡限制不等於允許上架）。"
            "請改用本機發布包自行處理。")


def upload_episode(eid: str) -> None:
    """Worker task. Uploads publish/video.mp4 with metadata.json, then sets the thumbnail."""
    try:
        _upload(eid)
    except Exception as e:  # noqa: BLE001 — surface any failure on the episode
        _set_state(eid, status="error", error=str(e) if isinstance(e, YouTubeError) else f"{type(e).__name__}: {e}")
        store.log(eid, f"YouTube 上傳失敗：{e}")


def _upload(eid: str) -> None:
    ep = store.get_episode(eid)
    blocked = upload_blocked_reason(ep or {})
    if blocked:
        raise YouTubeError(blocked)
    pub = store.ep_dir(eid) / "publish"
    video = pub / "video.mp4"
    if not video.is_file():
        raise YouTubeError("找不到發布包裡的 video.mp4，請先核准成片")
    meta = json.loads((pub / "metadata.json").read_text("utf-8"))
    cfg = store.get_settings()["youtube"]
    publish_at = _publish_at(meta.get("schedule"))
    tags = _tags(meta.get("hashtags", []))
    desc = meta.get("description", "")
    if meta.get("hashtags"):
        desc = f"{desc}\n\n{' '.join(meta['hashtags'])}"
    body = {
        "snippet": {"title": _clean(meta.get("title", ""), 100) or "未命名影片", "description": _clean(desc, 5000),
                    "tags": tags, "categoryId": str(cfg.get("category_id") or "28")},
        "status": {"privacyStatus": "private" if publish_at else (cfg.get("privacy") or "private"),
                   "selfDeclaredMadeForKids": bool(cfg.get("made_for_kids")), "embeddable": True},
    }
    if cfg.get("language"):
        body["snippet"]["defaultLanguage"] = body["snippet"]["defaultAudioLanguage"] = cfg["language"]
    if publish_at:
        body["status"]["publishAt"] = publish_at
    size = video.stat().st_size
    _set_state(eid, status="uploading", progress=0.0, error=None, video_id=None, url=None, started_at=time.time())
    store.log(eid, f"開始上傳 YouTube（{size / 1e6:.1f} MB，{'排程 ' + meta['schedule'] if publish_at else body['status']['privacyStatus']}）")

    r = httpx.post(f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                   headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json; charset=UTF-8",
                            "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
                   json=body, timeout=60)
    _raise_api(r, "建立上傳工作")
    session = r.headers["Location"]

    offset, result, retries = 0, None, 0
    with open(video, "rb") as f:
        while result is None:
            f.seek(offset)
            chunk = f.read(CHUNK)
            end = offset + len(chunk) - 1
            try:
                r = httpx.put(session, content=chunk, timeout=600,
                              headers={"Authorization": f"Bearer {_access_token()}",
                                       "Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{end}/{size}"})
            except httpx.HTTPError as e:
                retries += 1
                if retries > 5:
                    raise YouTubeError(f"上傳連線一直中斷：{e}") from e
                time.sleep(2 ** retries)
                r = httpx.put(session, headers={"Authorization": f"Bearer {_access_token()}",
                                                "Content-Range": f"bytes */{size}"}, timeout=60)
            if r.status_code == 308:
                rng = r.headers.get("Range")
                offset = int(rng.rsplit("-", 1)[1]) + 1 if rng else 0
                _set_state(eid, progress=round(offset / size, 3))
            elif r.status_code in (200, 201):
                result = r.json()
            elif r.status_code in (500, 502, 503, 504):
                retries += 1
                if retries > 5:
                    _raise_api(r, "上傳影片")
                time.sleep(2 ** retries)
            else:
                _raise_api(r, "上傳影片")

    vid = result["id"]
    url = f"https://youtu.be/{vid}"
    _set_state(eid, status="processing", progress=1.0, video_id=vid, url=url)
    store.log(eid, f"YouTube 上傳完成：{url}")

    thumb = pub / "thumbnail.jpg"
    note = None
    if thumb.is_file() and thumb.stat().st_size <= 2 * 1024 * 1024:
        r = httpx.post(f"{UPLOAD_API}/thumbnails/set", params={"videoId": vid, "uploadType": "media"},
                       headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "image/jpeg"},
                       content=thumb.read_bytes(), timeout=120)
        if r.status_code >= 300:
            note = "縮圖沒設上（頻道需先完成電話驗證才能自訂縮圖），請到 YouTube Studio 手動上傳 thumbnail.jpg"
            store.log(eid, note + f"（HTTP {r.status_code}）")
    _set_state(eid, status="done", note=note, privacy=body["status"]["privacyStatus"], publish_at=publish_at,
               finished_at=time.time())
