import asyncio
import json

import httpx

from backend.localmodels import discovery


def run(coro):
    return asyncio.run(coro)


def client_for(routes: dict):
    """routes: {(method, url): (status, json_body)}; anything else is a connect error."""

    def handler(request: httpx.Request):
        key = (request.method, str(request.url))
        if key not in routes:
            raise httpx.ConnectError("refused", request=request)
        status, body = routes[key]
        if callable(body):
            body = body(request)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_openai_style_listing_reads_context_and_hides_embeddings():
    c = client_for({
        ("GET", "http://127.0.0.1:8003/v1/models"): (200, {"data": [
            {"id": "mac-studio-default-model", "owned_by": "gateway", "max_model_len": 262144, "vision": True},
            {"id": "nomic-embed-text", "owned_by": "x"},
        ]}),
    })
    r = run(discovery.list_models("splash", "http://127.0.0.1:8003", client=c))
    assert r["reachable"] and r["error"] is None
    assert r["base_url"] == "http://127.0.0.1:8003/v1"  # /v1 appended
    first, second = r["models"]
    assert first["id"] == "mac-studio-default-model" and first["context_length"] == 262144
    assert first["supports_vision"] is True and first["kind"] == "chat"
    assert second["kind"] == "embedding"


def test_unauthorised_server_reports_needs_key():
    c = client_for({("GET", "http://127.0.0.1:8000/v1/models"): (401, {"error": "API key required"})})
    r = run(discovery.list_models("omlx", None, client=c))
    assert r["needs_key"] and r["reachable"] and not r["models"]


def test_typed_key_is_sent_as_bearer():
    seen = {}

    def models(req):
        seen["auth"] = req.headers.get("authorization")
        return {"data": [{"id": "m"}]}

    c = client_for({("GET", "http://10.0.0.5:1234/v1/models"): (200, models)})
    run(discovery.list_models("lmstudio", "http://10.0.0.5:1234/v1", api_key="secret", client=c))
    assert seen["auth"] == "Bearer secret"


def test_omlx_status_enrichment():
    c = client_for({
        ("GET", "http://127.0.0.1:8000/v1/models"): (200, {"data": [{"id": "Qwen:64k", "max_model_len": 65536}]}),
        ("GET", "http://127.0.0.1:8000/v1/models/status"): (200, {"models": [
            {"id": "Qwen:64k", "loaded": True, "estimated_size": 5_000_000_000, "model_type": "vlm"}]}),
    })
    m = run(discovery.list_models("omlx", None, client=c))["models"][0]
    assert m["loaded"] is True and m["size_bytes"] == 5_000_000_000 and m["supports_vision"] is True
    assert m["context_length"] == 65536


def test_lmstudio_native_listing_marks_loaded_and_tools():
    c = client_for({
        ("GET", "http://127.0.0.1:1234/v1/models"): (200, {"data": [{"id": "qwen3-8b"}]}),
        ("GET", "http://127.0.0.1:1234/api/v0/models"): (200, {"data": [
            {"id": "qwen3-8b", "type": "llm", "state": "loaded", "max_context_length": 40960,
             "capabilities": ["tool_use"], "arch": "qwen3", "quantization": "Q4_K_M"},
            {"id": "text-embedding-nomic", "type": "embeddings", "state": "not-loaded"},
        ]}),
    })
    models = run(discovery.list_models("lmstudio", None, client=c))["models"]
    assert [m["id"] for m in models] == ["qwen3-8b", "text-embedding-nomic"]
    assert models[0]["loaded"] and models[0]["supports_tools"] and models[0]["context_length"] == 40960
    assert models[1]["kind"] == "embedding"


def test_ollama_native_listing():
    c = client_for({
        ("GET", "http://127.0.0.1:11434/api/tags"): (200, {"models": [
            {"name": "qwen3:8b", "size": 5_200_000_000, "details": {"parameter_size": "8.2B", "quantization_level": "Q4_K_M"}},
        ]}),
        ("GET", "http://127.0.0.1:11434/api/ps"): (200, {"models": [{"name": "qwen3:8b"}]}),
        ("POST", "http://127.0.0.1:11434/api/show"): (200, {
            "model_info": {"qwen3.context_length": 40960}, "capabilities": ["completion", "tools"]}),
    })
    r = run(discovery.list_models("ollama", "http://127.0.0.1:11434/v1", client=c))
    assert r["base_url"] == "http://127.0.0.1:11434"  # /v1 stripped for the native API
    m = r["models"][0]
    assert m["context_length"] == 40960 and m["loaded"] and m["supports_tools"]
    assert m["details"] == "8.2B · Q4_K_M"


def test_unreachable_server_never_raises():
    r = run(discovery.list_models("ollama", None, client=client_for({})))
    assert not r["reachable"] and "Could not reach" in r["error"]


def test_detect_identifies_servers_and_marks_default(monkeypatch):
    monkeypatch.setenv("LOCAL_DEFAULT_BACKEND", "splash")
    monkeypatch.setenv("LOCAL_DEFAULT_BASE_URL", "http://127.0.0.1:8003/v1")
    c = client_for({
        ("GET", "http://127.0.0.1:8003/v1/models"): (200, {"data": [{"id": "m", "owned_by": "splash"}]}),
        ("GET", "http://127.0.0.1:8000/v1/models"): (401, {}),
        ("GET", "http://127.0.0.1:8000/health"): (200, {"status": "healthy", "engine_pool": {}}),
        ("GET", "http://127.0.0.1:11434/api/tags"): (200, {"models": []}),
        ("GET", "http://127.0.0.1:11434/api/version"): (200, {"version": "0.12.0"}),
        # SearXNG-style HTML 404 on 8080 must not count as a model server
        ("GET", "http://127.0.0.1:8080/v1/models"): (404, {"detail": "Not Found"}),
    })
    servers = {s["base_url"]: s for s in run(discovery.detect(client=c))}
    assert set(servers) == {"http://127.0.0.1:8003/v1", "http://127.0.0.1:8000/v1", "http://127.0.0.1:11434"}
    assert servers["http://127.0.0.1:8003/v1"]["backend"] == "splash"
    assert servers["http://127.0.0.1:8003/v1"]["is_default"] is True
    assert servers["http://127.0.0.1:8000/v1"]["backend"] == "omlx"
    assert servers["http://127.0.0.1:8000/v1"]["needs_key"] is True
    assert servers["http://127.0.0.1:11434"]["backend"] == "ollama"
