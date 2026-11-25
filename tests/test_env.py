"""Tests for `app/env.py` (.env parsing, loading precedence, CLI, and `/files/.env` block)."""
from __future__ import annotations

import os
import subprocess
import sys

from app import env, store


def test_parse_dotenv_handles_quotes_comments_export_and_bom():
    text = (
        "\ufeff"
        "# comment line\n"
        "\n"
        "export MAGPIE_API_KEY=abc123\n"
        "export\tWITH_EQUALS=a=b==c\n"
        "INLINE_COMMENT=hello world  # trailing note\n"
        "HASH_IN_VALUE=abc#123\n"
        "EMPTY_AFTER_HASH= # nothing\n"
        "SINGLE_QUOTED='line1\\n#not-comment' # after quote\n"
        'DOUBLE_QUOTED="line1\\nline2\\t\\"q\\"\\\\s" # after double quote\n'
        "123INVALID=nope\n"
        "BAD-KEY=nope\n"
        "NO_EQUALS_LINE\n"
    )
    parsed = env.parse_dotenv(text)
    assert parsed == {
        "MAGPIE_API_KEY": "abc123",
        "WITH_EQUALS": "a=b==c",
        "INLINE_COMMENT": "hello world",
        "HASH_IN_VALUE": "abc#123",
        "EMPTY_AFTER_HASH": "",
        "SINGLE_QUOTED": "line1\\n#not-comment",
        "DOUBLE_QUOTED": 'line1\nline2\t"q"\\s',
    }


def test_load_dotenv_respects_existing_and_zero_and_fills_empty(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "CF_TEST_NEW=from_file",
            "CF_TEST_EMPTY=",
            "CF_TEST_KEEP=from_file",
            "CF_TEST_ZERO=1",
            "CF_TEST_BLANK_IN_ENV=filled_from_file",
        ]),
        encoding="utf-8",
    )
    monkeypatch.delenv("CF_TEST_NEW", raising=False)
    monkeypatch.delenv("CF_TEST_EMPTY", raising=False)
    monkeypatch.setenv("CF_TEST_KEEP", "already_set")
    monkeypatch.setenv("CF_TEST_ZERO", "0")
    monkeypatch.setenv("CF_TEST_BLANK_IN_ENV", "")

    applied = env.load_dotenv(env_file)
    assert applied == {"CF_TEST_NEW": "from_file", "CF_TEST_BLANK_IN_ENV": "filled_from_file"}
    assert os.environ["CF_TEST_NEW"] == "from_file"
    assert "CF_TEST_EMPTY" not in os.environ
    assert os.environ["CF_TEST_KEEP"] == "already_set"
    assert os.environ["CF_TEST_ZERO"] == "0"
    assert os.environ["CF_TEST_BLANK_IN_ENV"] == "filled_from_file"

    overridden = env.load_dotenv(env_file, override=True)
    assert overridden["CF_TEST_KEEP"] == "from_file"
    assert overridden["CF_TEST_ZERO"] == "1"
    assert os.environ["CF_TEST_KEEP"] == "from_file"
    assert os.environ["CF_TEST_ZERO"] == "1"


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    assert env.load_dotenv(tmp_path / "does-not-exist.env") == {}


def test_cli_emits_nul_delimited_nonempty_records(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        'A=one\nEMPTY=\nB="two\\nlines"\n# comment\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "app.env", str(env_file)],
        capture_output=True,
        check=True,
    )
    assert proc.stdout == b"A=one\x00B=two\nlines\x00"


def test_files_endpoint_blocks_dotenv(client):
    secret = store.DATA / ".env"
    secret.write_text("MAGPIE_API_KEY=should-stay-private\n", encoding="utf-8")
    try:
        r = client.get("/files/.env")
        assert r.status_code == 404
    finally:
        secret.unlink(missing_ok=True)


def test_env_example_is_present_and_parseable():
    example = env.ROOT / ".env.example"
    assert example.is_file()
    parsed = env.parse_dotenv(example.read_text(encoding="utf-8-sig"))
    for key in ("MAGPIE_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "FREESOUND_API_KEY", "GEMINI_API_KEY"):
        assert key in parsed
