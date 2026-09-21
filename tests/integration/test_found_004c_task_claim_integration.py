from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[2]
TASK_MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"


LEASE_DDL = """
CREATE TABLE task_job_leases (
    job_id TEXT NOT NULL PRIMARY KEY,
    org_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_token TEXT NOT NULL UNIQUE,
    lease_until TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    claim_version INTEGER NOT NULL DEFAULT 1 CHECK (claim_version >= 1)
)
"""


def _prepare(connection) -> None:
    connection.executescript(TASK_MIGRATION.read_text(encoding="utf-8"))
    connection.execute(LEASE_DDL)


def _args(org_id: str, key: str) -> dict[str, object]:
    return {
        "org_id": org_id,
        "job_type": "render",
        "aggregate_type": "Content",
        "aggregate_id": str(uuid4()),
        "aggregate_version": 1,
        "payload_ref": "private://fixture/input",
        "idempotency_key": key,
        "trace_id": f"trace-{key}",
    }


def test_only_one_worker_claims_a_task_and_second_gets_stable_error(tmp_path: Path) -> None:
    import sqlite3

    from infra.foundation.task_claim import JobNotClaimableError, TaskClaimStore
    from infra.foundation.task_queue import TaskJobQueue

    path = tmp_path / "concurrent.db"
    first_connection = sqlite3.connect(path)
    second_connection = sqlite3.connect(path)
    _prepare(first_connection)
    first_connection.commit()
    org_id = str(uuid4())
    job = TaskJobQueue(first_connection).enqueue(
        **_args(org_id, "concurrent"), now=datetime(2026, 9, 16, tzinfo=timezone.utc)
    )
    first_connection.commit()
    first = TaskClaimStore(first_connection, lease_seconds=10).claim(
        org_id=org_id, worker_id="worker-a", now=datetime(2026, 9, 16, tzinfo=timezone.utc)
    )[0]
    with pytest.raises(JobNotClaimableError) as exc_info:
        TaskClaimStore(second_connection, lease_seconds=10).claim(
            org_id=org_id, worker_id="worker-b", now=datetime(2026, 9, 16, tzinfo=timezone.utc)
        )
    assert exc_info.value.code == "JOB_NOT_CLAIMABLE"
    assert first.job.id == job.id


def test_worker_only_internal_claim_commands_round_trip(synthetic_database_connection) -> None:
    from fastapi.testclient import TestClient
    import sqlite3

    from apps.api.main import create_app
    from infra.foundation.task_claim import TaskClaimStore
    from infra.foundation.task_queue import TaskJobQueue

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    _prepare(connection)
    org_id = str(uuid4())
    job = TaskJobQueue(connection).enqueue(
        **_args(org_id, "api-claim"), now=datetime(2026, 9, 15, tzinfo=timezone.utc)
    )
    connection.commit()
    client = TestClient(create_app(task_claim_store=TaskClaimStore(connection, lease_seconds=30)))
    missing_worker = client.post("/internal/task-jobs:claim", json={"org_id": org_id})
    assert missing_worker.status_code == 403
    claimed = client.post(
        "/internal/task-jobs:claim",
        headers={"X-Worker-Id": "worker-api"},
        json={"org_id": org_id},
    )
    assert claimed.status_code == 200, claimed.text
    lease = claimed.json()["data"][0]
    assert lease["job_id"] == job.id
    heartbeat = client.post(
        f"/internal/task-jobs/{job.id}:heartbeat",
        headers={"X-Worker-Id": "worker-api"},
        json={"lease_token": lease["lease_token"], "org_id": org_id},
    )
    assert heartbeat.status_code == 200
    completed = client.post(
        f"/internal/task-jobs/{job.id}:complete",
        headers={"X-Worker-Id": "worker-api"},
        json={"lease_token": lease["lease_token"], "org_id": org_id, "expected_version": 1},
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == "succeeded"


def test_invalid_claim_command_is_a_stable_400() -> None:
    from fastapi.testclient import TestClient
    import sqlite3

    from apps.api.main import create_app
    from infra.foundation.task_claim import TaskClaimStore

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    _prepare(connection)
    client = TestClient(create_app(task_claim_store=TaskClaimStore(connection)))
    response = client.post(
        "/internal/task-jobs:claim",
        headers={"X-Worker-Id": "worker-api"},
        json={"org_id": "not-a-uuid", "limit": "not-an-integer"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_CLAIM_COMMAND"
