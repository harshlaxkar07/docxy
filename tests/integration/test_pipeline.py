from app.services.document_service import document_service
from app.workers.task_processor import task_processor
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.document_repository import DocumentRepository
from app.db.repositories.result_repository import ResultRepository
from app.constants.statuses import JobStatus, DocumentStatus


def test_end_to_end_native_extraction(sample_native_pdf_bytes):
    # 1. Upload & Queue
    upload_res = document_service.process_upload(
        file_bytes=sample_native_pdf_bytes,
        original_filename="sample_native.pdf",
    )
    doc_uuid = upload_res["document_id"]
    job_uuid = upload_res["job_id"]

    job_repo = JobRepository()
    doc_repo = DocumentRepository()
    result_repo = ResultRepository()

    job = job_repo.get_by_uuid(job_uuid)
    assert job["status"] == JobStatus.QUEUED.value

    # 2. Process Job via TaskProcessor
    task_processor.process_job(job)

    # 3. Verify Job & Document State
    updated_job = job_repo.get_by_uuid(job_uuid)
    assert updated_job["status"] == JobStatus.DONE.value
    assert updated_job["processed_pages"] == 3
    assert updated_job["total_pages"] == 3

    updated_doc = doc_repo.get_by_uuid(doc_uuid)
    assert updated_doc["status"] == DocumentStatus.COMPLETED.value
    assert updated_doc["page_count"] == 3
    assert updated_doc["text_character_count"] > 100

    # 4. Verify Extracted Text Record
    text_res = result_repo.get_extracted_text(updated_doc["id"])
    assert text_res is not None
    assert "Page 1 Sample Native Document Content" in text_res["text"]
    assert "Page 2 Sample Native Document Content" in text_res["text"]
    assert "Page 3 Sample Native Document Content" in text_res["text"]

    # 5. Verify Output Files
    output_files = result_repo.get_output_files(updated_doc["id"])
    assert len(output_files) >= 1
    txt_files = [f for f in output_files if f["file_type"] == "EXTRACTED_TXT"]
    assert len(txt_files) == 1
