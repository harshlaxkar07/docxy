import time
from app.services.document_service import document_service
from app.workers.recovery import recovery_service
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.page_repository import PageRepository
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
    upload_res = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="resumption_test.pdf",
    )
    job_uuid = upload_res["job_id"]
    doc_uuid = upload_res["document_id"]

    job_repo = JobRepository()
    page_repo = PageRepository()
    job = job_repo.get_by_uuid(job_uuid)
    doc_id = job["document_id"]

    # Initialize pages and mark page 1 and page 2 as already DONE
    from app.services.extraction_service import extraction_service
    extraction_service.initialize_document_pages(doc_id, sample_native_pdf_bytes)

    page_repo.update_page_result(doc_id, 1, {"status": PageStatus.DONE.value, "text_character_count": 50})
    page_repo.update_page_result(doc_id, 2, {"status": PageStatus.DONE.value, "text_character_count": 50})

    # Execute processor
    task_processor.process_job(job)

    # Verify job completed and all 3 pages are DONE
    completed_job = job_repo.get_by_uuid(job_uuid)
    assert completed_job["status"] == JobStatus.DONE.value
    assert page_repo.get_completed_pages_count(doc_id) == 3
