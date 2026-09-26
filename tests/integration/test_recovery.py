import time
from app.services.document_service import document_service
from app.workers.recovery import recovery_service
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.page_repository import PageRepository
from app.db.repositories.result_repository import ResultRepository
from app.constants.statuses import JobStatus, PageStatus
from app.workers.task_processor import task_processor


def test_crash_recovery_stale_job(sample_native_pdf_bytes):
    # 1. Upload & create job
    upload_res = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="stale_test.pdf",
    )
    job_uuid = upload_res["job_id"]
    job_repo = JobRepository()
    job = job_repo.get_by_uuid(job_uuid)

    # 2. Simulate active worker crash: status RUNNING with expired heartbeat
    job_repo.update_status(job["id"], JobStatus.RUNNING)
    with job_repo._get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET last_heartbeat_at = datetime('now', '-300 seconds') WHERE id = ?;",
            (job["id"],),
        )

    # 3. Trigger recovery service
    recovered_count = recovery_service.recover_stale_jobs()
    assert recovered_count >= 1

    recovered_job = job_repo.get_by_uuid(job_uuid)
    assert recovered_job["status"] in (JobStatus.RETRYING.value, JobStatus.QUEUED.value)


def test_page_checkpoint_resumption(sample_native_pdf_bytes):
    """A job resumed after a crash must reproduce the pages it already did.

    Phase 1 extracts pages 1 and 2 through the real extraction path, so their
    text is checkpointed exactly as production would write it. Phase 2 runs the
    whole job as if the process had restarted. If per-page text is not
    persisted and read back, the regenerated TXT silently loses those pages.
    """
    import fitz

    upload_res = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="resumption_test.pdf",
    )
    job_uuid = upload_res["job_id"]

    job_repo = JobRepository()
    page_repo = PageRepository()
    job = job_repo.get_by_uuid(job_uuid)
    doc_id = job["document_id"]

    from app.services.extraction_service import extraction_service

    extraction_service.initialize_document_pages(doc_id, sample_native_pdf_bytes)

    # --- Phase 1: genuinely extract pages 1 and 2, then "crash" -----------
    fitz_doc = fitz.open(stream=sample_native_pdf_bytes, filetype="pdf")
    try:
        first = extraction_service.extract_page(doc_id, job["id"], 1, fitz_doc)
        second = extraction_service.extract_page(doc_id, job["id"], 2, fitz_doc)
    finally:
        fitz_doc.close()

    assert first["text"].strip(), "page 1 produced no text to checkpoint"
    assert second["text"].strip(), "page 2 produced no text to checkpoint"

    # The text must be durable, not just returned to the caller.
    stored_one = page_repo.get_page(doc_id, 1)
    assert (stored_one.get("text") or "").strip(), "page text was not checkpointed to the database"

    # --- Phase 2: resume the job from scratch -----------------------------
    task_processor.process_job(job)

    completed_job = job_repo.get_by_uuid(job_uuid)
    assert completed_job["status"] == JobStatus.DONE.value
    assert page_repo.get_completed_pages_count(doc_id) == 3

    result = ResultRepository().get_extracted_text(doc_id)
    assert result is not None
    for page_no, extracted in ((1, first), (2, second)):
        marker = extracted["text"].strip().splitlines()[0][:40]
        assert marker in result["text"], f"page {page_no} was lost when the job resumed"
    assert "Page 3" in result["text"], "page 3 was never extracted"
