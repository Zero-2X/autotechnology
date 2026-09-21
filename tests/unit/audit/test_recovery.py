from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.audit import AuditLogService, RecoveryError, RecoveryService


def test_synthetic_backup_is_tenant_scoped_and_idempotent() -> None:
    service = RecoveryService()
    org_id = uuid4()
    captured = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)
    first = service.create_backup(
        org_id=org_id, database_payload={"rows": [1]}, object_payload={"files": ["a"]},
        latest_event_at=captured - timedelta(minutes=5), captured_at=captured,
        idempotency_key="backup-1", trace_id="trace-r1",
    )
    second = service.create_backup(
        org_id=org_id, database_payload={"rows": [1]}, object_payload={"files": ["a"]},
        latest_event_at=captured - timedelta(minutes=5), captured_at=captured,
        idempotency_key="backup-1", trace_id="trace-r1",
    )
    assert first == second
    with pytest.raises(RecoveryError) as error:
        service.restore(org_id=uuid4(), snapshot_id=first.id, failure_started_at=captured,
                        idempotency_key="restore-other", trace_id="trace-r1")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_restore_measures_rpo_rto_and_pauses_queues_until_release() -> None:
    audit = AuditLogService()
    service = RecoveryService(audit_log=audit)
    org_id = uuid4()
    failure = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)
    snapshot = service.create_backup(
        org_id=org_id, database_payload={"rows": [1]}, object_payload={"files": ["a"]},
        latest_event_at=failure - timedelta(minutes=10), captured_at=failure - timedelta(minutes=2),
        idempotency_key="backup-2", trace_id="trace-r2",
    )
    restored = service.restore(
        org_id=org_id, snapshot_id=snapshot.id, failure_started_at=failure,
        restored_at=failure + timedelta(minutes=20), latest_recovered_event_at=failure - timedelta(minutes=10),
        idempotency_key="restore-1", trace_id="trace-r2", queue_names=("default", "priority"),
    )
    assert restored.measurement.target_met is True
    assert restored.queues_paused is True
    assert all(state.paused for state in service.queue_states.values())
    released = service.release_queues(org_id=org_id, restore_id=restored.id, expected_version=restored.version,
                                     idempotency_key="release-1", trace_id="trace-r2")
    assert released.queues_paused is False
    assert all(not state.paused for state in service.queue_states.values())
    assert [entry.action for entry in audit.entries] == ["backup.created", "restore.completed", "restore.queues_released"]


def test_restore_keeps_queues_paused_when_rpo_or_rto_target_fails() -> None:
    service = RecoveryService()
    org_id = uuid4()
    failure = datetime(2026, 9, 18, 10, tzinfo=timezone.utc)
    snapshot = service.create_backup(
        org_id=org_id, database_payload={"rows": []}, object_payload={},
        latest_event_at=failure - timedelta(minutes=120), captured_at=failure - timedelta(minutes=1),
        idempotency_key="backup-3", trace_id="trace-r3",
    )
    restored = service.restore(
        org_id=org_id, snapshot_id=snapshot.id, failure_started_at=failure,
        restored_at=failure + timedelta(minutes=300), latest_recovered_event_at=failure - timedelta(minutes=120),
        idempotency_key="restore-2", trace_id="trace-r3", missing_event_count=2,
    )
    assert restored.measurement.target_met is False
    with pytest.raises(RecoveryError) as error:
        service.release_queues(org_id=org_id, restore_id=restored.id, expected_version=restored.version,
                               idempotency_key="release-2", trace_id="trace-r3")
    assert error.value.code == "RECOVERY_TARGET_NOT_MET"


def test_implicit_restore_time_replays_without_advancing_clock() -> None:
    service = RecoveryService()
    org_id = uuid4()
    failure = datetime.now(timezone.utc) - timedelta(seconds=1)
    snapshot = service.create_backup(org_id=org_id, database_payload={"rows": []}, object_payload={},
        latest_event_at=failure, captured_at=failure, idempotency_key="b", trace_id="t")
    first = service.restore(org_id=org_id, snapshot_id=snapshot.id, failure_started_at=failure,
        idempotency_key="r", trace_id="t")
    assert service.restore(org_id=org_id, snapshot_id=snapshot.id, failure_started_at=failure,
        idempotency_key="r", trace_id="t") == first
