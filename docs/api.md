# REST API Documentation

All endpoints return a standard envelope structure:
```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

On failure:
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_PDF_FORMAT",
    "message": "File does not start with valid PDF binary signature (%PDF-)",
    "request_id": "req_a1b2c3d4e5",
    "details": null
  }
}
```

---

## Endpoints

### 1. Document Upload
- **POST** `/api/v1/documents`
- **Headers**:
  - `Content-Type`: `multipart/form-data`
  - `Idempotency-Key` (Optional): Unique string for duplicate submission prevention
- **Form Data**:
  - `file`: PDF binary
- **Response**: `202 Accepted`

### 1b. List Documents
- **GET** `/api/v1/documents`
- **Query**:
  - `limit` (default 25, 1–100), `offset` (default 0)
  - `status` (optional): `UPLOADED` | `PROCESSING` | `COMPLETED` | `FAILED`
  - `uuid` (optional): return only that document
- **Response**: `200 OK` — `{ items, total, limit, offset }`, newest first. Each item is a
  document joined with its latest job (`job_id`, `job_status`, `job_stage`,
  `progress_percentage`, `processed_pages`, `total_pages`, `error_code`), so a single
  request covers the state of every in-flight job.

### 2. Document Metadata
- **GET** `/api/v1/documents/{document_id}`
- **Response**: `200 OK`

### 3. Extracted Text
- **GET** `/api/v1/documents/{document_id}/text`
- **Response**: `200 OK`

### 3b. Per-Page Classification
- **GET** `/api/v1/documents/{document_id}/pages`
- **Query**: `limit` (default 1000, 1–5000), `offset` (default 0)
- **Response**: `200 OK` — `{ items, summary, total, limit, offset }`

  Each item reports how one page was routed: `page_type`
  (`NATIVE_TEXT` | `IMAGE_BASED` | `MIXED` | `EMPTY`), `extraction_method`,
  `status`, `ocr_used`, `text_character_count`, `text_density`,
  `image_count`, `image_area_ratio`, `processing_time_ms` and any page-level
  error.

  `summary` counts **every** page of the document (not just the returned
  slice): `total`, `native_text`, `image_based`, `mixed`, `empty`,
  `ocr_pages`, `done`, `failed`, `pending` — so a caller can show the
  native/OCR split without paging through the rows.

### 4. Download File
- **GET** `/api/v1/documents/{document_id}/download?file_type=pdf|txt`
- **Response**: `200 OK` (direct stream or 307 redirect to S3 presigned URL)

### 5. Job Status & Progress
- **GET** `/api/v1/jobs/{job_id}`
- **Response**: `200 OK`

### 6. Job Logs
- **GET** `/api/v1/jobs/{job_id}/logs?limit=100&offset=0`
- **Response**: `200 OK`

### 7. Retry Job
- **POST** `/api/v1/jobs/{job_id}/retry`
- **Response**: `200 OK`

### 8. Cancel Job
- **POST** `/api/v1/jobs/{job_id}/cancel`
- **Response**: `200 OK`

### 9. Health & Readiness
- **GET** `/health`
- **GET** `/health/live`
- **GET** `/health/ready`
