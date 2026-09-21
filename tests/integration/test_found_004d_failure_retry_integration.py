from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
TASK_MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"


FAILURE_DDL = """
CREATE TABLE task_failures (
    id TEXT PRIMARY KEY, org_id TEXT NOT NULL, job_id TEXT NOT NULL,
    attempt_count INTEGER NOT NULL, error_class TEXT NOT NULL, error_code TEXT NOT NULL,
    message_redacted TEXT, retryable INTEGER NOT NULL, trace_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL, UNIQUE(job_id, attempt_count, error_code)
)
"""
HUMAN_DDL = """
CREATE TABLE human_tasks (
    id TEXT PRIMARY KEY, org_id TEXT NOT NULL, task_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, input_version INTEGER NOT NULL,
    workflow_run_id TEXT, approval_id TEXT, status TEXT NOT NULL, assigned_to TEXT,
    claim_lease_until TEXT, priority TEXT NOT NULL, sla_policy_id TEXT, due_at TEXT,
    input_snapshot TEXT NOT NULL, result TEXT NOT NULL, completed_by TEXT,
    override_expires_at TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    UNIQUE(org_id, task_type, aggregate_id, input_version)
)
"""
LEASE_DDL = """
CREATE TABLE task_job_leases (
    job_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, worker_id TEXT NOT NULL,
    lease_token TEXT NOT NULL UNIQUE, lease_until TEXT NOT NULL, claimed_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL, claim_version INTEGER NOT NULL
)
"""


def _fixture() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(TASK_MIGRATION.read_text(encoding="utf-8"))
    connection.executescript(FAILURE_DDL)
    connection.executescript(HUMAN_DDL)
    connection.executescript(LEASE_DDL)
    return connection


def _job(connection: sqlite3.Connection, *, org_id: str, max_attempts: int = 3):
    from infra.foundation.task_queue import TaskJobQueue

    return TaskJobQueue(connection).enqueue(
        org_id=org_id,
        job_type="render",
        aggregate_type="Content",
        aggregate_id=str(uuid4()),
        aggregate_version=1,
        payload_ref="private://fixture/input",
        idempotency_key=str(uuid4()),
        trace_id="trace-fixture",
        max_attempts=max_attempts,
        now=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )


def test_failure_classification_idempotency_backoff_and_dead_letter() -> None:
    from infra.foundation.task_failure import RetryPolicy, TaskFailureStore

    connection = _fixture()
    org_id = str(uuid4())
    job = _job(connection, org_id=org_id, max_attempts=2)
    connection.commit()
    store = TaskFailureStore(connection, policy=RetryPolicy(backoff_base_ms=100, backoff_cap_ms=150))
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    first = store.record_failure(
        job_id=job.id, org_id=org_id, attempt_count=1, error_class="transient",
        error_code="TIMEOUT", message_redacted="temporary", trace_id="trace-1", occurred_at=now,
    )
    assert first.status == "retry_scheduled"
    assert first.available_at.endswith("00.100000+00:00")
    duplicate = store.record_failure(
        job_id=job.id, org_id=org_id, attempt_count=1, error_class="transient",
        error_code="TIMEOUT", message_redacted="temporary", trace_id="trace-1", occurred_at=now,
    )
    assert duplicate.duplicate is True
    assert connection.execute("SELECT COUNT(*) FROM task_failures").fetchone()[0] == 1
    dead = store.record_failure(
        job_id=job.id, org_id=org_id, attempt_count=2, error_class="transient",
        error_code="TIMEOUT-2", message_redacted="temporary", trace_id="trace-2", occurred_at=now,
    )
    assert dead.status == "dead_letter"
    assert dead.code == "MAX_ATTEMPTS_EXCEEDED"


