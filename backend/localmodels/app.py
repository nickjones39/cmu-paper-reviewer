"""Single-origin local app: upstream API + /api/local/* + the docs/ frontend.

Run with ``uvicorn backend.localmodels.app:app`` (``./run_local.sh`` does this).
Upstream's ``backend.main`` and ``docs/`` are used unmodified:

* ``/js/config.js`` is replaced so the frontend talks to this same origin.
* ``index.html`` is served with ``/js/local-models.js`` injected, which adds
  the "Local models" mode and the dynamic model selector to the upload form.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.localmodels.router import router
from backend.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.include_router(router)

_CONFIG_JS = (
    "// Served by backend.localmodels.app: the API lives on this same origin.\n"
    'const API_BASE_URL = localStorage.getItem("API_BASE_URL") || window.location.origin;\n'
)

_INJECT = '<script src="js/local-models.js"></script>\n  '


def inject_local_script(html: str) -> str:
    """Insert local-models.js just before upload.js so its mode pill exists when upload.js binds pills."""
    if "js/local-models.js" in html:
        return html
    new, n = re.subn(r'(<script\s+src="js/upload\.js"\s*>)', _INJECT + r"\1", html, count=1)
    if n == 0:  # upstream renamed upload.js — still load our script, at the end of <body>
        new = html.replace("</body>", _INJECT + "</body>", 1)
    return new


@app.get("/js/config.js", include_in_schema=False)
async def local_config_js():
    return Response(_CONFIG_JS, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/js/local-models.js", include_in_schema=False)
async def local_models_js():
    return FileResponse(STATIC_DIR / "local-models.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def local_index():
    index = DOCS_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="docs/index.html not found")
    return HTMLResponse(inject_local_script(index.read_text(encoding="utf-8")),
                        headers={"Cache-Control": "no-store"})


# Everything else (review.html, css, images) straight from upstream's docs/.
app.mount("/", StaticFiles(directory=str(DOCS_DIR), html=True), name="frontend")
