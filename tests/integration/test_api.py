import pytest
from app.workers.task_processor import task_processor
from app.db.repositories.job_repository import JobRepository


def test_api_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_api_health_ready(client):
    res = client.get("/health/ready")
    assert res.status_code == 200
    assert res.json()["status"] in ("ready", "degraded")


def test_api_upload_and_status(client, sample_native_pdf_bytes):
    # Upload PDF
    files = {"file": ("test_doc.pdf", sample_native_pdf_bytes, "application/pdf")}
    res = client.post("/api/v1/documents", files=files)
    assert res.status_code == 202
    data = res.json()
    assert data["success"] is True
    doc_id = data["data"]["document_id"]
    job_id = data["data"]["job_id"]

    # Check Job Status
    job_res = client.get(f"/api/v1/jobs/{job_id}")
    assert job_res.status_code == 200
    assert job_res.json()["data"]["job_id"] == job_id
    assert job_res.json()["data"]["status"] == "queued"

    # Process job synchronously
    job_repo = JobRepository()
    job = job_repo.get_by_uuid(job_id)
    task_processor.process_job(job)

    # Check Job Status after completion
    job_res_done = client.get(f"/api/v1/jobs/{job_id}")
    assert job_res_done.status_code == 200
    assert job_res_done.json()["data"]["status"] == "done"

    # Check Document Metadata
    doc_res = client.get(f"/api/v1/documents/{doc_id}")
    assert doc_res.status_code == 200
    assert doc_res.json()["data"]["page_count"] == 3

    # Check Extracted Text Endpoint
    text_res = client.get(f"/api/v1/documents/{doc_id}/text")
    assert text_res.status_code == 200
    assert text_res.json()["data"]["character_count"] > 0

    # Check Download Endpoint
    download_res = client.get(f"/api/v1/documents/{doc_id}/download?file_type=txt")
    assert download_res.status_code in (200, 307)


def test_api_duplicate_upload_detection(client, sample_native_pdf_bytes):
    files1 = {"file": ("orig.pdf", sample_native_pdf_bytes, "application/pdf")}
    res1 = client.post("/api/v1/documents", files=files1)
    doc_id1 = res1.json()["data"]["document_id"]
    job_id1 = res1.json()["data"]["job_id"]

    # Process first upload to completion
    job_repo = JobRepository()
    job = job_repo.get_by_uuid(job_id1)
    task_processor.process_job(job)

    # Re-upload same file
    files2 = {"file": ("copy.pdf", sample_native_pdf_bytes, "application/pdf")}
    res2 = client.post("/api/v1/documents", files=files2)
    assert res2.status_code == 202
    assert res2.json()["data"]["is_duplicate"] is True
    assert res2.json()["data"]["document_id"] == doc_id1


def test_api_idempotency_header(client, sample_native_pdf_bytes):
    headers = {"Idempotency-Key": "test-key-12345"}
    files = {"file": ("idempotent.pdf", sample_native_pdf_bytes, "application/pdf")}
    
    res1 = client.post("/api/v1/documents", files=files, headers=headers)
    job_id1 = res1.json()["data"]["job_id"]

    files2 = {"file": ("idempotent.pdf", sample_native_pdf_bytes, "application/pdf")}
    res2 = client.post("/api/v1/documents", files=files2, headers=headers)
    job_id2 = res2.json()["data"]["job_id"]

    assert job_id1 == job_id2
