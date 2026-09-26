# Background Worker & Orchestration

## Worker Architecture

The `BackgroundWorker` runs as a long-lived polling process:

```python
while worker_running:
    job = job_repo.claim_next_job(worker_id)
    if not job:
        sleep(poll_interval)
        continue
    task_processor.process_job(job)
```

### Atomic Claiming
Jobs are claimed using single-transaction atomic queries:
```sql
UPDATE jobs
SET status = 'RUNNING',
    worker_id = :worker_id,
    started_at = COALESCE(started_at, :now),
    last_heartbeat_at = :now,
    attempt_count = attempt_count + 1,
    updated_at = :now
WHERE id = (
    SELECT id FROM jobs
    WHERE status IN ('QUEUED', 'RETRYING')
      AND (retry_after IS NULL OR retry_after <= CURRENT_TIMESTAMP)
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
);
```

This guarantees no duplicate claims across concurrent workers.
