# Background Worker & Orchestration

The worker runs in-process as a pool of daemon threads started from the FastAPI
lifespan. There is no external broker: the queue is the `jobs` table.

## Components

| Component | Responsibility |
| --- | --- |
| `WorkerPool` | Owns `WORKER_COUNT` workers plus one recovery sweeper |
| `BackgroundWorker` | Claims one job at a time and runs it to completion |
| `Heartbeat` | Bumps `last_heartbeat_at` on a timer while a job runs |
| `RecoveryService` | Reclaims jobs whose heartbeat went stale |

## Polling loop

Each worker runs the same loop independently:

```python
while not stopped:
    job = job_repo.claim_next_job(worker_id)
    if not job:
        wait(WORKER_POLL_INTERVAL_SECONDS)
        continue

    with Heartbeat(job["id"], job_repo):
        task_processor.process_job(job, custom_groq_key=...)
```

## Atomic claiming

Claiming is **two statements inside one `BEGIN IMMEDIATE` transaction**, not a
single `UPDATE … WHERE id = (SELECT …)`. A candidate is selected, then updated
under a guard that re-checks its status:

```sql
BEGIN IMMEDIATE;

-- 1. pick a candidate
SELECT id FROM jobs
WHERE status IN ('QUEUED', 'RETRYING')
  AND (retry_after IS NULL OR retry_after <= CURRENT_TIMESTAMP)
ORDER BY priority DESC, created_at ASC
LIMIT 1;

-- 2. take it, but only if it is still claimable
UPDATE jobs
SET status = 'RUNNING',
    worker_id = :worker_id,
    started_at = COALESCE(started_at, :now),
    last_heartbeat_at = :now,
    attempt_count = attempt_count + 1,
    updated_at = :now
WHERE id = :id
  AND status IN ('QUEUED', 'RETRYING');

COMMIT;
```

If the `UPDATE` reports `rowcount == 0`, another worker won the race and
`claim_next_job` returns `None`, so the loop simply polls again. `BEGIN
IMMEDIATE` takes SQLite's write lock up front, so two workers cannot interleave
between the select and the update. The guard makes duplicate claims impossible
regardless.

## Heartbeats

`Heartbeat` runs on its own timer thread for the lifetime of a job, writing
`last_heartbeat_at` every `WORKER_HEARTBEAT_INTERVAL_SECONDS` (default 10 s).

This is deliberately independent of page progress. When the heartbeat was
bumped only as each page completed, a single OCR page slower than
`JOB_STALE_TIMEOUT_SECONDS` (default 120 s) made a perfectly healthy job look
abandoned, and the recovery sweep would reclaim a job that was still running.

A failed heartbeat write is logged and ignored — it must never kill the job.

## Recovery

`WorkerPool` sweeps for stale jobs in two places:

1. **At startup**, before any worker begins, reclaiming anything abandoned by a
   previous process.
2. **Periodically**, on a dedicated thread every
   `RECOVERY_SWEEP_INTERVAL_SECONDS` (default 60 s), so a job orphaned while
   the process keeps running is reclaimed without a restart.

A stale job is reset to `RETRYING` with `retry_after = now + 5s`, or moved to
`FAILED` with `MAX_RETRIES_EXCEEDED` once `attempt_count` passes
`JOB_MAX_ATTEMPTS`.

## Concurrency

`WORKER_COUNT` controls how many workers the pool starts. Because claiming is
race-safe, workers scale without further coordination.

Scale with `WORKER_COUNT` rather than by running more containers: the queue is a
single SQLite file, so multiple processes would contend for one write lock.

## Shutdown

`WorkerPool.stop()` signals every worker and the sweeper, then joins them.
It runs from the FastAPI lifespan, and `install_signal_handlers()` also binds
`SIGTERM`/`SIGINT` so a direct `python run.py` stops cleanly. Any handler that
was already registered (uvicorn's) is invoked afterwards, so normal shutdown is
unaffected. Handlers are only installed from the main thread.
