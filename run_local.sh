#!/usr/bin/env bash
# Run the reviewer on this Mac against a local model server (fork add-on).
#
#   ./run_local.sh            # API + worker + frontend on http://127.0.0.1:8321
#   ./run_local.sh --no-open  # don't open the browser
#
# Settings: .env.local (see .env.local.example). Data: ./data (gitignored).
set -euo pipefail
cd "$(dirname "$0")"

OPEN_BROWSER=1
[[ "${1:-}" == "--no-open" ]] && OPEN_BROWSER=0

if [[ -z "${VIRTUAL_ENV:-}" && -x .venv/bin/python ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
if ! python -c "import openhands.sdk, fastapi" 2>/dev/null; then
  echo "Dependencies missing. Set up once with:" >&2
  echo "  uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt" >&2
  echo "  uv pip install --python .venv/bin/python --no-deps lmnr==0.7.52" >&2
  exit 1
fi

PORT="${LOCAL_APP_PORT:-$(python -c 'from backend.localmodels import settings; print(settings.get("LOCAL_APP_PORT", "8321"))')}"
export OPENHANDS_SUPPRESS_BANNER=1
# WeasyPrint (the PDF fallback when LaTeX fails) dlopens Pango/GObject, which
# Homebrew installs outside the default macOS library search path.
if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null; then
  export DYLD_FALLBACK_LIBRARY_PATH="$(brew --prefix)/lib${DYLD_FALLBACK_LIBRARY_PATH:+:$DYLD_FALLBACK_LIBRARY_PATH}"
fi
mkdir -p data/uploads data/ocr data/reviews data/pdfs

python -m backend.worker &
WORKER_PID=$!
uvicorn backend.localmodels.app:app --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!

cleanup() {
  kill "$WORKER_PID" "$SERVER_PID" 2>/dev/null || true
  wait "$WORKER_PID" "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

URL="http://127.0.0.1:${PORT}/"
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null "${URL}api/health" 2>/dev/null && break
  sleep 0.5
done
echo "CMU Paper Reviewer (local models) → ${URL}"
[[ "$OPEN_BROWSER" == 1 ]] && command -v open >/dev/null && open "$URL"

# Exit (and stop the other process) as soon as either one dies.
while kill -0 "$WORKER_PID" 2>/dev/null && kill -0 "$SERVER_PID" 2>/dev/null; do
  sleep 2
done
