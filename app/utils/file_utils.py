import os
import re
import uuid
from pathlib import Path
from typing import Optional


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and unsafe characters."""
    # Strip path separators
    basename = os.path.basename(filename)
    # Remove control characters and unsafe path symbols
    sanitized = re.sub(r'[^a-zA-Z0-9_\-\. ]', '_', basename)
    return sanitized.strip() or f"document_{uuid.uuid4().hex[:8]}.pdf"


def get_file_extension(filename: str) -> str:
    """Get lowercase file extension without dot."""
    ext = os.path.splitext(filename)[1].lower()
    return ext[1:] if ext.startswith(".") else ext


def is_pdf_mime_type(mime_type: Optional[str]) -> bool:
    if not mime_type:
        return False
    return mime_type.lower() in ("application/pdf", "application/x-pdf")


def is_pdf_header(header_bytes: bytes) -> bool:
    """Validate PDF binary magic bytes header (%PDF-)."""
    return header_bytes.startswith(b"%PDF-")


def generate_uuid() -> str:
    return str(uuid.uuid4())
