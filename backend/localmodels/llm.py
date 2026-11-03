"""Turn a submission's local-model choice into an OpenHands ``LLM``.

The choice travels inside the submission's ``review_settings`` JSON under the
``local_model`` key (no schema change needed upstream)::

    {"local_model": {"backend": "omlx", "base_url": "http://127.0.0.1:8000/v1",
                     "model": "Qwen3.5-4B-MLX-4bit", "context_length": 65536,
                     "native_tool_calling": true}}

API keys are never stored there: a key typed in the form travels in the
existing ``user_litellm_api_key`` column (cleared after the review), and
everything else is resolved server-side by ``keys.resolve_api_key``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.localmodels import settings as local_settings
from backend.localmodels.backends import get_backend, normalize_base_url
from backend.localmodels.keys import PLACEHOLDER_KEY, resolve_api_key

logger = logging.getLogger(__name__)

# OpenHands refuses context windows below this (openhands.sdk.llm.llm).
MIN_CONTEXT_TOKENS = 16384
# Local prefill of a long paper can take minutes on a laptop; be patient.
DEFAULT_TIMEOUT_S = int(local_settings.get("LOCAL_LLM_TIMEOUT", "1800"))


class LocalModelError(ValueError):
    """Raised for an unusable local-model choice (shown to the submitter)."""


def _opt_int(v: Any) -> int | None:
    if v in (None, "", 0):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise LocalModelError(f"Expected a whole number, got {v!r}.")


def _opt_float(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise LocalModelError(f"Expected a number, got {v!r}.")


@dataclass
class LocalModelConfig:
    backend: str
    base_url: str
    model: str
    context_length: int | None = None
    max_output_tokens: int | None = None
    native_tool_calling: bool = True
    temperature: float | None = None
    timeout: int = DEFAULT_TIMEOUT_S

    @classmethod
    def from_settings(cls, review_settings: dict | None) -> "LocalModelConfig | None":
        raw = (review_settings or {}).get("local_model")
        if not raw:
            return None
        if not isinstance(raw, dict):
            raise LocalModelError("local_model must be an object.")
        backend = get_backend(raw.get("backend"))
        model = str(raw.get("model") or "").strip()
        if not model:
            raise LocalModelError("Choose a model for the local backend.")
        base_url = normalize_base_url(backend, raw.get("base_url"))
        if not base_url:
            raise LocalModelError("Enter the local server's base URL.")
        cfg = cls(
            backend=backend.id,
            base_url=base_url,
            model=model,
            context_length=_opt_int(raw.get("context_length")),
            max_output_tokens=_opt_int(raw.get("max_output_tokens")),
            native_tool_calling=bool(raw.get("native_tool_calling", True)),
            temperature=_opt_float(raw.get("temperature")),
            timeout=_opt_int(raw.get("timeout")) or DEFAULT_TIMEOUT_S,
        )
        if cfg.context_length is not None and cfg.context_length < MIN_CONTEXT_TOKENS:
            raise LocalModelError(
                f"The reviewer agent needs a context window of at least {MIN_CONTEXT_TOKENS:,} "
                f"tokens; {cfg.context_length:,} was chosen."
            )
        return cfg

    # ── LiteLLM routing ──────────────────────────────────────────────────────

    @property
    def is_ollama(self) -> bool:
        return get_backend(self.backend).api_style == "ollama"

    @property
    def litellm_model(self) -> str:
        # Ollama's native API is the only way to set num_ctx per request; all
        # other servers speak the OpenAI dialect.
        return f"ollama_chat/{self.model}" if self.is_ollama else f"openai/{self.model}"

    def api_key(self, explicit: str | None = None) -> str:
        return resolve_api_key(self.backend, self.base_url, explicit) or PLACEHOLDER_KEY

    def output_tokens(self) -> int:
        if self.max_output_tokens:
            return self.max_output_tokens
        if self.context_length:
            return max(2048, min(16384, self.context_length // 4))
        return 8192

    def apply_global_litellm_options(self) -> None:
        """Process-wide LiteLLM settings this backend needs (worker runs one review at a time)."""
        if self.is_ollama and self.context_length:
            import litellm

            litellm.OllamaChatConfig(num_ctx=self.context_length)

    def served_context_length(self, api_key: str | None = None) -> int | None:
        """The window the server reports for this model *right now*.

        Stable aliases (e.g. a gateway's ``mac-studio-default-model``) can be
        re-pointed at a different model between submission and review, so the
        window chosen in the form may no longer fit. Ollama is skipped: there
        num_ctx is ours to set.
        """
        if self.is_ollama:
            return None
        import httpx

        key = api_key or self.api_key()
        try:
            r = httpx.get(f"{self.base_url}/models", timeout=httpx.Timeout(5.0, connect=2.0),
                          headers={"Authorization": f"Bearer {key}"} if key else {})
            r.raise_for_status()
            for m in r.json().get("data", []):
                if m.get("id") == self.model:
                    for k in ("max_model_len", "context_length", "context_window", "max_context_length"):
                        v = m.get(k)
                        if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                            return v
        except Exception:
            logger.warning("Could not read the served context window from %s", self.base_url, exc_info=True)
        return None

    def reconcile_context(self, api_key: str | None = None) -> None:
        """Clamp the chosen window to what the server serves now (or adopt it if none was chosen)."""
        served = self.served_context_length(api_key)
        if served is None:
            return
        if self.context_length is None or self.context_length > served:
            if self.context_length:
                logger.warning("Context %d exceeds the %d tokens %s now serves; using %d.",
                               self.context_length, served, self.model, served)
            self.context_length = served
            if self.max_output_tokens and self.max_output_tokens >= served // 2:
                self.max_output_tokens = None  # fall back to the auto quarter-window

    def build_llm(self, api_key: str | None = None):
        from openhands.sdk import LLM

        self.reconcile_context(api_key)
        self.apply_global_litellm_options()
        return LLM(
            model=self.litellm_model,
            base_url=self.base_url,
            api_key=api_key or self.api_key(),
            drop_params=True,
            # Cloud-only features: prompt-cache retention, Anthropic thinking
            # budgets and OpenAI encrypted reasoning mean nothing to local servers.
            caching_prompt=False,
            prompt_cache_retention=None,
            reasoning_effort=None,
            extended_thinking_budget=None,
            enable_encrypted_reasoning=False,
            native_tool_calling=self.native_tool_calling,
            max_input_tokens=self.context_length,
            max_output_tokens=self.output_tokens(),
            temperature=self.temperature,
            timeout=self.timeout,
            num_retries=3,
            input_cost_per_token=0.0,
            output_cost_per_token=0.0,
        )

    def litellm_completion_kwargs(self, api_key: str | None = None) -> dict:
        """Keyword arguments for a direct ``litellm.completion`` call (debates)."""
        kw: dict[str, Any] = {
            "model": self.litellm_model,
            "api_base": self.base_url,
            "api_key": api_key or self.api_key(),
            "timeout": self.timeout,
        }
        if self.is_ollama and self.context_length:
            kw["num_ctx"] = self.context_length
        if self.temperature is not None:
            kw["temperature"] = self.temperature
        return kw
