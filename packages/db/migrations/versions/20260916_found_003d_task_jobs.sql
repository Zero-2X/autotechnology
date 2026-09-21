-- Revision: 20260916_found_003d_task_jobs
-- FOUND-003D: PostgreSQL task_jobs queue and read-only polling baseline.
CREATE TABLE IF NOT EXISTS task_jobs (
    id TEXT NOT NULL PRIMARY KEY,
    org_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    queue_name TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL CHECK (aggregate_version >= 1),
    payload_ref TEXT NOT NULL CHECK (payload_ref LIKE 'private://%'),
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) = 64),
    status TEXT NOT NULL CHECK (
        status IN (
            'queued', 'leased', 'running', 'succeeded', 'failed',
            'retry_scheduled', 'dead_letter', 'cancelled'
        )
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts >= 1),
    available_at TEXT NOT NULL,
    lease_until TEXT,
    locked_by TEXT,
    last_error TEXT,
    replayed_from_job_id TEXT,
    replayed_from_attempt_count INTEGER CHECK (
        replayed_from_attempt_count IS NULL OR replayed_from_attempt_count >= 0
    ),
    replay_reason TEXT,
    idempotency_key TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (org_id, job_type, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_task_jobs_poll_ready
    ON task_jobs (org_id, queue_name, status, available_at, created_at, id)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_task_jobs_aggregate
    ON task_jobs (org_id, aggregate_type, aggregate_id, aggregate_version);
