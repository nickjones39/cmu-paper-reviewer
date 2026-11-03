import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.localmodels import hooks, keys
from backend.localmodels.app import inject_local_script
from backend.localmodels.backends import get_backend, normalize_base_url
from backend.localmodels.llm import LocalModelConfig, LocalModelError


def test_normalize_base_url():
    assert normalize_base_url(get_backend("splash"), "127.0.0.1:8003") == "http://127.0.0.1:8003/v1"
    assert normalize_base_url(get_backend("lmstudio"), "") == "http://127.0.0.1:1234/v1"
    assert normalize_base_url(get_backend("ollama"), "http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434"


def test_config_routes_ollama_natively_and_others_as_openai():
    o = LocalModelConfig.from_settings({"local_model": {"backend": "ollama", "model": "qwen3:8b", "context_length": 32768}})
    assert o.litellm_model == "ollama_chat/qwen3:8b" and o.base_url == "http://127.0.0.1:11434"
    assert o.litellm_completion_kwargs()["num_ctx"] == 32768
    s = LocalModelConfig.from_settings({"local_model": {"backend": "splash", "base_url": "http://127.0.0.1:8003/v1",
                                                        "model": "mac-studio-default-model"}})
    assert s.litellm_model == "openai/mac-studio-default-model"
    assert s.api_key() == keys.PLACEHOLDER_KEY  # no key needed, placeholder keeps litellm happy


def test_config_rejects_tiny_context_and_missing_model():
    with pytest.raises(LocalModelError):
        LocalModelConfig.from_settings({"local_model": {"backend": "ollama", "model": "x", "context_length": 4096}})
    with pytest.raises(LocalModelError):
        LocalModelConfig.from_settings({"local_model": {"backend": "ollama", "model": ""}})


def test_build_llm_disables_cloud_only_features():
    cfg = LocalModelConfig.from_settings({"local_model": {"backend": "splash", "base_url": "http://127.0.0.1:8003",
                                                          "model": "m", "context_length": 262144}})
    llm = cfg.build_llm()
    assert llm.model == "openai/m" and llm.base_url == "http://127.0.0.1:8003/v1"
    assert llm.max_input_tokens == 262144 and llm.max_output_tokens == 16384
    assert not llm.caching_prompt and not llm.enable_encrypted_reasoning and not llm.uses_responses_api()


def test_context_is_clamped_to_what_the_server_serves_now(monkeypatch):
    # e.g. the gateway alias was re-pointed from a 256k Qwen to a 32k DeepSeek after submission
    monkeypatch.setattr(LocalModelConfig, "served_context_length", lambda self, api_key=None: 32768)
    cfg = LocalModelConfig.from_settings({"local_model": {"backend": "custom", "base_url": "http://127.0.0.1:8003/v1",
                                                          "model": "mac-studio-default-model", "context_length": 262144}})
    llm = cfg.build_llm()
    assert llm.max_input_tokens == 32768 and llm.max_output_tokens == 8192
    unset = LocalModelConfig.from_settings({"local_model": {"backend": "custom", "base_url": "http://127.0.0.1:8003/v1",
                                                            "model": "m"}})
    assert unset.build_llm().max_input_tokens == 32768  # adopted when none was chosen


def test_check_submission_strips_local_model_from_other_modes():
    out = hooks.check_submission("queue", json.dumps({"max_items": 3, "local_model": {"backend": "custom",
                                                                                      "base_url": "http://evil/v1", "model": "x"}}))
    assert json.loads(out) == {"max_items": 3}
    assert hooks.check_submission("byok", None) is None


def test_check_submission_fills_configured_defaults(monkeypatch):
    monkeypatch.setenv("LOCAL_DEFAULT_BACKEND", "splash")
    monkeypatch.setenv("LOCAL_DEFAULT_BASE_URL", "http://127.0.0.1:8003/v1")
    monkeypatch.setenv("LOCAL_DEFAULT_MODEL", "mac-studio-default-model")
    lm = json.loads(hooks.check_submission("local", None))["local_model"]
    assert lm == {"backend": "splash", "base_url": "http://127.0.0.1:8003/v1", "model": "mac-studio-default-model"}
    # A different server keeps its own (missing) model instead of inheriting the default
    with pytest.raises(HTTPException):
        hooks.check_submission("local", json.dumps({"local_model": {"backend": "ollama"}}))


def test_check_submission_requires_a_choice_and_can_be_disabled(monkeypatch):
    with pytest.raises(HTTPException):
        hooks.check_submission("local", "{}")
    monkeypatch.setenv("LOCAL_MODELS_ENABLED", "0")
    with pytest.raises(HTTPException):
        hooks.check_submission("local", json.dumps({"local_model": {"backend": "ollama", "model": "m"}}))


def test_autodetected_key_only_goes_to_loopback(monkeypatch, tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"auth": {"api_key": "omlx-secret"}}))
    monkeypatch.setenv("OMLX_SETTINGS", str(f))
    assert keys.resolve_api_key("omlx", "http://127.0.0.1:8000/v1") == "omlx-secret"
    assert keys.resolve_api_key("omlx", "http://192.168.1.9:8000/v1") is None
    assert keys.resolve_api_key("omlx", "http://192.168.1.9:8000/v1", explicit="typed") == "typed"
    monkeypatch.setenv("SPLASH_API_KEY", "env-secret")
    assert keys.resolve_api_key("splash", "http://127.0.0.1:8003/v1") == "env-secret"


def test_review_service_hook_points_at_local_model_without_leaking_cloud_key(monkeypatch):
    from backend.config import settings
    from backend.services.review_service import ReviewService

    monkeypatch.setattr(settings, "litellm_api_key", "cloud-key")
    svc = ReviewService(review_settings={"local_model": {"backend": "splash", "base_url": "http://127.0.0.1:8003/v1",
                                                         "model": "mac-studio-default-model", "context_length": 65536}})
    assert svc.model_name == "openai/mac-studio-default-model"
    assert svc.litellm_api_key == keys.PLACEHOLDER_KEY
    llm = svc._build_llm()
    assert llm.base_url == "http://127.0.0.1:8003/v1" and llm.max_input_tokens == 65536

    plain = ReviewService(review_settings={"max_items": 3})
    assert plain.model_name in settings.review_models  # upstream behaviour untouched


def test_local_ocr_switch():
    sub = SimpleNamespace(mode=SimpleNamespace(value="local"), user_mistral_api_key=None)
    assert hooks.is_local(sub) and hooks.use_local_ocr(sub)
    sub.user_mistral_api_key = "k"
    assert not hooks.use_local_ocr(sub)
    assert not hooks.is_local(SimpleNamespace(mode=SimpleNamespace(value="byok")))


def test_script_injection_lands_before_upload_js():
    html = '<body><script src="js/config.js"></script>\n  <script src="js/upload.js"></script></body>'
    out = inject_local_script(html)
    assert out.index("local-models.js") < out.index("upload.js")
    assert inject_local_script(out) == out
    assert "local-models.js" in inject_local_script("<body></body>")
