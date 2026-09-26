import os
import io
import pytest
from pathlib import Path
import fitz
from PIL import Image

# Force test configuration
os.environ["DATABASE_PATH"] = "./data/test_app.db"
os.environ["AWS_ENABLED"] = "false"
os.environ["GROQ_ENABLED"] = "false"
os.environ["WORKER_ENABLED"] = "false"
os.environ["LOCAL_STORAGE_DIR"] = "./data/test_output"
os.environ["TEMP_DIR"] = "./data/test_temp"

from app.core.config import settings
from app.db.database import db
from app.db.migrations import run_migrations
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    settings.DATABASE_PATH = "./data/test_app.db"
    settings.LOCAL_STORAGE_DIR = "./data/test_output"
    settings.TEMP_DIR = "./data/test_temp"
    settings.ensure_directories()
    
    test_db_path = Path("./data/test_app.db")
    if test_db_path.exists():
        test_db_path.unlink()
    for ext in ["-shm", "-wal"]:
        f = Path(f"./data/test_app.db{ext}")
        if f.exists():
            f.unlink()

    with db.connection() as conn:
        run_migrations(conn)

    yield

    # Session cleanup
    if test_db_path.exists():
        test_db_path.unlink(missing_ok=True)
    for ext in ["-shm", "-wal"]:
        f = Path(f"./data/test_app.db{ext}")
        if f.exists():
            f.unlink(missing_ok=True)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_native_pdf_bytes() -> bytes:
    """Generate a clean native digital text PDF with 3 pages."""
    doc = fitz.open()
    for i in range(1, 4):
        page = doc.new_page(width=595, height=842)
        text = (
            f"Page {i} Sample Native Document Content.\n"
            f"This is a paragraph of digital text that should be extracted natively by PyMuPDF without any OCR calls. "
            f"Testing character counts, word density, and formatting preservation across multi-page document ingestions.\n"
            * 5
        )
        page.insert_text((50, 72), text, fontsize=11)
    
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


@pytest.fixture
def sample_image_pdf_bytes() -> bytes:
    """Generate a PDF containing an image page (scanned simulation)."""
    doc = fitz.open()
    img = Image.new("RGB", (800, 1000), color=(240, 240, 240))
    img_bytes_io = io.BytesIO()
    img.save(img_bytes_io, format="PNG")
    img_bytes = img_bytes_io.getvalue()

    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=img_bytes)
    
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes
