"""Fork settings, read from the environment or the repo's .env.local file.

Upstream's pydantic ``Settings`` only knows upstream's fields, so the fork
reads its own ``LOCAL_*`` / ``*_API_KEY`` variables here instead of editing
``backend/config.py``. They live in ``.env.local``, not ``.env``: upstream's
pydantic Settings rejects unknown keys in ``.env``. Real environment variables
win over ``.env.local`` values.

Default model selection (what the upload form preselects)::

    LOCAL_DEFAULT_BACKEND=splash
    LOCAL_DEFAULT_BASE_URL=http://127.0.0.1:8003/v1
    LOCAL_DEFAULT_MODEL=mac-studio-default-model
    LOCAL_DEFAULT_CONTEXT=          # optional, tokens; blank = server's window
    LOCAL_DEFAULT_LABEL=            # optional name shown for the default server
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _dotenv() -> dict[str, str]:
    path = Path(os.environ.get("LOCAL_ENV_FILE", REPO_ROOT / ".env.local"))
    try:
        from dotenv import dotenv_values

        return {k: v for k, v in dotenv_values(path).items() if v is not None}
    except Exception:
        return {}


def get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        value = _dotenv().get(name)
    return value if value not in (None, "") else default


def default_selection() -> dict:
    from backend.localmodels.backends import get_backend, normalize_base_url

    backend_id = get("LOCAL_DEFAULT_BACKEND")
    if not backend_id:
        return {}
    backend = get_backend(backend_id)
    ctx = get("LOCAL_DEFAULT_CONTEXT")
    return {
        "backend": backend.id,
        "base_url": normalize_base_url(backend, get("LOCAL_DEFAULT_BASE_URL")),
        "model": get("LOCAL_DEFAULT_MODEL") or "",
        "context_length": int(ctx) if ctx and ctx.isdigit() else None,
        "label": get("LOCAL_DEFAULT_LABEL") or "",
    }
