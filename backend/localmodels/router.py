"""/api/local/* — backend registry, server detection and the live model list."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.localmodels import discovery, hooks
from backend.localmodels.backends import all_backends, get_backend, normalize_base_url
from backend.localmodels.keys import has_server_side_key
from backend.localmodels.llm import MIN_CONTEXT_TOKENS
from backend.localmodels.settings import default_selection

router = APIRouter(prefix="/api/local", tags=["local-models"])


def _require_enabled():
    if not hooks.enabled():
        raise HTTPException(status_code=404, detail="Local-model mode is disabled on this server.")


@router.get("/backends")
async def backends():
    _require_enabled()
    return {
        "backends": all_backends(),
        "min_context_tokens": MIN_CONTEXT_TOKENS,
        "defaults": default_selection(),
    }


@router.get("/detect")
async def detect():
    """Probe the default address of every known backend."""
    _require_enabled()
    return {"servers": await discovery.detect()}


class ModelsRequest(BaseModel):
    backend: str
    base_url: str | None = None
    api_key: str | None = None


@router.post("/models")
async def models(body: ModelsRequest):
    """List models on one backend. POST so a typed API key never lands in a URL or log."""
    _require_enabled()
    result = await discovery.list_models(body.backend, body.base_url, body.api_key)
    b = get_backend(body.backend)
    result["has_server_key"] = has_server_side_key(b.id, normalize_base_url(b, body.base_url))
    return result
