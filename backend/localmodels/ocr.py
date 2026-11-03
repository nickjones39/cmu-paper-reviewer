"""Offline PDF → Markdown for local runs (no Mistral key, nothing leaves the Mac).

Uses pypdf, which upstream already depends on. Text layers come out well;
equations and tables are flattened, and scanned PDFs without a text layer
yield nothing (``LocalOCRService`` then fails loudly rather than reviewing an
empty paper). Supply a Mistral key in the form for full OCR quality.

Writes the same files as ``backend.services.ocr_service.OCRService``:
``preprint/preprint.md``, ``preprint/images/*`` and ``preprint/images_list.json``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pypdf import PdfReader

from backend.services.storage_service import images_dir, images_list_path, preprint_md_path

logger = logging.getLogger(__name__)

# Skip icons, logos and rule lines.
MIN_IMAGE_BYTES = 8 * 1024
MAX_IMAGES = 200


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class LocalOCRService:
    def process_pdf(self, pdf_path: str | Path, key: str) -> str:
        logger.info("Local text extraction for key=%s, file=%s", key, pdf_path)
        reader = PdfReader(str(pdf_path))
        parts: list[str] = []
        images: list[dict] = []
        img_dir = None

        for page_no, page in enumerate(reader.pages, start=1):
            try:
                text = _clean(page.extract_text() or "")
            except Exception:
                logger.warning("key=%s: text extraction failed on page %d", key, page_no, exc_info=True)
                text = ""
            page_md = [f"<!-- page {page_no} -->", text] if text else [f"<!-- page {page_no} -->"]

            if len(images) < MAX_IMAGES:
                try:
                    page_images = list(page.images)
                except Exception:
                    page_images = []
                for i, img in enumerate(page_images):
                    data = getattr(img, "data", b"") or b""
                    if len(data) < MIN_IMAGE_BYTES or len(images) >= MAX_IMAGES:
                        continue
                    ext = Path(getattr(img, "name", "") or "").suffix.lower() or ".png"
                    if ext not in (".png", ".jpg", ".jpeg", ".jp2", ".tif", ".tiff", ".bmp", ".gif"):
                        ext = ".png"
                    name = f"page{page_no}-img{i}{ext}"
                    img_dir = img_dir or images_dir(key)
                    (img_dir / name).write_bytes(data)
                    page_md.append(f"![{name}]({name})")
                    images.append({
                        "id": name,
                        "page": page_no,
                        "top_left_x": None,
                        "top_left_y": None,
                        "bottom_right_x": None,
                        "bottom_right_y": None,
                    })
            parts.append("\n\n".join(page_md))

        full_text = "\n\n".join(parts)
        extracted_chars = len(re.sub(r"<!-- page \d+ -->|!\[[^\]]*\]\([^)]*\)|\s", "", full_text))
        if extracted_chars < 200:
            raise RuntimeError(
                "Local text extraction found almost no text in this PDF (it may be a scan). "
                "Add a Mistral API key in the Local models form to use OCR instead."
            )

        preprint_md_path(key).write_text(full_text, encoding="utf-8")
        if images:
            images_list_path(key).write_text(json.dumps(images, indent=2), encoding="utf-8")
        logger.info("Local extraction complete for key=%s: %d pages, %d images", key, len(reader.pages), len(images))
        return full_text