def test_deterministic_unknown_tenant_and_dead_requeue() -> None:
    from infra.foundation.task_failure import (
        RetryNotAllowedError,
        RetryPolicy,
        TaskFailureStore,
        TenantScopeViolationError,
    )

    connection = _fixture()
    org_id, other_org = str(uuid4()), str(uuid4())
    deterministic_job = _job(connection, org_id=org_id)
    unknown_job = _job(connection, org_id=org_id)
    dead_job = _job(connection, org_id=org_id, max_attempts=1)
    connection.commit()
    store = TaskFailureStore(connection, policy=RetryPolicy(backoff_base_ms=10, backoff_cap_ms=10))
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    deterministic = store.record_failure(
        job_id=deterministic_job.id, org_id=org_id, attempt_count=1,
        error_class="deterministic", error_code="BAD_INPUT", trace_id="trace-d", occurred_at=now,
    )
    assert deterministic.status == "failed"
    assert deterministic.code == "RETRY_NOT_ALLOWED"
    with pytest.raises(RetryNotAllowedError):
        store.retry(job_id=deterministic_job.id, org_id=org_id, trace_id="trace-r", now=now)
    unknown = store.record_failure(
        job_id=unknown_job.id, org_id=org_id, attempt_count=1,
        error_class="unknown", error_code="PROVIDER_UNKNOWN", trace_id="trace-u", occurred_at=now,
    )
    assert unknown.human_task is not None
    assert unknown.code == "UNKNOWN_RESULT_REQUIRES_REVIEW"
    with pytest.raises(TenantScopeViolationError):
        store.record_failure(
            job_id=unknown_job.id, org_id=other_org, attempt_count=1,
            error_class="transient", error_code="CROSS", trace_id="trace-x", occurred_at=now,
        )
    store.record_failure(
        job_id=dead_job.id, org_id=org_id, attempt_count=1,
        error_class="transient", error_code="LIMIT", trace_id="trace-l", occurred_at=now,
    )
    requeued = store.requeue_dead(
        job_id=dead_job.id, org_id=org_id, reason="operator review", idempotency_key="requeue-1",
        trace_id="trace-requeue", now=now,
    )
    assert requeued.id != dead_job.id
    assert requeued.status == "queued"
    assert requeued.replayed_from_job_id == dead_job.id
    assert requeued.replayed_from_attempt_count == 1
    assert connection.execute("SELECT COUNT(*) FROM task_failures WHERE job_id = ?", (dead_job.id,)).fetchone()[0] == 1


def test_worker_only_retry_commands_round_trip() -> None:
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from infra.foundation.task_failure import RetryPolicy, TaskFailureStore

    connection = _fixture()
    org_id = str(uuid4())
    job = _job(connection, org_id=org_id, max_attempts=2)
    connection.commit()
    store = TaskFailureStore(connection, policy=RetryPolicy(backoff_base_ms=10, backoff_cap_ms=10))
    store.record_failure(
        job_id=job.id, org_id=org_id, attempt_count=1, error_class="transient",
        error_code="TIMEOUT", trace_id="trace-1", occurred_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    client = TestClient(create_app(task_failure_store=store))
    assert client.post(f"/internal/task-jobs/{job.id}:retry", json={"org_id": org_id}).status_code == 403
    body_fallback = client.post(
        f"/internal/task-jobs/{job.id}:retry",
        headers={"X-Worker-Id": "worker"},
        json={"org_id": org_id, "idempotency_key": "body-key-only"},
    )
    assert body_fallback.status_code == 400
    assert body_fallback.json()["detail"]["code"] == "INVALID_RETRY_COMMAND"
    short_header = client.post(
        f"/internal/task-jobs/{job.id}:retry",
        headers={"X-Worker-Id": "worker", "Idempotency-Key": "short"},
        json={"org_id": org_id},
    )
    assert short_header.status_code == 400
    assert short_header.json()["detail"]["code"] == "INVALID_RETRY_COMMAND"
    response = client.post(
        f"/internal/task-jobs/{job.id}:retry",
        headers={"X-Worker-Id": "worker", "Idempotency-Key": "retry-api-1"},
        json={"org_id": org_id, "trace_id": "trace-api"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "retry_scheduled"


def test_failure_attempt_count_cannot_jump_ahead() -> None:
    from infra.foundation.task_failure import InvalidTaskFailureError, TaskFailureStore

    connection = _fixture()
    org_id = str(uuid4())
    job = _job(connection, org_id=org_id, max_attempts=3)
    connection.commit()
    store = TaskFailureStore(connection)
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)

    with pytest.raises(InvalidTaskFailureError):
        store.record_failure(
            job_id=job.id,
            org_id=org_id,
            attempt_count=3,
            error_class="transient",
            error_code="JUMPED_ATTEMPT",
            trace_id="trace-jump",
            occurred_at=now,
        )

    assert connection.execute("SELECT COUNT(*) FROM task_failures").fetchone()[0] == 0
    assert connection.execute(
        "SELECT attempt_count, status FROM task_jobs WHERE id = ?", (job.id,)
    ).fetchone() == (0, "queued")
