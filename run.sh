#!/usr/bin/env bash
# Start the Content Factory web app on http://127.0.0.1:8770
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${CF_DATA:-$PWD/data}/.env"
if [ -f "$ENV_FILE" ] && [ -x .venv/bin/python ]; then
  while IFS= read -r -d '' entry; do
    key="${entry%%=*}"
    val="${entry#*=}"
    if [ -z "${!key:-}" ]; then
      export "$key=$val"
    fi
  done < <(.venv/bin/python -m app.env "$ENV_FILE")
fi
PORT="${CF_PORT:-8770}"
HOST="${CF_HOST:-127.0.0.1}"
if ! curl -fsS -o /dev/null http://127.0.0.1:8090/health 2>/dev/null; then
  echo "提醒：audio.cpp 伺服器（:8090）沒在跑，配音會失敗。可先執行 audiocpp-webui。" >&2
fi
exec .venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT"
