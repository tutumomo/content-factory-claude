"""LLM providers: Claude Code CLI (headless), OpenAI-compatible HTTP, and an offline mock."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

import httpx

from . import mock_llm, store


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    """The provider declined to write this content.

    A refusal is not a broken JSON reply: the model answered, it just said no. Reporting it as
    "模型回覆不是合法 JSON" hides the cause and sends the owner looking in the wrong place.
    """


# Refusal phrasings seen from the providers we support. Matched case-insensitively on the
# whole reply; a refusal is a short, whole-message statement, so a hit means the model said no.
REFUSAL_MARKERS = (
    "i can't help with that",
    "i cannot help with that",
    "i can't assist with that",
    "i cannot assist with that",
    "i'm sorry, but i can't",
    "i am unable to provide",
    "i can't create",
    "i cannot create",
    "i'm not able to help with",
    "unable to assist with",
    "抱歉，我無法",
    "我無法協助",
    "無法協助這個",
    "我不能協助",
    "我不能幫你",
    "無法幫你製作",
    "這個請求我必須拒絕",
    "我不能生成",
)


def looks_like_refusal(text: str) -> bool:
    """True when the reply is a refusal rather than an answer (or a malformed answer)."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(m in t for m in REFUSAL_MARKERS)


def _extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = text.find(open_c), text.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(text[a : b + 1])
            except json.JSONDecodeError:
                continue
    if looks_like_refusal(text):
        raise LLMRefusal(
            "模型拒絕寫這個題材（provider 迴覆「" + text.strip()[:120] + "」）。"
            "請在設定頁把這個任務改派給能寫的 provider（例如本機 OpenAI 相容端點），或改用其他分級。")
    raise LLMError("模型回覆不是合法 JSON：" + text[:300])


def _claude_cli(system: str, prompt: str, cfg: dict, tools: str = "", timeout: float | None = None) -> str:
    """Run `claude -p` in an empty temp dir. `tools` names built-in tools to allow (e.g. "WebSearch");
    the default "" gives the model no tools at all."""
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--system-prompt", system,
        "--tools", tools,
        "--no-session-persistence",
        "--disable-slash-commands",
        "--setting-sources", "project",  # temp dir has no project settings: keeps user hooks/plugins out of the output
    ]
    if tools:  # -p cannot ask for permission, so the named tools must be pre-approved
        cmd += ["--allowedTools", tools]
    if cfg.get("claude_model"):
        cmd += ["--model", cfg["claude_model"]]
    # Drop variables inherited from a parent Claude Code / desktop session (model routing, host auth,
    # session ids). Keep ANTHROPIC_API_KEY if the user set one on purpose.
    env = {k: v for k, v in os.environ.items()
           if not (k == "CLAUDECODE" or k.startswith("CLAUDE_") or (k.startswith("ANTHROPIC_") and k != "ANTHROPIC_API_KEY"))}
    with tempfile.TemporaryDirectory(prefix="cf-llm-") as cwd:
        try:
            r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                               timeout=timeout or cfg.get("timeout_s", 1800), stdin=subprocess.DEVNULL)
        except FileNotFoundError as e:
            raise LLMError("找不到 claude 指令") from e
        except subprocess.TimeoutExpired as e:
            tmo = timeout or cfg.get("timeout_s", 1800)
            raise LLMError(f"claude 逾時：等了 {float(tmo):.0f} 秒還沒回覆。"
                           f"到設定頁把「LLM 逾時」調大，或換小一點的模型。") from e
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"claude 輸出無法解析（exit {r.returncode}）：{(r.stdout or r.stderr)[:300]}") from e
    if d.get("is_error"):
        raise LLMError("claude 回報錯誤：" + str(d.get("result"))[:300])
    return d.get("result") or ""


