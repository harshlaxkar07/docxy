import io
from pathlib import Path
from typing import Optional, Union, Tuple
from PIL import Image
import fitz  # PyMuPDF

from app.core.config import settings
from app.constants.statuses import PageType
from app.core.exceptions import (
    PDFValidationError,
    PDFCorruptedError,
    PDFEncryptedError,
    PDFPageLimitError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class PDFPageAnalysis:
    def __init__(
        self,
        page_number: int,
        width: float,
        height: float,
        text: str,
        character_count: int,
        text_density: float,
        image_count: int,
        image_area_ratio: float,
        page_type: PageType,
    ):
        self.page_number = page_number
        self.width = width
        self.height = height
        self.text = text
        self.character_count = character_count
        self.text_density = text_density
        self.image_count = image_count
        self.image_area_ratio = image_area_ratio
        self.page_type = page_type


class PDFService:
    def validate_pdf(self, pdf_path_or_bytes: Union[str, Path, bytes]) -> dict:
        """Validate PDF binary structure, corruption, password protection, and page limits."""
        doc = None
        try:
            if isinstance(pdf_path_or_bytes, bytes):
                doc = fitz.open(stream=pdf_path_or_bytes, filetype="pdf")
            else:
                doc = fitz.open(str(pdf_path_or_bytes))

            if doc.is_encrypted:
                raise PDFEncryptedError()

            if doc.page_count <= 0:
                raise PDFValidationError("PDF contains no pages")

            if doc.page_count > settings.MAX_PAGES_PER_DOCUMENT:
                raise PDFPageLimitError(
                    f"PDF contains {doc.page_count} pages, exceeding maximum limit of {settings.MAX_PAGES_PER_DOCUMENT}"
                )

            return {
                "page_count": doc.page_count,
                "is_encrypted": False,
                "format": doc.metadata.get("format", "PDF"),
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
            }
        except (PDFEncryptedError, PDFPageLimitError, PDFValidationError):
            raise
        except Exception as e:
            logger.error("PDF validation failed with corruption or syntax error: %s", e)
            raise PDFCorruptedError(f"PDF validation failed: {e}")
        finally:
            if doc:
                try:
                    doc.close()
                except Exception:
                    pass

    def inspect_and_classify_page(self, page: fitz.Page, page_number: int) -> PDFPageAnalysis:
        """Inspect a single PyMuPDF page and classify into NATIVE_TEXT, IMAGE_BASED, MIXED, or EMPTY."""
        rect = page.rect
        width = float(rect.width)
        height = float(rect.height)
        page_area = width * height if (width > 0 and height > 0) else 1.0

        # Extract native text
        text = page.get_text("text") or ""
        char_count = len(text.strip())
        text_density = char_count / page_area

        # Inspect images
        images = page.get_images(full=True)
        image_count = len(images)
        total_image_area = 0.0

        for img_info in images:
            xref = img_info[0]
            for img_rect in page.get_image_rects(xref):
                total_image_area += float(img_rect.width * img_rect.height)

        image_area_ratio = min(total_image_area / page_area, 1.0)

        # Classification heuristics
        if char_count == 0 and image_count == 0:
            page_type = PageType.EMPTY
        elif char_count >= settings.PDF_MIN_TEXT_LENGTH:
            if image_count > 0 and image_area_ratio >= settings.PDF_MIN_IMAGE_AREA_RATIO:
                page_type = PageType.MIXED
            else:
                page_type = PageType.NATIVE_TEXT
        else:
            # Low text count (< threshold)
            if image_count > 0 or image_area_ratio >= settings.PDF_MIN_IMAGE_AREA_RATIO:
                page_type = PageType.IMAGE_BASED
            elif text_density < settings.PDF_MIN_TEXT_DENSITY:
                page_type = PageType.IMAGE_BASED if image_count > 0 else PageType.EMPTY
            else:
                page_type = PageType.NATIVE_TEXT

        return PDFPageAnalysis(
            page_number=page_number,
            width=width,
            height=height,
            text=text,
            character_count=char_count,
            text_density=text_density,
            image_count=image_count,
            image_area_ratio=image_area_ratio,
            page_type=page_type,
        )

    def render_page_to_image(
        self,
        page: fitz.Page,
        dpi: int = 150,
        max_dimension: int = 1600,
        quality: int = 85,
    ) -> bytes:
        """Render a PyMuPDF page to an optimized JPEG byte buffer for Vision OCR."""
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Convert to PIL Image for compression & resizing if needed
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Resize if dimensions exceed max_dimension
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()


pdf_service = PDFService()
