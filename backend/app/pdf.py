from __future__ import annotations

import io

from pypdf import PdfReader


def pdf_to_text(data: bytes) -> str:
    """Extract plain text from a PDF, page by page."""
    reader = PdfReader(io.BytesIO(data))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(pages).strip()
