"""Guards the fork's integration points after every merge from upstream.

If one of these fails after `git merge upstream/main`, upstream changed the
code around a hook: re-apply the hook (see LOCAL_MODELS.md, "Hook points").
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# file → snippets that must still be present
HOOKS = {
    "backend/models.py": ['local = "local"  # [local-models fork]'],
    "backend/routers/submissions.py": [
        "local_hooks.check_submission(mode, review_settings)",
        "local_hooks.LOCAL_MODE",
    ],
    "backend/worker.py": [
        "local_hooks.is_local(submission)",
        "local_hooks.use_local_ocr(submission)",
        "local_hooks.LocalOCRService()",
    ],
    "backend/services/review_service.py": ["local_hooks.configure_review_service(self)"],
    "backend/routers/debates.py": [
        "local_hooks.debate_llm_overrides(session, key)",
        "local_hooks.merge_debate_kwargs(_local_llm",
    ],
}


@pytest.mark.parametrize("path,snippets", HOOKS.items())
def test_upstream_hook_present(path, snippets):
    text = (REPO / path).read_text(encoding="utf-8")
    for s in snippets:
        assert s in text, f"{path}: hook missing: {s!r}"


def test_hooks_still_sit_where_upstream_expects():
    worker = (REPO / "backend/worker.py").read_text(encoding="utf-8")
    # The BYOK flag must be widened before the OCR/review steps read it.
    assert worker.index("local_hooks.is_local(submission)") < worker.index("ocr = OCRService(")
    # The local OCR branch must come before upstream's BYOK branch.
    assert worker.index("local_hooks.use_local_ocr(submission)") < worker.index("elif is_byok:")
    review = (REPO / "backend/services/review_service.py").read_text(encoding="utf-8")
    assert "def _build_llm(self)" in review, "configure_review_service shadows ReviewService._build_llm"
    assert "self.model_name" in review and "self.litellm_base_url" in review


def test_upload_js_exposes_what_local_models_js_wraps():
    js = (REPO / "docs/js/upload.js").read_text(encoding="utf-8")
    for fn in ("updateSubmitButton", "performUpload", "showConsentModal", "showMessage", "copyToClipboard"):
        assert re.search(rf"^(async\s+)?function {fn}\(", js, re.M), f"upload.js no longer defines {fn}()"
    for name in ("reviewSettings", "selectedFile", "codeInput", "suppInput", "submitBtn"):
        assert re.search(rf"^(let|const|var) {name}\b", js, re.M), f"upload.js no longer declares {name}"


def test_index_html_has_injection_anchors():
    html = (REPO / "docs/index.html").read_text(encoding="utf-8")
    for anchor in ('class="mode-toggle"', 'id="byok-fields"', 'id="mode"', 'src="js/upload.js"', 'id="focus-area"'):
        assert anchor in html, f"docs/index.html lost {anchor}"
