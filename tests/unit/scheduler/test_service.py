from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from apps.scheduler import SchedulerError, SchedulerService


NOW = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)


def test_scheduler_uses_immutable_region_version_and_utc_cron_calculation() -> None:
    service = SchedulerService()
    org_id = uuid4()
    region_version = uuid4()
    job = service.create_job(
        org_id=org_id, job_type="refresh", schedule="0 9 * * *",
        region_profile_version_id=region_version, timezone_name="Asia/Shanghai",
        idempotency_key="schedule-1", now=NOW,
    )
    assert job.as_contract()["status"] == "active"
    state = service._state[job.id]
    assert state["next_run_at"] == datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)
    assert state["region_profile_version_id"] == region_version


def test_due_claim_is_idempotent_and_completion_advances_once() -> None:
    service = SchedulerService()
    org_id = uuid4()
    job = service.create_job(
        org_id=org_id, job_type="refresh", schedule="interval:60",
        region_profile_version_id=uuid4(), idempotency_key="schedule-2",
        now=NOW, first_run_at=NOW,
    )
    leases = service.claim_due(org_id=org_id, worker_id="worker-a", idempotency_key="claim-1", now=NOW)
    assert len(leases) == 1
    assert service.claim_due(org_id=org_id, worker_id="worker-a", idempotency_key="claim-1", now=NOW) == leases
    completed = service.complete(org_id=org_id, lease=leases[0], expected_version=leases[0].claim_version, idempotency_key="complete-1", now=NOW + timedelta(seconds=1))
    assert completed.id == job.id
    assert service.claim_due(org_id=org_id, worker_id="worker-a", idempotency_key="claim-2", now=NOW + timedelta(seconds=1)) == ()
    assert len(service.claim_due(org_id=org_id, worker_id="worker-a", idempotency_key="claim-3", now=NOW + timedelta(seconds=61))) == 1


def test_pause_resume_does_not_catch_up_old_occurrence_and_tenant_isolation_is_strict() -> None:
    service = SchedulerService()
    org_id = uuid4()
    job = service.create_job(
        org_id=org_id, job_type="refresh", schedule="interval:60",
        region_profile_version_id=uuid4(), idempotency_key="schedule-3", now=NOW, first_run_at=NOW,
    )
    paused = service.pause(org_id=org_id, job_id=job.id, expected_version=0, idempotency_key="pause-1")
    assert service.claim_due(org_id=org_id, worker_id="worker-a", idempotency_key="claim-paused", now=NOW + timedelta(hours=1)) == ()
    resumed = service.resume(org_id=org_id, job_id=job.id, expected_version=1, idempotency_key="resume-1", now=NOW + timedelta(hours=1))
    assert resumed.status == "active"
    assert service._state[job.id]["next_run_at"] == NOW + timedelta(hours=1, seconds=60)
    with pytest.raises(SchedulerError) as error:
        service.pause(org_id=uuid4(), job_id=job.id, expected_version=2, idempotency_key="cross")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_expired_lease_can_be_reclaimed_and_command_key_conflicts_are_rejected() -> None:
    service = SchedulerService()
    org_id = uuid4()
    job = service.create_job(
        org_id=org_id, job_type="refresh", schedule="once",
        region_profile_version_id=uuid4(), idempotency_key="schedule-4", now=NOW, first_run_at=NOW,
    )
    lease = service.claim_due(org_id=org_id, worker_id="worker-a", idempotency_key="claim-expire-1", now=NOW)[0]
    reclaimed = service.claim_due(org_id=org_id, worker_id="worker-b", idempotency_key="claim-expire-2", now=NOW + timedelta(seconds=31))[0]
    assert reclaimed.worker_id == "worker-b"
    with pytest.raises(SchedulerError) as error:
        service.claim_due(org_id=org_id, worker_id="worker-c", idempotency_key="claim-expire-2", now=NOW + timedelta(seconds=31), limit=2)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
