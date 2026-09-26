"""Artifact downloads, including the month-boundary regression.

The TXT download used to rebuild its storage key from `datetime.now()`. Any
file written in an earlier month was then looked up under the current
year/month prefix and missed entirely, degrading to a hard 404.
"""

from pathlib import Path

import pytest

from app.core.config import settings
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.result_repository import ResultRepository
from app.services.document_service import document_service
from app.workers.task_processor import task_processor


@pytest.fixture
def processed_document(sample_native_pdf_bytes):
    """A document taken all the way through the pipeline."""
    upload = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="downloadable.pdf",
    )
    job = JobRepository().get_by_uuid(upload["job_id"])
    task_processor.process_job(job)
    return upload["document_id"], job["document_id"]


def test_txt_download_succeeds(client, processed_document):
    doc_uuid, _ = processed_document
    res = client.get(f"/api/v1/documents/{doc_uuid}/download?file_type=txt")
    assert res.status_code == 200
    assert b"Sample Native Document Content" in res.content


def test_pdf_download_succeeds(client, processed_document):
    doc_uuid, _ = processed_document
    res = client.get(f"/api/v1/documents/{doc_uuid}/download?file_type=pdf")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_txt_download_survives_a_month_boundary(client, processed_document):
    """Regression: the key is read from output_files, not recomputed from today.

    The recorded key is rewritten to a prior month and the file moved to match,
    exactly as it would look after the calendar rolls over. Recomputing the key
    would look under the current month and 404.
    """
    doc_uuid, doc_id = processed_document
    repo = ResultRepository()

    record = repo.get_output_file_by_type(doc_id, "EXTRACTED_TXT")
    assert record is not None, "the pipeline recorded no EXTRACTED_TXT artifact"

    current_key = record["s3_key"]
    assert "/" in current_key

    # Move the artifact to a key from an earlier month.
    past_key = current_key.replace("/2026/", "/2020/").replace("/2025/", "/2020/")
    if past_key == current_key:  # unexpected key shape; build one explicitly
        past_key = f"extracted/2020/01/{doc_uuid}/extracted.txt"

    root = Path(settings.LOCAL_STORAGE_DIR)
    src, dst = root / current_key, root / past_key
    assert src.exists(), f"artifact missing on disk at {src}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)

    with __import__("app.db.database", fromlist=["db"]).db.connection() as conn:
        conn.execute(
            "UPDATE output_files SET s3_key = ? WHERE id = ?;", (past_key, record["id"])
        )

    res = client.get(f"/api/v1/documents/{doc_uuid}/download?file_type=txt")
    assert res.status_code == 200, "download failed for an artifact written in a past month"
    assert b"Sample Native Document Content" in res.content


def test_download_of_unprocessed_document_404s(client, sample_native_pdf_bytes):
    upload = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="never_processed.pdf",
    )
    res = client.get(f"/api/v1/documents/{upload['document_id']}/download?file_type=txt")
    assert res.status_code == 404


def test_local_storage_route_serves_objects(client, processed_document):
    """The URL generate_presigned_url advertises when AWS is off must resolve."""
    _, doc_id = processed_document
    record = ResultRepository().get_output_file_by_type(doc_id, "EXTRACTED_TXT")

    res = client.get(f"/api/v1/storage/local/{record['s3_key']}")
    assert res.status_code == 200
    assert b"Sample Native Document Content" in res.content


def test_local_storage_route_blocks_traversal(client):
    """A key escaping the storage root must never be served."""
    res = client.get("/api/v1/storage/local/../../../../etc/passwd")
    assert res.status_code in (403, 404)
    assert b"root:" not in res.content
