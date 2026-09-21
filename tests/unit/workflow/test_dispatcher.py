from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.workflow import DispatchError, OutboxDispatcher


def _event(dispatcher: OutboxDispatcher, org_id, available_at=None):
    return dispatcher.append_event(
        org_id=org_id,
        event_type="workflow.step.queued",
        trace_id="trace-003",
        aggregate_type="workflow_step",
        aggregate_id=uuid4(),
        aggregate_version=1,
        idempotency_key="event-003",
        payload={
            "task_job": {
                "job_type": "workflow.step",
                "queue_name": "default",
                "payload_ref": "private://workflow/step-1",
                "payload": {"step": "review"},
                "max_attempts": 2,
            }
        },
        available_at=available_at,
    )


def test_dispatch_publishes_once_and_creates_idempotent_task_job() -> None:
    dispatcher = OutboxDispatcher()
    org_id = uuid4()
    event = _event(dispatcher, org_id)
    first = dispatcher.dispatch_once(worker_id="worker-a", idempotency_key="dispatch-1", org_id=org_id)
    second = dispatcher.dispatch_once(worker_id="worker-a", idempotency_key="dispatch-1", org_id=org_id)
    assert first == second
    assert dispatcher.events[event.event_id].status == "published"
    assert len(dispatcher.jobs) == 1
    assert len(dispatcher.dispatch_attempts) == 1


def test_claim_retry_and_replay_preserve_tenant_and_source() -> None:
    dispatcher = OutboxDispatcher(max_attempts=2)
    org_id = uuid4()
    _event(dispatcher, org_id)
    dispatcher.dispatch_once(worker_id="worker-a", idempotency_key="dispatch-2", org_id=org_id)
    job = next(iter(dispatcher.jobs.values()))
    claimed = dispatcher.claim_job(org_id=org_id, job_id=job.id, worker_id="worker-a", idempotency_key="claim-1")
    assert claimed.status == "leased"
    failed = dispatcher.retry_job(org_id=org_id, job_id=job.id, error_class="deterministic", error="bad input", idempotency_key="retry-1")
    assert failed.status == "dead_letter"
    replay = dispatcher.replay_job(org_id=org_id, job_id=job.id, reason="corrected input", idempotency_key="replay-1", trace_id="trace-replay")
    assert replay.replayed_from_job_id == job.id
    assert dispatcher.replay_job(org_id=org_id, job_id=job.id, reason="corrected input", idempotency_key="replay-1", trace_id="other") == replay
    with pytest.raises(DispatchError) as error:
        dispatcher.claim_job(org_id=uuid4(), job_id=job.id, worker_id="worker-b", idempotency_key="claim-other")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_expired_lease_can_be_reclaimed_and_key_reuse_is_rejected() -> None:
    dispatcher = OutboxDispatcher(lease_seconds=5)
    org_id = uuid4()
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    _event(dispatcher, org_id, available_at=now)
    dispatcher.dispatch_once(worker_id="worker-a", idempotency_key="dispatch-3", org_id=org_id, now=now)
    job = next(iter(dispatcher.jobs.values()))
    dispatcher.claim_job(org_id=org_id, job_id=job.id, worker_id="worker-a", idempotency_key="claim-2", now=now)
    reclaimed = dispatcher.claim_job(org_id=org_id, job_id=job.id, worker_id="worker-b", idempotency_key="claim-3", now=now + timedelta(seconds=6))
    assert reclaimed.locked_by == "worker-b"
    with pytest.raises(DispatchError) as error:
        dispatcher.retry_job(org_id=org_id, job_id=job.id, error_class="transient", error="different", idempotency_key="claim-3")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
