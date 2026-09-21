from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from infra.foundation.database import create_connection_fixture
from infra.foundation.task_queue import (
    TaskJobQueue,
    TaskQueueConflictError,
)


ROOT = Path(__file__).resolve().parents[2]
ROOT_MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"


def _job_args(*, org_id: str, key: str, payload_ref: str = "private://fixture/tenant/org-a/input") -> dict:
    return {
        "org_id": org_id,
        "job_type": "render",
        "aggregate_type": "Content",
        "aggregate_id": str(uuid4()),
        "aggregate_version": 1,
        "payload_ref": payload_ref,
        "idempotency_key": key,
        "trace_id": f"trace-{key}",
    }


def test_dbapi_queue_enqueues_idempotently_and_polls_without_redis() -> None:
    with create_connection_fixture() as fixture:
        migration = ROOT_MIGRATION.read_text(encoding="utf-8")
        fixture.connection.executescript(migration)
        queue = TaskJobQueue(fixture.connection)
        org_id = str(uuid4())
        now = datetime(2026, 9, 16, tzinfo=timezone.utc)
        args = _job_args(org_id=org_id, key="same")
        first = queue.enqueue(**args, now=now)
        replay = queue.enqueue(**args, now=now + timedelta(seconds=30))
        assert replay.id == first.id
        assert replay.payload_hash == first.payload_hash
        with pytest.raises(TaskQueueConflictError):
            conflict_args = {**args, "payload_ref": "private://fixture/tenant/org-a/other"}
            queue.enqueue(**conflict_args, now=now)
        fixture.connection.commit()
        ready = queue.poll_ready(org_id=org_id, now=now + timedelta(seconds=1))
        assert [job.id for job in ready] == [first.id]
        assert ready[0].status == "queued"


def test_polling_is_tenant_scoped_stable_and_does_not_mutate_state() -> None:
    with create_connection_fixture() as fixture:
        migration = ROOT_MIGRATION.read_text(encoding="utf-8")
        fixture.connection.executescript(migration)
        queue = TaskJobQueue(fixture.connection)
        now = datetime(2026, 9, 16, tzinfo=timezone.utc)
        org_a = str(uuid4())
        org_b = str(uuid4())
        first = queue.enqueue(**_job_args(org_id=org_a, key="a"), now=now)
        second = queue.enqueue(
            **_job_args(org_id=org_a, key="b"),
            now=now,
            available_at=now + timedelta(minutes=5),
        )
        queue.enqueue(**_job_args(org_id=org_b, key="other"), now=now)
        fixture.connection.commit()
        jobs = queue.poll_ready(org_id=org_a, now=now + timedelta(seconds=1))
        assert [job.id for job in jobs] == [first.id]
        assert second.status == "queued"
        assert fixture.connection.execute(
            "SELECT status FROM task_jobs WHERE id = ?", (first.id,)
        ).fetchone() == ("queued",)
