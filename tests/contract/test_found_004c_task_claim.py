from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "docs/tasks/FOUND-004C.md"
SCHEMA = ROOT / "packages/contracts/jsonschema/task-job.schema.json"
TASK_MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"
LEASE_MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_004c_task_leases.py"


def _job_args(org_id: str, key: str) -> dict[str, object]:
    return {
        "org_id": org_id,
        "job_type": "render",
        "aggregate_type": "Content",
        "aggregate_id": str(uuid4()),
        "aggregate_version": 1,
        "payload_ref": "private://fixture/tenant/input",
        "idempotency_key": key,
        "trace_id": f"trace-{key}",
    }


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import importlib.util
    import sqlite3

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa

    database = tmp_path / "task-claim.db"
    connection = sqlite3.connect(database)
    connection.executescript(TASK_MIGRATION.read_text(encoding="utf-8"))
    engine = sa.create_engine("sqlite:///:memory:", poolclass=sa.pool.StaticPool)
    sqlalchemy_connection = engine.connect()
    context = MigrationContext.configure(sqlalchemy_connection)
    module_spec = importlib.util.spec_from_file_location("found_004c", LEASE_MIGRATION)
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    original_op = module.op
    module.op = Operations(context)
    try:
        module.upgrade()
    finally:
        module.op = original_op
        sqlalchemy_connection.close()
        engine.dispose()
    # The migration above uses a separate SQLite fixture; create the lease
    # table on the file connection for the DB-API contract tests.
    connection.executescript(
        "CREATE TABLE task_job_leases ("
        "job_id TEXT NOT NULL PRIMARY KEY, org_id TEXT NOT NULL, worker_id TEXT NOT NULL, "
        "lease_token TEXT NOT NULL UNIQUE, lease_until TEXT NOT NULL, claimed_at TEXT NOT NULL, "
        "heartbeat_at TEXT NOT NULL, claim_version INTEGER NOT NULL DEFAULT 1 CHECK (claim_version >= 1));"
    )
    from infra.foundation.task_claim import TaskClaimStore

    return connection, TaskClaimStore(connection, lease_seconds=10)


def test_task_claim_contract_is_explicit_and_schema_aligned() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    task = TASK.read_text(encoding="utf-8")
    assert "lease_until" in schema["required"]
    assert "locked_by" in schema["required"]
    assert "claim(worker_id, lease_seconds)" in task
    assert "20260916_found_004c_task_leases.py" in task
    assert "JOB_NOT_CLAIMABLE" in task
    assert "LEASE_TOKEN_INVALID" in task


def test_claim_heartbeat_complete_and_fail_validate_token_and_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infra.foundation.task_queue import TaskJobQueue
    from infra.foundation.task_claim import (
        JobVersionConflictError,
        LeaseTokenInvalidError,
    )

    connection, claims = _store(tmp_path, monkeypatch)
    org_id = str(uuid4())
    queue = TaskJobQueue(connection)
    job = queue.enqueue(**_job_args(org_id, "claim"), now=datetime(2026, 9, 16, tzinfo=timezone.utc))
    connection.commit()
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    lease = claims.claim(org_id=org_id, worker_id="worker-a", now=now)[0]
    assert lease.job.status == "leased"
    assert lease.job.attempt_count == 1
    refreshed = claims.heartbeat(job_id=job.id, lease_token=lease.lease_token, org_id=org_id, now=now + timedelta(seconds=2))
    assert refreshed.lease_until > lease.lease_until
    with pytest.raises(LeaseTokenInvalidError):
        claims.complete(job_id=job.id, lease_token="wrong", org_id=org_id, now=now + timedelta(seconds=3))
    with pytest.raises(JobVersionConflictError):
        claims.complete(job_id=job.id, lease_token=lease.lease_token, expected_version=99, org_id=org_id, now=now + timedelta(seconds=3))
    completed = claims.complete(job_id=job.id, lease_token=refreshed.lease_token, expected_version=1, org_id=org_id, now=now + timedelta(seconds=3))
    assert completed.status == "succeeded"
    assert connection.execute("SELECT COUNT(*) FROM task_job_leases").fetchone()[0] == 0


def test_expired_lease_is_reclaimed_and_old_token_cannot_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infra.foundation.task_queue import TaskJobQueue
    from infra.foundation.task_claim import LeaseTokenInvalidError

    connection, claims = _store(tmp_path, monkeypatch)
    org_id = str(uuid4())
    queue = TaskJobQueue(connection)
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    job = queue.enqueue(**_job_args(org_id, "reclaim"), now=now)
    connection.commit()
    first = claims.claim(org_id=org_id, worker_id="crashed-worker", now=now)[0]
    second = claims.claim(org_id=org_id, worker_id="recovery-worker", now=now + timedelta(seconds=11))[0]
    assert second.job.id == job.id
    assert second.lease_token != first.lease_token
    assert second.job.attempt_count == 2
    with pytest.raises(LeaseTokenInvalidError):
        claims.complete(job_id=job.id, lease_token=first.lease_token, org_id=org_id, now=now + timedelta(seconds=12))


def test_expired_lease_stops_at_max_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infra.foundation.task_claim import JobNotClaimableError
    from infra.foundation.task_queue import TaskJobQueue

    connection, claims = _store(tmp_path, monkeypatch)
    org_id = str(uuid4())
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    job = TaskJobQueue(connection).enqueue(
        **_job_args(org_id, "max-attempts"),
        max_attempts=1,
        now=now,
    )
    connection.commit()
    claims.claim(org_id=org_id, worker_id="crashed-worker", now=now)

    with pytest.raises(JobNotClaimableError):
        claims.claim(org_id=org_id, worker_id="recovery-worker", now=now + timedelta(seconds=11))

    assert connection.execute(
        "SELECT status, attempt_count, locked_by, lease_until FROM task_jobs WHERE id = ?",
        (job.id,),
    ).fetchone() == ("dead_letter", 1, None, None)
    assert connection.execute("SELECT COUNT(*) FROM task_job_leases").fetchone()[0] == 0
