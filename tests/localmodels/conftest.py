import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Tests never see the developer's .env.local, keys or oMLX settings."""
    from backend.localmodels import settings

    monkeypatch.setenv("LOCAL_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("OMLX_SETTINGS", str(tmp_path / "no-omlx.json"))
    for var in list(os.environ):
        if var.startswith("LOCAL_DEFAULT_") or var.endswith("_API_KEY") and var != "LITELLM_API_KEY":
            monkeypatch.delenv(var, raising=False)
    settings._dotenv.cache_clear()
    # build_llm() asks the live server for its window; keep tests off the network.
    from backend.localmodels.llm import LocalModelConfig

    monkeypatch.setattr(LocalModelConfig, "served_context_length", lambda self, api_key=None: None)
    yield
    settings._dotenv.cache_clear()
