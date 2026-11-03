"""Server-side API-key resolution for local backends.

Keys found here (environment variables, oMLX's own settings file) never leave
the server: the browser only learns *whether* a key is available. An
auto-detected key is only ever sent to a loopback address, so pointing the
model selector at another host cannot leak it.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from backend.localmodels.backends import get_backend

logger = logging.getLogger(__name__)

# litellm's OpenAI client refuses an empty key; local servers ignore this one.
PLACEHOLDER_KEY = "sk-no-key-required"

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def is_loopback(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS or host.endswith(".localhost")


def _omlx_settings_key() -> str | None:
    path = Path(os.environ.get("OMLX_SETTINGS", "~/.omlx/settings.json")).expanduser()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    auth = data.get("auth") or {}
    if auth.get("skip_api_key_verification") or auth.get("allow_unauthenticated_inference"):
        return None
    key = auth.get("api_key")
    return key if isinstance(key, str) and key else None


def resolve_api_key(backend_id: str | None, base_url: str, explicit: str | None = None) -> str | None:
    """Best key for talking to ``backend_id`` at ``base_url``, or None.

    Order: key typed by the user → ``<BACKEND>_API_KEY`` env var →
    ``LOCAL_LLM_API_KEY`` env var → auto-detection (loopback servers only).
    """
    if explicit and explicit.strip():
        return explicit.strip()
    from backend.localmodels import settings as local_settings

    backend = get_backend(backend_id)
    for env in (backend.key_env, "LOCAL_LLM_API_KEY"):
        if env and local_settings.get(env):
            return local_settings.get(env)
    if not is_loopback(base_url):
        return None
    if backend.id == "omlx":
        return _omlx_settings_key()
    return None


def has_server_side_key(backend_id: str | None, base_url: str) -> bool:
    return resolve_api_key(backend_id, base_url) is not None