def _openai(system: str, prompt: str, cfg: dict, timeout: float | None = None) -> str:
    headers = {}
    env = cfg.get("openai_key_env")
    if env:
        key = os.environ.get(env)
        if not key:
            raise LLMError(f"環境變數 {env} 未設定")
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": cfg.get("openai_model") or "default",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0.7,
    }
    url = cfg["openai_base_url"].rstrip("/") + "/chat/completions"
    tmo = float(timeout or cfg.get("timeout_s") or 600)
    started = time.monotonic()
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=tmo)
        r.raise_for_status()
    except httpx.TimeoutException as e:
        raise LLMError(
            f"模型逾時：等了 {tmo:.0f} 秒還沒回覆（{type(e).__name__}）。本機模型慢的時候很常見。"
            f"這次生效的上限是 {tmo:.0f} 秒——設定頁有兩個逾時，"
            f"「LLM 逾時」管製作流程、「建集判讀逾時」管對話框的建議，"
            f"調大對應的那個，或改用小一點的模型。") from e
    except httpx.HTTPError as e:
        waited = time.monotonic() - started
        raise LLMError(f"OpenAI 相容端點錯誤（{url}，等了 {waited:.0f} 秒）：{e}") from e
    content = r.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S)


def provider_for(task: str, cfg: dict | None = None) -> str:
    """Which provider runs this task.

    `llm.task_routes` maps a task name to a provider ("claude_cli" | "openai" | "mock"), so an
    episode that needs a model willing to write a given subject can point that task elsewhere
    without changing the channel's default. Unknown tasks fall back to the default provider.
    """
    cfg = cfg or store.get_settings()["llm"]
    routes = cfg.get("task_routes") or {}
    p = str(routes.get(task) or "").strip().lower()
    if p in ("claude_cli", "openai", "mock"):
        return p
    return str(cfg.get("provider") or "claude_cli").strip().lower()


def timeout_for(task: str, cfg: dict | None = None) -> float:
    """How long this task may take. `llm.task_timeout_s` overrides per task, then `llm.timeout_s`.

    A local model can take minutes on a long prompt, so the ceiling is deliberately generous;
    the point of the value is to fail eventually, not to police speed.
    """
    cfg = cfg or store.get_settings()["llm"]
    per = (cfg.get("task_timeout_s") or {}).get(task)
    try:
        return float(per or cfg.get("timeout_s") or 1800)
    except (TypeError, ValueError):
        return 1800.0


def complete(task: str, system: str, prompt: str, timeout: float | None = None) -> str:
    """Run one task. `timeout` overrides this call only.

    Passing it as an argument matters: an earlier version temporarily rewrote the global
    `llm.timeout_s` and restored it afterwards, which meant a concurrently running episode could
    read that temporary value and time out at the short bound meant for the dialog.
    """
    cfg = store.get_settings()["llm"]
    p = provider_for(task, cfg)
    if p == "mock":
        return mock_llm.respond(task, prompt)
    tmo = float(timeout) if timeout else timeout_for(task, cfg)
    if p == "openai":
        return _openai(system, prompt, cfg, timeout=tmo)
    return _claude_cli(system, prompt, cfg, timeout=tmo)


def claude_web_search(system: str, prompt: str, timeout: float = 300):
    """One `claude -p` run with only the WebSearch tool, returning parsed JSON.

    Used by the source stage regardless of the configured LLM provider, so it is called only
    when the caller decided the Claude CLI is the search engine.
    """
    cfg = store.get_settings()["llm"]
    sys2 = system + "\n\n最後只輸出一個 JSON 物件，不要任何其他文字或 Markdown 圍欄。"
    return _extract_json(_claude_cli(sys2, prompt, cfg, tools="WebSearch", timeout=timeout))


def complete_json(task: str, system: str, prompt: str, timeout: float | None = None):
    sys2 = system + "\n\n只輸出一個 JSON 物件，不要任何其他文字或 Markdown 圍欄。"
    text = complete(task, sys2, prompt, timeout=timeout)
    try:
        return _extract_json(text)
    except LLMRefusal:
        raise                      # a refusal is an answer, not a broken reply: do not retry it
    except LLMError:
        fix = complete(task, sys2, prompt + "\n\n（上一次輸出不是合法 JSON。請只輸出合法 JSON。）",
                       timeout=timeout)
        return _extract_json(fix)


def health() -> dict:
    cfg = store.get_settings()["llm"]
    p = cfg["provider"]
    if p == "mock":
        return {"ok": True, "provider": p, "detail": "離線示範模式（內容是範例，不是真的生成）"}
    try:
        out = complete("health", "You are a health check.", "Reply with the single word: ok")
        return {"ok": "ok" in out.lower(), "provider": p, "detail": out[:80]}
    except LLMError as e:
        return {"ok": False, "provider": p, "detail": str(e)}
