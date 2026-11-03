"""Registry of known local inference servers.

Each entry says where the server listens by default, which API dialect it
speaks, and how to recognise it. Adding a new backend is one entry here; no
other code needs to change unless the server has a non-OpenAI model listing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Backend:
    id: str
    label: str
    # Candidate base URLs, most likely first. OpenAI-style URLs end in /v1.
    default_urls: tuple[str, ...]
    # "openai" (GET /v1/models, POST /v1/chat/completions) or "ollama" (native API).
    api_style: str = "openai"
    # Environment variable holding this backend's API key, if it uses one.
    key_env: str | None = None
    homepage: str = ""
    notes: str = ""
    # macOS-only servers are flagged so the UI can say so.
    apple_silicon_only: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["default_url"] = self.default_urls[0] if self.default_urls else ""
        from backend.localmodels import settings as local_settings

        d["key_env_set"] = bool(self.key_env and local_settings.get(self.key_env))
        return d


BACKENDS: tuple[Backend, ...] = (
    Backend(
        id="ollama",
        label="Ollama",
        default_urls=("http://127.0.0.1:11434",),
        api_style="ollama",
        key_env="OLLAMA_API_KEY",
        homepage="https://ollama.com",
        notes="Uses the native Ollama API so the context window (num_ctx) can be set per review.",
        tags=("gguf", "mlx"),
    ),
    Backend(
        id="lmstudio",
        label="LM Studio",
        default_urls=("http://127.0.0.1:1234/v1",),
        key_env="LMSTUDIO_API_KEY",
        homepage="https://lmstudio.ai",
        notes="Start the server from the Developer tab or with `lms server start`.",
        tags=("gguf", "mlx"),
    ),
    Backend(
        id="omlx",
        label="oMLX",
        default_urls=("http://127.0.0.1:8000/v1",),
        key_env="OMLX_API_KEY",
        homepage="https://github.com/jundot/omlx",
        notes="API key is read automatically from ~/.omlx/settings.json when the server is local.",
        apple_silicon_only=True,
        tags=("mlx",),
    ),
    Backend(
        id="splash",
        label="Splash",
        default_urls=("http://127.0.0.1:8000/v1",),
        key_env="SPLASH_API_KEY",
        homepage="https://github.com/incoai/splash",
        notes="`splash serve --model <owner/repo>` (or a gateway in front of it); set SPLASH_API_KEY if the server requires one.",
        apple_silicon_only=True,
        tags=("mlx",),
    ),
    Backend(
        id="mlx-serve",
        label="mlx-serve",
        default_urls=("http://127.0.0.1:11234/v1", "http://127.0.0.1:8095/v1"),
        key_env="MLX_SERVE_API_KEY",
        homepage="https://github.com/ddalcu/mlx-serve",
        notes="ddalcu/mlx-serve listens on 11234; the PyPI mlx-serve package on 8095.",
        apple_silicon_only=True,
        tags=("mlx", "gguf"),
    ),
    Backend(
        id="mlx-lm",
        label="mlx_lm.server",
        default_urls=("http://127.0.0.1:8080/v1",),
        homepage="https://github.com/ml-explore/mlx-lm",
        notes="`mlx_lm.server --model <repo>` from Apple's mlx-lm package.",
        apple_silicon_only=True,
        tags=("mlx",),
    ),
    Backend(
        id="mlx-openai-server",
        label="mlx-openai-server",
        default_urls=("http://127.0.0.1:8000/v1",),
        homepage="https://github.com/cubist38/mlx-openai-server",
        apple_silicon_only=True,
        tags=("mlx",),
    ),
    Backend(
        id="llamacpp",
        label="llama.cpp (llama-server)",
        default_urls=("http://127.0.0.1:8080/v1",),
        key_env="LLAMA_API_KEY",
        homepage="https://github.com/ggml-org/llama.cpp",
        notes="Start with `--jinja` so tool calling works.",
        tags=("gguf",),
    ),
    Backend(
        id="vllm",
        label="vLLM / vllm-mlx",
        default_urls=("http://127.0.0.1:8000/v1",),
        key_env="VLLM_API_KEY",
        homepage="https://docs.vllm.ai",
        notes="Enable tool calling with `--enable-auto-tool-choice --tool-call-parser <parser>`.",
    ),
    Backend(
        id="jan",
        label="Jan",
        default_urls=("http://127.0.0.1:1337/v1",),
        key_env="JAN_API_KEY",
        homepage="https://jan.ai",
    ),
    Backend(
        id="localai",
        label="LocalAI",
        default_urls=("http://127.0.0.1:8080/v1",),
        key_env="LOCALAI_API_KEY",
        homepage="https://localai.io",
    ),
    Backend(
        id="custom",
        label="Other OpenAI-compatible server",
        default_urls=(),
        key_env="LOCAL_LLM_API_KEY",
        notes="Any server exposing /v1/models and /v1/chat/completions.",
    ),
)

_BY_ID = {b.id: b for b in BACKENDS}


def get_backend(backend_id: str | None) -> Backend:
    """Return the backend for ``backend_id``, falling back to the generic one."""
    return _BY_ID.get(backend_id or "", _BY_ID["custom"])


def all_backends() -> list[dict]:
    return [b.to_dict() for b in BACKENDS]


def normalize_base_url(backend: Backend, base_url: str | None) -> str:
    """Return a clean base URL for ``backend`` (default when blank).

    OpenAI-style servers get a trailing ``/v1`` if the user left it off;
    Ollama's native API is rooted at the server origin, so ``/v1`` is removed.
    """
    url = (base_url or "").strip() or (backend.default_urls[0] if backend.default_urls else "")
    url = url.rstrip("/")
    if not url:
        return url
    if "://" not in url:
        url = "http://" + url
    if backend.api_style == "ollama":
        if url.endswith("/v1"):
            url = url[: -len("/v1")]
    elif not url.endswith("/v1"):
        url = url + "/v1"
    return url


def server_root(base_url: str) -> str:
    """Origin of an OpenAI-style base URL (``http://host:port/v1`` → ``http://host:port``)."""
    url = base_url.rstrip("/")
    return url[: -len("/v1")] if url.endswith("/v1") else url
