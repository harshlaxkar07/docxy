# Crash Recovery & Resumability

## Heartbeat Tracking & Stale Detection

During page processing, the worker updates `jobs.last_heartbeat_at` periodically.

On application startup, `RecoveryService.recover_stale_jobs()` runs:
```sql
SELECT * FROM jobs
WHERE status IN ('RUNNING', 'PROCESSING', 'OCR_PROCESSING', 'GENERATING_TEXT', 'UPLOADING')
  AND (strftime('%s', 'now') - strftime('%s', last_heartbeat_at)) > :stale_timeout_seconds;
```

Stale jobs are reset to `RETRYING` with `retry_after = now + 5s` (or `FAILED` if exceeding `max_attempts`).

## Page-Level Checkpointing

Because `document_pages.status = 'DONE'` is saved per page:
- When a recovered job resumes, `TaskProcessor` inspects `document_pages`.
- Completed pages are skipped immediately.
- Processing seamlessly continues from the first incomplete page without re-running native extraction or OCR on finished pages.
