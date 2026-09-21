import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from infra.foundation.storage import FakeStorage
from infra.foundation.task_claim import TaskClaimStore
from infra.foundation.task_queue import TaskJobQueue
from modules.audit.infrastructure.local_recovery import LocalRecoveryDrill
from modules.audit.recovery import RecoveryError, RecoveryService


ROOT = Path(__file__).resolve().parents[2]
TASK_DDL = ROOT / "packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"
LEASE_DDL = """CREATE TABLE task_job_leases (
    job_id TEXT NOT NULL PRIMARY KEY, org_id TEXT NOT NULL, worker_id TEXT NOT NULL,
    lease_token TEXT NOT NULL UNIQUE, lease_until TEXT NOT NULL, claimed_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL, claim_version INTEGER NOT NULL DEFAULT 1)
"""


def test_restore_recreates_database_objects_and_blocks_worker_until_release(tmp_path) -> None:
    org_id = uuid4()
    now = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)
    source = sqlite3.connect(":memory:")
    source.executescript(TASK_DDL.read_text(encoding="utf-8"))
    source.execute(LEASE_DDL)
    job = TaskJobQueue(source).enqueue(org_id=str(org_id), job_type="render", aggregate_type="Content",
        aggregate_id=str(uuid4()), aggregate_version=1, payload_ref="private://fixture/input",
        idempotency_key="fixture-job", trace_id="trace-r", now=now)
    source.commit()
    objects = FakeStorage()
    original = objects.put(str(org_id), "fixture/body.txt", b"synthetic evidence", content_type="text/plain")
    drill = LocalRecoveryDrill(tmp_path / "backups", RecoveryService())
    backup = drill.backup(org_id=org_id, database=source, object_store=objects,
        latest_event_at=now, captured_at=now + timedelta(minutes=1),
        idempotency_key="backup-local", trace_id="trace-r")
    source.execute("DELETE FROM task_jobs")
    source.commit()
    objects.delete(str(org_id), original.storage_object_ref)

    restored_objects = FakeStorage()
    restored = drill.restore(org_id=org_id, snapshot_id=backup.id, object_store=restored_objects,
        failure_started_at=now + timedelta(minutes=2), restored_at=now + timedelta(minutes=20),
        idempotency_key="restore-local", trace_id="trace-r")
    assert restored.connection.execute("SELECT id FROM task_jobs").fetchone()[0] == job.id
    assert restored_objects.get(str(org_id), original.storage_object_ref) == b"synthetic evidence"
    claims = TaskClaimStore(restored.connection)
    assert claims.claim(org_id=str(org_id), worker_id="worker-a", now=now + timedelta(minutes=21)) == ()
    released = drill.release(org_id=org_id, restore_id=restored.run.id,
        expected_version=restored.run.version, idempotency_key="release-local", trace_id="trace-r")
    assert released.queues_paused is False
    assert claims.claim(org_id=str(org_id), worker_id="worker-a", now=now + timedelta(minutes=21))[0].job.id == job.id


def test_corrupt_backup_is_rejected_before_target_mutation(tmp_path) -> None:
    org_id = uuid4()
    now = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)
    drill = LocalRecoveryDrill(tmp_path, RecoveryService())
    backup = drill.backup(org_id=org_id, database=sqlite3.connect(":memory:"), object_store=FakeStorage(),
        latest_event_at=now, captured_at=now, idempotency_key="backup-corrupt", trace_id="trace-c")
    (tmp_path / str(org_id) / str(backup.id) / "database.sqlite").write_bytes(b"corrupt")
    target = FakeStorage()
    with pytest.raises(RecoveryError) as error:
        drill.restore(org_id=org_id, snapshot_id=backup.id, object_store=target,
            failure_started_at=now, restored_at=now + timedelta(minutes=1),
            idempotency_key="restore-corrupt", trace_id="trace-c")
    assert error.value.code == "BACKUP_VERIFICATION_FAILED"
    assert target.list(str(org_id)) == ()
