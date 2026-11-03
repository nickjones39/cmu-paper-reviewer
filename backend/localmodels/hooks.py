"""The only functions upstream code calls into.

Every call site in an upstream file is tagged ``# [local-models fork]`` and is
listed in LOCAL_MODELS.md; ``tests/localmodels/test_hooks_present.py`` fails if
a merge from upstream drops one. Keep these signatures stable: changing them
means touching upstream files again.
"""

from __future__ import annotations

import json
import logging

from backend.localmodels.llm import LocalModelConfig, LocalModelError
from backend.localmodels.ocr import LocalOCRService  # noqa: F401  (re-exported for worker.py)

logger = logging.getLogger(__name__)

LOCAL_MODE = "local"


def enabled() -> bool:
    """Local mode can be switched off for a public deployment of the fork."""
    from backend.localmodels import settings as local_settings

    return (local_settings.get("LOCAL_MODELS_ENABLED", "1") or "1").lower() not in ("0", "false", "no")


def _mode_value(submission) -> str:
    mode = getattr(submission, "mode", None)
    return getattr(mode, "value", mode) or ""


def is_local(submission) -> bool:
    return _mode_value(submission) == LOCAL_MODE


def use_local_ocr(submission) -> bool:
    """Local runs use offline text extraction unless a Mistral key was supplied."""
    return is_local(submission) and not getattr(submission, "user_mistral_api_key", None)


# ─── submissions.py ──────────────────────────────────────────────────────────


def check_submission(mode: str, review_settings: str | None) -> str | None:
    """Validate a submission's local-model choice; return the settings to store.

    For non-local modes any ``local_model`` key is stripped, so a queue/BYOK
    submission can never steer the worker at an arbitrary URL.
    """
    from fastapi import HTTPException

    try:
        parsed = json.loads(review_settings) if review_settings else {}
    except (json.JSONDecodeError, TypeError):
        parsed = None  # upstream decides what to do with malformed settings

    if mode != LOCAL_MODE:
        if isinstance(parsed, dict) and "local_model" in parsed:
            parsed.pop("local_model")
            return json.dumps(parsed)
        return review_settings

    if not enabled():
        raise HTTPException(status_code=400, detail="Local-model mode is disabled on this server.")
    if parsed is None:
        raise HTTPException(status_code=400, detail="Local-model mode needs valid review settings JSON.")
    if not isinstance(parsed, dict):
        parsed = {}
    # Fill anything the client left out from LOCAL_DEFAULT_* (.env), so API
    # callers can submit with mode=local alone.
    from backend.localmodels.settings import default_selection

    defaults = default_selection()
    choice = dict(parsed.get("local_model") or {})
    from backend.localmodels.backends import get_backend, normalize_base_url

    same_server = defaults and (
        not choice.get("backend")
        or (choice["backend"] == defaults["backend"]
            and normalize_base_url(get_backend(choice["backend"]), choice.get("base_url") or defaults["base_url"])
            == defaults["base_url"])
    )
    if same_server:
        for k, v in defaults.items():
            if k != "label" and v not in (None, "") and choice.get(k) in (None, ""):
                choice[k] = v
    if choice:
        parsed["local_model"] = choice
    try:
        cfg = LocalModelConfig.from_settings(parsed)
    except LocalModelError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if cfg is None:
        raise HTTPException(status_code=400, detail="Choose a local backend and model.")
    # Store the normalised choice so the worker and debates see clean values.
    parsed["local_model"] = {**parsed["local_model"], "backend": cfg.backend, "base_url": cfg.base_url, "model": cfg.model}
    return json.dumps(parsed)


# ─── review_service.py ───────────────────────────────────────────────────────


def configure_review_service(svc) -> None:
    """Point a freshly built ``ReviewService`` at the local model, if one was chosen."""
    try:
        cfg = LocalModelConfig.from_settings(getattr(svc, "review_settings", None))
    except LocalModelError:
        logger.exception("Ignoring invalid local_model settings")
        return
    if cfg is None or not enabled():
        return

    from backend.config import settings

    # ReviewService falls back to the server's cloud LiteLLM key when the
    # submission carried none; never send that key to a local server.
    typed = svc.litellm_api_key if svc.litellm_api_key and svc.litellm_api_key != settings.litellm_api_key else None
    svc.local_model = cfg
    svc.model_name = cfg.litellm_model
    svc.litellm_base_url = cfg.base_url
    svc.litellm_api_key = cfg.api_key(typed)
    # Instance attribute shadows ReviewService._build_llm for this review only.
    svc._build_llm = lambda: cfg.build_llm(svc.litellm_api_key)
    logger.info("Review will use local model %s at %s (%s)", cfg.model, cfg.base_url, cfg.backend)


# ─── debates.py ──────────────────────────────────────────────────────────────


async def debate_llm_overrides(session, key: str) -> dict:
    """LiteLLM kwargs that send a debate about a local review to the same local model."""
    if not enabled():
        return {}
    from sqlalchemy import select

    from backend.models import Submission

    result = await session.execute(select(Submission).where(Submission.key == key))
    sub = result.scalar_one_or_none()
    if sub is None or not is_local(sub) or not sub.review_settings:
        return {}
    try:
        cfg = LocalModelConfig.from_settings(json.loads(sub.review_settings))
    except (LocalModelError, json.JSONDecodeError, TypeError):
        return {}
    if cfg is None:
        return {}
    # The key the submitter typed was cleared after the review; debates use
    # server-side keys (env vars / oMLX settings) or none.
    return cfg.litellm_completion_kwargs()


def merge_debate_kwargs(overrides: dict, upstream_kwargs: dict) -> dict:
    return {**upstream_kwargs, **overrides}
