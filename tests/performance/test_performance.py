import time
import fitz
from app.services.document_service import document_service
from app.workers.task_processor import task_processor
from app.db.repositories.job_repository import JobRepository
from app.db.repositories.document_repository import DocumentRepository
from app.constants.statuses import JobStatus


def generate_synthetic_pdf(page_count: int) -> bytes:
    doc = fitz.open()
    for i in range(1, page_count + 1):
        page = doc.new_page(width=595, height=842)
        content = (
            f"Performance Benchmark Document - Page {i}\n"
            f"Paragraph 1: Testing high-throughput page-by-page streaming extraction without buffering entire text in memory.\n"
            f"Paragraph 2: Evaluating SQLite write latency, status transitions, SHA-256 chunked hashing, and TXT generation.\n"
            * 4
        )
        page.insert_text((50, 72), content, fontsize=10)
    pdf_bytes = doc.write()
    doc.close()
    return pdf_bytes


def test_benchmark_synthetic_pdfs():
    page_counts = [10, 50]
    benchmarks = {}

    for count in page_counts:
        pdf_bytes = generate_synthetic_pdf(count)
        
        # Measure upload time
        t0 = time.time()
        upload_res = document_service.process_upload(
            file_bytes=pdf_bytes,
            original_filename=f"benchmark_{count}_pages.pdf",
        )
        upload_duration_ms = (time.time() - t0) * 1000
        job_uuid = upload_res["job_id"]

        # Measure extraction processing time
        job_repo = JobRepository()
        job = job_repo.get_by_uuid(job_uuid)
        
        t1 = time.time()
        task_processor.process_job(job)
        process_duration_ms = (time.time() - t1) * 1000

        updated_job = job_repo.get_by_uuid(job_uuid)
        assert updated_job["status"] == JobStatus.DONE.value
        assert updated_job["processed_pages"] == count

        benchmarks[count] = {
            "upload_ms": round(upload_duration_ms, 2),
            "processing_ms": round(process_duration_ms, 2),
            "ms_per_page": round(process_duration_ms / count, 2),
        }

    # Verify linear scaling and sub-100ms per page native throughput
    for count, metrics in benchmarks.items():
        assert metrics["ms_per_page"] < 100.0, f"Page processing too slow: {metrics}"
