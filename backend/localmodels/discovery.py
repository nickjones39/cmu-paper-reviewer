"""Find running local inference servers and list the models they serve.

All functions accept an optional ``httpx.AsyncClient`` so tests can inject a
mock transport. Network errors are reported in the result, never raised:
the model selector should degrade to "not running", not to a 500.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.localmodels.backends import BACKENDS, Backend, get_backend, normalize_base_url, server_root
from backend.localmodels.keys import resolve_api_key

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)  # probes are noisy at INFO

PROBE_TIMEOUT = httpx.Timeout(2.5, connect=0.75)
LIST_TIMEOUT = httpx.Timeout(10.0, connect=2.0)

# Model ids that are clearly not chat models (hidden unless "show all").
_NON_CHAT_HINTS = ("embed", "rerank", "whisper", "tts", "stt", "bge-", "e5-", "clip", "kokoro")


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _first_int(*values: Any) -> int | None:
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int) and v > 0:
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _kind_from_id(model_id: str) -> str:
    low = model_id.lower()
    return "embedding" if any(h in low for h in _NON_CHAT_HINTS) else "chat"


def _model(
    model_id: str,
    *,
    context_length: int | None = None,
    loaded: bool | None = None,
    kind: str | None = None,
    size_bytes: int | None = None,
    details: str = "",
    supports_tools: bool | None = None,
    supports_vision: bool | None = None,
) -> dict:
    return {
        "id": model_id,
        "context_length": context_length,
        "loaded": loaded,
        "kind": kind or _kind_from_id(model_id),
        "size_bytes": size_bytes,
        "details": details,
        "supports_tools": supports_tools,
        "supports_vision": supports_vision,
    }


async def _get_json(client: httpx.AsyncClient, url: str, api_key: str | None, timeout=LIST_TIMEOUT):
    resp = await client.get(url, headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# ─── Per-backend model listing ───────────────────────────────────────────────


async def _list_openai(client, base_url: str, api_key: str | None) -> list[dict]:
    data = await _get_json(client, f"{base_url}/models", api_key)
    models = []
    for m in data.get("data", []) if isinstance(data, dict) else []:
        mid = m.get("id")
        if not mid:
            continue
        meta = m.get("meta") or {}
        models.append(_model(
            mid,
            context_length=_first_int(
                m.get("max_model_len"), m.get("context_length"), m.get("context_window"),
                m.get("max_context_length"), meta.get("n_ctx_train"),
            ),
            loaded=m.get("loaded") if isinstance(m.get("loaded"), bool) else None,
            supports_vision=True if m.get("vision") is True else None,
        ))
    return models


async def _enrich_omlx(client, base_url: str, api_key: str | None, models: list[dict]) -> None:
    try:
        status = await _get_json(client, f"{base_url}/models/status", api_key, PROBE_TIMEOUT)
    except Exception:
        return
    info = {s.get("id"): s for s in status.get("models", []) if isinstance(s, dict)}
    for m in models:
        s = info.get(m["id"]) or info.get(m["id"].split(":")[0])
        if not s:
            continue
        m["loaded"] = bool(s.get("loaded"))
        m["size_bytes"] = _first_int(s.get("estimated_size"))
        mtype = (s.get("model_type") or "").lower()
        if mtype in ("embedding", "reranker", "audio", "stt", "tts"):
            m["kind"] = "embedding"
        m["supports_vision"] = mtype == "vlm" or None
        # The served window (max_model_len / max_context_window) wins over the
        # model's native maximum, because that is what the server will accept.
        m["context_length"] = m["context_length"] or _first_int(
            s.get("max_context_window"), s.get("model_context_length")
        )


async def _enrich_lmstudio(client, base_url: str, api_key: str | None, models: list[dict]) -> list[dict]:
    try:
        data = await _get_json(client, f"{server_root(base_url)}/api/v0/models", api_key, PROBE_TIMEOUT)
    except Exception:
        return models
    out = []
    for m in data.get("data", []):
        mid = m.get("id")
        if not mid:
            continue
        mtype = (m.get("type") or "").lower()
        caps = m.get("capabilities") or []
        out.append(_model(
            mid,
            context_length=_first_int(m.get("loaded_context_length"), m.get("max_context_length")),
            loaded=(m.get("state") == "loaded"),
            kind="embedding" if mtype == "embeddings" else "chat",
            details=" · ".join(x for x in (m.get("arch"), m.get("quantization")) if x),
            supports_tools=("tool_use" in caps) if caps else None,
            supports_vision=(mtype == "vlm") or None,
        ))
    return out or models


async def _enrich_llamacpp(client, base_url: str, api_key: str | None, models: list[dict]) -> None:
    try:
        props = await _get_json(client, f"{server_root(base_url)}/props", api_key, PROBE_TIMEOUT)
    except Exception:
        return
    n_ctx = _first_int((props.get("default_generation_settings") or {}).get("n_ctx"))
    for m in models:
        m["loaded"] = True
        if n_ctx:
            m["context_length"] = n_ctx


async def _list_ollama(client, base_url: str, api_key: str | None) -> list[dict]:
    tags = await _get_json(client, f"{base_url}/api/tags", api_key)
    try:
        ps = await _get_json(client, f"{base_url}/api/ps", api_key, PROBE_TIMEOUT)
        loaded_names = {m.get("name") for m in ps.get("models", [])}
    except Exception:
        loaded_names = set()

    async def show(name: str) -> dict:
        try:
            resp = await client.post(
                f"{base_url}/api/show", json={"model": name},
                headers=_headers(api_key), timeout=PROBE_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return {}

    entries = [t for t in tags.get("models", []) if t.get("name")]
    shown = await asyncio.gather(*(show(t["name"]) for t in entries))
    models = []
    for t, s in zip(entries, shown):
        info = s.get("model_info") or {}
        ctx = _first_int(*(v for k, v in info.items() if k.endswith(".context_length")))
        caps = s.get("capabilities") or []
        d = t.get("details") or {}
        kind = "embedding" if ("embedding" in caps and "completion" not in caps) else None
        models.append(_model(
            t["name"],
            context_length=ctx,
            loaded=t["name"] in loaded_names,
            kind=kind,
            size_bytes=_first_int(t.get("size")),
            details=" · ".join(x for x in (d.get("parameter_size"), d.get("quantization_level")) if x),
            supports_tools=("tools" in caps) if caps else None,
            supports_vision=("vision" in caps) or None,
        ))
    return models


async def list_models(
    backend_id: str,
    base_url: str | None = None,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """List the models served by one backend. Never raises."""
    backend = get_backend(backend_id)
    url = normalize_base_url(backend, base_url)
    result: dict[str, Any] = {
        "backend": backend.id,
        "base_url": url,
        "models": [],
        "reachable": False,
        "needs_key": False,
        "error": None,
    }
    if not url:
        result["error"] = "Enter the server's base URL."
        return result

    key = resolve_api_key(backend.id, url, api_key)
    result["key_source"] = "user" if (api_key and api_key.strip()) else ("server" if key else None)
    own_client = client is None
    client = client or httpx.AsyncClient()
    try:
        if backend.api_style == "ollama":
            models = await _list_ollama(client, url, key)
        else:
            models = await _list_openai(client, url, key)
            if backend.id == "omlx":
                await _enrich_omlx(client, url, key, models)
            elif backend.id == "lmstudio":
                models = await _enrich_lmstudio(client, url, key, models)
            elif backend.id == "llamacpp":
                await _enrich_llamacpp(client, url, key, models)
        result["reachable"] = True
        result["models"] = sorted(models, key=lambda m: (m["kind"] != "chat", not m["loaded"], m["id"].lower()))
    except httpx.HTTPStatusError as exc:
        result["reachable"] = True
        code = exc.response.status_code
        if code in (401, 403):
            result["needs_key"] = True
            result["error"] = "The server wants an API key."
        else:
            result["error"] = f"The server answered HTTP {code} for the model list."
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = f"Could not reach {url} ({type(exc).__name__})."
    finally:
        if own_client:
            await client.aclose()
    return result


# ─── Detection of running servers ────────────────────────────────────────────


async def _fingerprint(client: httpx.AsyncClient, root: str) -> str | None:
    """Identify which server software answers at ``root``, if possible."""

    async def get(path: str):
        try:
            r = await client.get(f"{root}{path}", timeout=PROBE_TIMEOUT)
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return r.json()
        except Exception:
            pass
        return None

    health, ollama_ver, lms, props, oapi = await asyncio.gather(
        get("/health"), get("/api/version"), get("/api/v0/models"), get("/props"), get("/openapi.json"),
    )
    if isinstance(ollama_ver, dict) and "version" in ollama_ver:
        return "ollama"
    if isinstance(health, dict) and "engine_pool" in health:
        return "omlx"
    title = ((oapi or {}).get("info") or {}).get("title", "").lower() if isinstance(oapi, dict) else ""
    if "omlx" in title:
        return "omlx"
    if "splash" in title:
        return "splash"
    if "mlx-serve" in title or "mlx serve" in title:
        return "mlx-serve"
    if isinstance(lms, dict) and "data" in lms:
        return "lmstudio"
    if isinstance(props, dict) and "default_generation_settings" in props:
        return "llamacpp"
    if "vllm" in title:
        return "vllm"
    return None


# /v1/models "owned_by" values that identify the server software.
_OWNER_HINTS = {"splash": "splash", "omlx": "omlx", "llamacpp": "llamacpp", "vllm": "vllm"}


async def _probe(client: httpx.AsyncClient, url: str, candidates: list[Backend]) -> dict | None:
    style = candidates[0].api_style
    probe_url = f"{url}/api/tags" if style == "ollama" else f"{url}/models"
    try:
        r = await client.get(probe_url, timeout=PROBE_TIMEOUT)
    except httpx.HTTPError:
        return None
    if r.status_code not in (200, 401, 403):
        return None
    owners: set[str] = set()
    if r.status_code == 200:
        try:
            body = r.json()
        except ValueError:
            return None
        if not isinstance(body, dict) or not ({"data", "models"} & body.keys()):
            return None
        owners = {str(m.get("owned_by", "")).lower() for m in body.get("data", []) if isinstance(m, dict)}
    identified = _OWNER_HINTS.get(next((o for o in owners if o in _OWNER_HINTS), ""), None)
    identified = identified or await _fingerprint(client, server_root(url))
    ids = [c.id for c in candidates]
    backend_id = identified if identified in ids else (ids[0] if len(ids) == 1 else (identified or ids[0]))
    return {
        "base_url": url,
        "backend": backend_id,
        "identified": identified is not None,
        "candidates": ids,
        "needs_key": r.status_code in (401, 403),
    }


async def detect(client: httpx.AsyncClient | None = None) -> list[dict]:
    """Probe every default address in the registry; return the servers that answer."""
    from backend.localmodels.settings import default_selection

    by_url: dict[str, list[Backend]] = {}
    default = default_selection()
    if default.get("base_url"):
        # The configured default server is probed first, whatever port it uses.
        by_url[default["base_url"]] = [get_backend(default["backend"])]
    for b in BACKENDS:
        for u in b.default_urls:
            lst = by_url.setdefault(normalize_base_url(b, u), [])
            if b not in lst:
                lst.append(b)

    own_client = client is None
    client = client or httpx.AsyncClient()
    try:
        found = await asyncio.gather(*(_probe(client, u, c) for u, c in by_url.items()))
    finally:
        if own_client:
            await client.aclose()

    servers = [f for f in found if f]
    for s in servers:
        s["has_server_key"] = resolve_api_key(s["backend"], s["base_url"]) is not None
        s["is_default"] = s["base_url"] == default.get("base_url")
    return servers
