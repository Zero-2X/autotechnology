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


def _fixture() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(TASK_MIGRATION.read_text(encoding="utf-8"))
    connection.executescript(FAILURE_DDL)
    connection.executescript(HUMAN_DDL)
    connection.commit()
    return connection


def _job(connection: sqlite3.Connection, *, org_id: str, status: str = "queued", payload_ref: str = "private://fixture/input", max_attempts: int = 3):
    from infra.foundation.task_queue import TaskJobQueue

    job = TaskJobQueue(connection).enqueue(
        org_id=org_id,
        job_type="render",
        aggregate_type="Content",
        aggregate_id=str(uuid4()),
        aggregate_version=2,
        payload_ref=payload_ref,
        idempotency_key=str(uuid4()),
        trace_id="trace-source",
        max_attempts=max_attempts,
        now=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    if status != "queued":
        connection.execute("UPDATE task_jobs SET status = ?, attempt_count = 1 WHERE id = ?", (status, job.id))
        connection.commit()
        from infra.foundation.task_queue import TaskJob
        row = connection.execute("SELECT * FROM task_jobs WHERE id = ?", (job.id,)).fetchone()
        columns = [item[1] for item in connection.execute("PRAGMA table_info(task_jobs)")]
        job = TaskJob(**dict(zip(columns, row)))
    return job


def test_replay_creates_new_job_and_is_idempotent_without_mutating_source() -> None:
    from infra.foundation.task_replay import TaskReplayStore

    connection = _fixture()
    org_id = str(uuid4())
    source = _job(connection, org_id=org_id, status="failed")
    store = TaskReplayStore(connection, policy_checker=lambda job: True, kill_switch_checker=lambda job: True)
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    first = store.replay(
        source_job_id=source.id, org_id=org_id, source_attempt_count=1,
        reason="operator replay", idempotency_key="replay-key-1", trace_id="trace-replay", now=now,
    )
    assert first.job.id != source.id
    assert first.job.status == "queued"
    assert first.job.payload_ref == source.payload_ref
    assert first.job.payload_hash == source.payload_hash
    assert first.job.aggregate_version == source.aggregate_version
    assert first.job.replayed_from_job_id == source.id
    assert first.job.replayed_from_attempt_count == 1
    assert "operator replay" in (first.job.replay_reason or "")
    second = store.replay(
        source_job_id=source.id, org_id=org_id, source_attempt_count=1,
        reason="operator replay", idempotency_key="replay-key-1", trace_id="trace-other", now=now,
    )
    assert second.duplicate is True
    assert second.job.id == first.job.id
    unchanged = connection.execute("SELECT status, attempt_count, payload_ref FROM task_jobs WHERE id = ?", (source.id,)).fetchone()
    assert unchanged == ("failed", 1, source.payload_ref)


def test_replay_rejects_state_version_tenant_secret_and_policy() -> None:
    from infra.foundation.task_replay import (
        ReplayNotAllowedError,
        ReplaySecretInputError,
        ReplaySourceNotFoundError,
        ReplayVersionConflictError,
        TaskReplayStore,
        TenantScopeViolationError,
    )

    connection = _fixture()
    org_id, other_org = str(uuid4()), str(uuid4())
    source = _job(connection, org_id=org_id, status="failed")
    store = TaskReplayStore(connection)
    with pytest.raises(ReplayVersionConflictError):
        store.replay(source_job_id=source.id, org_id=org_id, source_attempt_count=0, reason="bad", idempotency_key="k0", trace_id="t")
    with pytest.raises(ReplaySourceNotFoundError):
        store.replay(source_job_id=str(uuid4()), org_id=org_id, source_attempt_count=1, reason="missing", idempotency_key="k-missing", trace_id="t")
    with pytest.raises(TenantScopeViolationError):
        store.replay(source_job_id=source.id, org_id=other_org, source_attempt_count=1, reason="cross", idempotency_key="k1", trace_id="t")
    other_source = _job(connection, org_id=org_id, status="failed")
    store.replay(source_job_id=source.id, org_id=org_id, source_attempt_count=1, reason="same-key", idempotency_key="k2", trace_id="t")
    with pytest.raises(ReplayVersionConflictError):
        store.replay(source_job_id=other_source.id, org_id=org_id, source_attempt_count=1, reason="same-key", idempotency_key="k2", trace_id="t")
    # The source is failed and therefore replayable; a policy hook can reject it.
    reject = TaskReplayStore(connection, policy_checker=lambda job: False)
    with pytest.raises(ReplayNotAllowedError):
        reject.replay(source_job_id=source.id, org_id=org_id, source_attempt_count=1, reason="policy", idempotency_key="k3", trace_id="t")
    secret = _job(connection, org_id=org_id, status="failed", payload_ref="private://fixture/secret/token-ref")
    with pytest.raises(ReplaySecretInputError):
        store.replay(source_job_id=secret.id, org_id=org_id, source_attempt_count=1, reason="secret", idempotency_key="k4", trace_id="t")
    running = _job(connection, org_id=org_id, status="running")
    with pytest.raises(ReplayNotAllowedError):
        store.replay(source_job_id=running.id, org_id=org_id, source_attempt_count=1, reason="running", idempotency_key="k5", trace_id="t")


def test_unknown_result_requires_completed_human_review() -> None:
    from infra.foundation.task_failure import TaskFailureStore
    from infra.foundation.task_replay import ReplayNotAllowedError, TaskReplayStore

    connection = _fixture()
    org_id = str(uuid4())
    source = _job(connection, org_id=org_id, status="queued")
    failure_store = TaskFailureStore(connection)
    failure_store.record_failure(
        job_id=source.id, org_id=org_id, attempt_count=1, error_class="unknown",
        error_code="PROVIDER_UNKNOWN", trace_id="trace-u", occurred_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    replay_store = TaskReplayStore(connection)
    with pytest.raises(ReplayNotAllowedError):
        replay_store.replay(source_job_id=source.id, org_id=org_id, source_attempt_count=1, reason="review", idempotency_key="uk1", trace_id="t")
    connection.execute("UPDATE human_tasks SET status = 'completed' WHERE org_id = ? AND task_type = 'unknown_result'", (org_id,))
    connection.commit()
    replayed = replay_store.replay(source_job_id=source.id, org_id=org_id, source_attempt_count=1, reason="reviewed", idempotency_key="uk2", trace_id="t")
    assert replayed.source_failure_id


def test_worker_only_replay_command() -> None:
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from infra.foundation.task_replay import TaskReplayStore

    connection = _fixture()
    org_id = str(uuid4())
    source = _job(connection, org_id=org_id, status="failed")
    client = TestClient(create_app(task_replay_store=TaskReplayStore(connection)))
    body = {"source_job_id": source.id, "source_attempt_count": 1, "reason": "api replay", "org_id": org_id, "trace_id": "trace-api"}
    assert client.post(f"/internal/task-jobs/{source.id}:replay", json=body).status_code == 403
    body_fallback = client.post(
        f"/internal/task-jobs/{source.id}:replay",
        headers={"X-Worker-Id": "worker"},
        json={**body, "idempotency_key": "body-key-only"},
    )
    assert body_fallback.status_code == 400
    assert body_fallback.json()["detail"]["code"] == "INVALID_REPLAY_COMMAND"
    response = client.post(
        f"/internal/task-jobs/{source.id}:replay",
        headers={"X-Worker-Id": "worker", "Idempotency-Key": "api-replay-1"},
        json=body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["job"]["replayed_from_job_id"] == source.id
