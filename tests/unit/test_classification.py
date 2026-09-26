import fitz
from app.services.pdf_service import pdf_service
from app.constants.statuses import PageType


def test_classify_native_page(sample_native_pdf_bytes):
    doc = fitz.open(stream=sample_native_pdf_bytes, filetype="pdf")
    page = doc[0]
    analysis = pdf_service.inspect_and_classify_page(page, page_number=1)
    doc.close()

    assert analysis.page_type == PageType.NATIVE_TEXT
    assert analysis.character_count > 100
    # A native page must carry real text, register density, and hold no imagery.
    # (The previous assertion here tested `character_count > 0` twice over.)
    assert "Sample Native Document Content" in analysis.text
    assert analysis.character_count == len(analysis.text.strip())
    assert analysis.text_density > 0
    assert analysis.image_count == 0


def test_classify_image_page(sample_image_pdf_bytes):
    doc = fitz.open(stream=sample_image_pdf_bytes, filetype="pdf")
    page = doc[0]
    analysis = pdf_service.inspect_and_classify_page(page, page_number=1)
    doc.close()

    assert analysis.page_type == PageType.IMAGE_BASED
    assert analysis.image_count >= 1
    assert analysis.image_area_ratio > 0.3


def test_classify_empty_page():
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    analysis = pdf_service.inspect_and_classify_page(page, page_number=1)
    doc.close()

    assert analysis.page_type == PageType.EMPTY
    assert analysis.character_count == 0
    assert analysis.image_count == 0
