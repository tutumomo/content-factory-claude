"""Lightweight `.env` parser and loader with zero third-party dependencies.

Loads key-value pairs from `data/.env` (or `$CF_DATA/.env`) into `os.environ` without overwriting
already-set non-empty variables, so both `./run.sh` and direct `uvicorn app.main:app` launches work
outside interactive shells.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def _parse_double_quoted(raw: str) -> tuple[str, bool]:
    """Parse a double-quoted value starting at `raw[0] == '"'`, handling standard escapes."""
    out: list[str] = []
    i = 1
    n = len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\\" and i + 1 < n:
            nxt = raw[i + 1]
            out.append(_ESCAPES[nxt] if nxt in _ESCAPES else "\\" + nxt)
            i += 2
            continue
        if ch == '"':
            return "".join(out), True
        out.append(ch)
        i += 1
    return "", False


def _parse_value(raw_after_eq: str) -> str:
    """Parse the right-hand side of `KEY=...` into its string value."""
    stripped = raw_after_eq.lstrip()
    if stripped.startswith("'"):
        end = stripped.find("'", 1)
        if end != -1:
            return stripped[1:end]
    elif stripped.startswith('"'):
        val, ok = _parse_double_quoted(stripped)
        if ok:
            return val
    return re.split(r"\s+#", raw_after_eq, maxsplit=1)[0].strip()


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `.env` text into `{key: value}`. Ignores blanks, comments, and invalid keys."""
    result: dict[str, str] = {}
    for raw_line in text.lstrip("\ufeff").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export") and len(line) > 6 and line[6].isspace():
            line = line[6:].lstrip()
        if "=" not in line:
            continue
        key_part, val_part = line.split("=", 1)
        key = key_part.strip()
        if not _KEY_RE.match(key):
            continue
        result[key] = _parse_value(val_part)
    return result


def default_env_path(data_dir: Path | None = None) -> Path:
    """Resolve `<data_dir>/.env`, honoring `CF_DATA` when no explicit directory is given."""
    if data_dir is not None:
        base = Path(data_dir)
    elif os.environ.get("CF_DATA"):
        base = Path(os.environ["CF_DATA"]).expanduser().resolve()
    else:
        base = ROOT / "data"
    return base / ".env"


def load_dotenv(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load non-empty entries from a `.env` file into `os.environ`.

    Existing non-empty variables (including `"0"` such as `CF_NSFW=0`) are kept unless
    `override=True`. Empty values in the file are skipped so blank template fields stay unset.
    """
    target = Path(path) if path is not None else default_env_path()
    if not target.is_file():
        return {}
    parsed = parse_dotenv(target.read_text(encoding="utf-8-sig"))
    applied: dict[str, str] = {}
    for key, val in parsed.items():
        if not val:
            continue
        if override or not os.environ.get(key):
            os.environ[key] = val
            applied[key] = val
    return applied


def _main(argv: list[str] | None = None) -> int:
    """Emit NUL-delimited `KEY=VALUE` records for `run.sh` without shell evaluation."""
    args = sys.argv[1:] if argv is None else argv
    target = Path(args[0]) if args else default_env_path()
    if not target.is_file():
        return 0
    for key, val in parse_dotenv(target.read_text(encoding="utf-8-sig")).items():
        if val:
            sys.stdout.buffer.write(f"{key}={val}\0".encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
