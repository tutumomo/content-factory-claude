"""LLM providers: Claude Code CLI (headless), OpenAI-compatible HTTP, and an offline mock."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

import httpx

from . import mock_llm, store


class LLMError(RuntimeError):
    pass


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
    raise LLMError("模型回覆不是合法 JSON：" + text[:300])


def _claude_cli(system: str, prompt: str, cfg: dict) -> str:
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--system-prompt", system,
        "--tools", "",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--setting-sources", "project",  # temp dir has no project settings: keeps user hooks/plugins out of the output
    ]
    if cfg.get("claude_model"):
        cmd += ["--model", cfg["claude_model"]]
    # Drop variables inherited from a parent Claude Code / desktop session (model routing, host auth,
    # session ids). Keep ANTHROPIC_API_KEY if the user set one on purpose.
    env = {k: v for k, v in os.environ.items()
           if not (k == "CLAUDECODE" or k.startswith("CLAUDE_") or (k.startswith("ANTHROPIC_") and k != "ANTHROPIC_API_KEY"))}
    with tempfile.TemporaryDirectory(prefix="cf-llm-") as cwd:
        try:
            r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                               timeout=cfg.get("timeout_s", 600), stdin=subprocess.DEVNULL)
        except FileNotFoundError as e:
            raise LLMError("找不到 claude 指令") from e
        except subprocess.TimeoutExpired as e:
            raise LLMError("claude 逾時") from e
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(f"claude 輸出無法解析（exit {r.returncode}）：{(r.stdout or r.stderr)[:300]}") from e
    if d.get("is_error"):
        raise LLMError("claude 回報錯誤：" + str(d.get("result"))[:300])
    return d.get("result") or ""


def _openai(system: str, prompt: str, cfg: dict) -> str:
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
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=cfg.get("timeout_s", 600))
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"OpenAI 相容端點錯誤：{e}") from e
    content = r.json()["choices"][0]["message"]["content"] or ""
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S)


def complete(task: str, system: str, prompt: str) -> str:
    cfg = store.get_settings()["llm"]
    p = cfg["provider"]
    if p == "mock":
        return mock_llm.respond(task, prompt)
    if p == "openai":
        return _openai(system, prompt, cfg)
    return _claude_cli(system, prompt, cfg)


def complete_json(task: str, system: str, prompt: str):
    sys2 = system + "\n\n只輸出一個 JSON 物件，不要任何其他文字或 Markdown 圍欄。"
    text = complete(task, sys2, prompt)
    try:
        return _extract_json(text)
    except LLMError:
        fix = complete(task, sys2, prompt + "\n\n（上一次輸出不是合法 JSON。請只輸出合法 JSON。）")
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
