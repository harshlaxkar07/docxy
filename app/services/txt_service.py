from typing import Optional
from app.core.config import settings
from app.core import runtime_settings
from app.utils.hashing import compute_sha256


class TXTService:
    def format_document_text(
        self,
        pages: list[dict],
        document_metadata: Optional[dict] = None,
        include_markers: Optional[bool] = None,
        include_metadata: Optional[bool] = None,
    ) -> tuple[str, int, int, str]:
        """
        Aggregate sorted page records into a final formatted string.
        Returns (formatted_text, character_count, word_count, sha256_hash).
        """
        use_markers = include_markers if include_markers is not None else runtime_settings.get("TXT_INCLUDE_PAGE_MARKERS")
        use_meta = include_metadata if include_metadata is not None else runtime_settings.get("TXT_INCLUDE_METADATA")

        rule = "=" * 60

        # Each entry is a complete block; blocks are joined with a blank line.
        # Joining with "" here would run the metadata lines together.
        sections: list[str] = []

        if use_meta and document_metadata:
            sections.append(
                "\n".join(
                    [
                        rule,
                        "DOCUMENT METADATA",
                        f"Original Filename: {document_metadata.get('original_filename', 'N/A')}",
                        f"Document UUID: {document_metadata.get('uuid', 'N/A')}",
                        f"Total Pages: {document_metadata.get('page_count', len(pages))}",
                        f"Extraction Method: {document_metadata.get('extraction_method', 'NATIVE+OCR')}",
                        rule,
                    ]
                )
            )

        for page in sorted(pages, key=lambda p: p["page_number"]):
            page_num = page["page_number"]
            page_text = (page.get("text") or "").strip()

            if use_markers:
                # The marker is kept even for an empty page, so the page is
                # still accounted for in the output.
                sections.append(f"================ PAGE {page_num} ================\n{page_text}")
            elif page_text:
                sections.append(page_text)

        full_text = "\n\n".join(sections).strip()
        char_count = len(full_text)
        word_count = len(full_text.split())
        text_hash = compute_sha256(full_text.encode("utf-8"))

        return full_text, char_count, word_count, text_hash


txt_service = TXTService()
