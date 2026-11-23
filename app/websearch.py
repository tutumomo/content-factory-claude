"""Find candidate source links on the web when the owner gave too little material.

Engines, tried in order until one returns links:
- `claude`: `claude -p` with only the WebSearch tool. It plans its own queries from the topic,
  the notes and the open gaps, and is the best at picking first-hand pages (about 30 s). `auto`
  uses it whenever the `claude` command is installed, whatever the LLM provider; if it is not
  logged in it fails fast and the chain moves on.
- `bing`: keyless Bing HTML results for the topic (result links are unwrapped from /ck/a).
- `wikipedia`: zh.wikipedia search API (zh-tw pages); background material, not news.

DuckDuckGo's HTML endpoint was tested on 2026-11-23 and answered 202 with no results (bot
check), so it is not in the chain. Only the topic, notes and gaps go into the Claude prompt;
the Bing and Wikipedia queries are built from the topic alone.
"""
from __future__ import annotations

import base64
import html
import re
import shutil
from urllib.parse import parse_qs, quote, urlparse

import httpx

from . import llm, store

ENGINES = ("claude", "bing", "wikipedia")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
# pages that are search/login shells or need an account: fetching them yields no article text
SKIP_HOSTS = ("bing.com", "microsoft.com", "google.com", "facebook.com", "instagram.com",
              "threads.net", "x.com", "twitter.com", "tiktok.com", "linkedin.com", "pinterest.")


class SearchError(RuntimeError):
    pass


def engines(choice: str = "auto") -> list[str]:
    """Engine chain for a setting value. `auto` skips Claude when the CLI is not installed and
    returns nothing in offline demo mode."""
    provider = store.get_settings()["llm"].get("provider")
    choice = (choice or "auto").strip().lower()
    if choice in ENGINES:
        rest = [e for e in ("bing", "wikipedia") if e != choice]
        return [choice] + rest
    if provider == "mock":
        return []
    return (["claude"] if shutil.which("claude") else []) + ["bing", "wikipedia"]


def _usable(url: str, seen: set[str]) -> bool:
    if not url.startswith(("http://", "https://")) or url in seen:
        return False
    host = (urlparse(url).hostname or "").lower()
    return bool(host) and not any(h in host for h in SKIP_HOSTS)


def _claude(ep: dict, gaps: list[str], tried: list[str], limit: int) -> list[dict]:
    sys = """你是研究助理，替自媒體講稿找可以引用的公開網頁。用 WebSearch 搜尋，挑出最能支撐題目的頁面。
規則：
- 優先一手來源：官方公告、官方部落格或文件、論文、政府或機構頁面、原始報導；其次是可信的深度報導與百科。
- 只挑不用登入、沒有付費牆、有文字正文的頁面；不要影片、社群貼文、搜尋結果頁、論壇灌水文。
- 搜尋詞只用題目裡的公開關鍵字，不要放任何個人資料。
- 不要編造網址：只回傳你在搜尋結果裡實際看到的網址。
輸出：{"urls":[{"url":"https://…","title":"頁面標題","why":"這頁支撐哪個主張（一句）"}]}"""
    notes = str(ep.get("notes") or "").strip()[:800]
    pr = [f"# 題目\n{ep.get('topic') or ''}"]
    if notes:
        pr.append(f"# 使用者筆記\n{notes}")
    if gaps:
        pr.append("# 目前缺的證據\n" + "\n".join(f"- {g}" for g in gaps[:6]))
    if tried:
        pr.append("# 已經試過、不用再給的網址\n" + "\n".join(tried[:10]))
    pr.append(f"請找 {limit} 個網址，最多 {limit + 2} 個。")
    try:
        data = llm.claude_web_search(sys, "\n\n".join(pr))
    except llm.LLMError as e:
        raise SearchError(f"Claude 搜尋失敗：{e}") from e
    rows = data.get("urls") if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        if isinstance(r, str):
            r = {"url": r}
        if isinstance(r, dict) and r.get("url"):
            out.append({"url": str(r["url"]).strip(), "title": str(r.get("title") or "")[:120],
                        "why": str(r.get("why") or "")[:160]})
    return out


def _unwrap_bing(href: str) -> str:
    href = html.unescape(href)
    if "bing.com/ck/a" not in href:
        return href
    u = (parse_qs(urlparse(href).query).get("u") or [""])[0]
    if not u.startswith("a1"):
        return ""
    raw = u[2:]
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", "replace")
    except ValueError:
        return ""


def _bing(query: str) -> list[dict]:
    try:
        r = httpx.get("https://www.bing.com/search", params={"q": query, "setlang": "zh-Hant", "cc": "TW"},
                      headers={"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"},
                      timeout=20, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise SearchError(f"Bing 搜尋失敗：{e}") from e
    out = []
    for m in re.finditer(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        url = _unwrap_bing(m.group(1))
        if url:
            title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            out.append({"url": url, "title": title[:120], "why": ""})
    return out


def _wikipedia(query: str) -> list[dict]:
    try:
        r = httpx.get("https://zh.wikipedia.org/w/api.php",
                      params={"action": "query", "list": "search", "srsearch": query,
                              "format": "json", "srlimit": 3},
                      # Wikimedia answers 403 to a bare UA; a generic URL (not the owner's) is enough
                      headers={"User-Agent": "content-factory/1.0 (+https://www.mediawiki.org/wiki/API:Etiquette)"},
                      timeout=20)
        r.raise_for_status()
        hits = r.json().get("query", {}).get("search", [])
    except (httpx.HTTPError, ValueError) as e:
        raise SearchError(f"維基百科搜尋失敗：{e}") from e
    return [{"url": "https://zh.wikipedia.org/zh-tw/" + quote(h["title"].replace(" ", "_")),
             "title": h["title"], "why": "維基百科背景資料"} for h in hits if h.get("title")]


def search(ep: dict, gaps: list[str] | None = None, tried: list[str] | None = None,
           limit: int = 3, choice: str = "auto") -> dict:
    """Return `{"engine", "results": [{url,title,why}], "errors": [..]}`.

    Stops at the first engine that yields usable links; `tried` URLs are never returned again.
    """
    seen = set(tried or [])
    errors: list[str] = []
    query = re.sub(r"\s+", " ", str(ep.get("topic") or "")).strip()[:100]
    for eng in engines(choice):
        try:
            if eng == "claude":
                rows = _claude(ep, list(gaps or []), list(tried or []), limit)
            elif not query:
                continue
            elif eng == "bing":
                rows = _bing(query)
            else:
                rows = _wikipedia(query)
        except SearchError as e:
            errors.append(str(e))
            continue
        keep = []
        for r in rows:
            if _usable(r["url"], seen):
                seen.add(r["url"])
                keep.append(r)
        if keep:
            return {"engine": eng, "results": keep[:limit + 3], "errors": errors}
        errors.append(f"{eng} 沒有可用結果")
    return {"engine": "", "results": [], "errors": errors}
