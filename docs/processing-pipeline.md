# PDF Ingestion and Extraction Pipeline

## Step-by-Step Execution Flow

1. **Ingestion & Validation**:
   - Validates `%PDF-` binary magic bytes and MIME type.
   - Computes SHA-256 hash. If matching completed document exists, returns existing result immediately.
   - Enforces upload file size limit (`MAX_UPLOAD_SIZE_MB`) and page limit (`MAX_PAGES_PER_DOCUMENT`).
   - Creates `documents` and `jobs` records atomically and returns `202 Accepted` with `job_id`.

2. **Atomic Worker Claiming**:
   - Background worker claims next `QUEUED` or `RETRYING` job whose `retry_after` has elapsed using atomic SQL update with `worker_id`.

3. **Storage & Original Upload**:
   - Original PDF is uploaded to AWS S3 (`documents/YYYY/MM/<uuid>/original.pdf`) or stored in `data/output/`.

4. **Page Inspection & Heuristics**:
   - PyMuPDF opens the PDF and evaluates each page:
     - `character_count`: Extracted digital text length.
     - `text_density`: Character count / Page area.
     - `image_area_ratio`: Combined image bounding box area / Page area.
   - Classification:
     - `NATIVE_TEXT`: High character count, digital text selectable.
     - `IMAGE_BASED`: Low character count (< `PDF_MIN_TEXT_LENGTH`) and high image area ratio -> Marked for Vision OCR.
     - `MIXED`: High digital text + embedded images.
     - `EMPTY`: Zero text and zero images.

5. **Targeted Vision OCR Fallback**:
   - Only `IMAGE_BASED` pages are rendered to high-resolution JPEG buffers and passed through the `GroqRateLimiter` to the Groq Vision model.
   - Digital pages are extracted natively in sub-millisecond time.

6. **Page-Level Checkpointing**:
   - Each page updates `document_pages.status = 'DONE'`, enabling resumability if interrupted.
   - Worker updates `last_heartbeat_at` and `progress_percentage`.

7. **Aggregation & TXT Output**:
   - Extracted pages are formatted in page sequence with standard headers (`================ PAGE X ================`).
   - Generated TXT file is uploaded to S3 (`extracted/YYYY/MM/<uuid>/extracted.txt`) or stored locally.
   - Job is marked `DONE` and Document marked `COMPLETED`.
