from datetime import datetime, timedelta, timezone
import sqlite3
from uuid import uuid4

import pytest

from test_found_004d_failure_retry_integration import _fixture, _job


def test_facade_records_failure_and_state_transition_once():
    from infra.foundation.task_failure import RetryPolicy, TaskFailureStore
    from infra.foundation.task_failure_facade import FailureCommand, TaskFailureFacade

    connection = _fixture()
    org_id = str(uuid4())
    job = _job(connection, org_id=org_id, max_attempts=2)
    connection.commit()
    result = TaskFailureFacade(TaskFailureStore(connection, policy=RetryPolicy(backoff_base_ms=1, backoff_cap_ms=1))).handle(
        FailureCommand(job_id=job.id, org_id=org_id, error_class="transient", error_code="TIMEOUT", trace_id="trace-facade", attempt_count=1, occurred_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
    )
    assert result.status == "retry_scheduled"
    assert connection.execute("SELECT COUNT(*) FROM task_failures WHERE job_id = ?", (job.id,)).fetchone()[0] == 1
    assert connection.execute("SELECT status FROM task_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "retry_scheduled"


def test_lease_bound_facade_rejects_wrong_worker_or_token():
    from infra.foundation.task_claim import TaskClaimStore
    from infra.foundation.task_failure import RetryPolicy, TaskFailureStore, InvalidTaskFailureError
    from infra.foundation.task_failure_facade import FailureCommand, TaskFailureFacade

    connection = _fixture()
    org_id = str(uuid4())
    job = _job(connection, org_id=org_id)
    connection.commit()
    lease = TaskClaimStore(connection, lease_seconds=30).claim(org_id=org_id, worker_id="worker-a", now=datetime(2026, 9, 16, tzinfo=timezone.utc))[0]
    facade = TaskFailureFacade(TaskFailureStore(connection, policy=RetryPolicy(backoff_base_ms=1, backoff_cap_ms=1)))
    with pytest.raises(InvalidTaskFailureError):
        facade.handle(FailureCommand(job_id=job.id, org_id=org_id, error_class="deterministic", error_code="BAD", trace_id="t", lease_token=lease.lease_token, worker_id="worker-b", occurred_at=datetime(2026, 9, 16, tzinfo=timezone.utc)))
    assert connection.execute("SELECT COUNT(*) FROM task_failures").fetchone()[0] == 0


def claimed():
    from infra.foundation.task_claim import TaskClaimStore

    connection = _fixture()
    org_id = str(uuid4())
    job = _job(connection, org_id=org_id)
    connection.commit()
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    claims = TaskClaimStore(connection, lease_seconds=30)
    lease = claims.claim(org_id=org_id, worker_id="worker-a", now=now)[0]
    return connection, claims, lease, now


def test_legacy_fail_writes_fact_and_clears_lease_atomically():
    connection, claims, lease, now = claimed()
    result = claims.fail(job_id=lease.job_id, org_id=lease.job.org_id,
                         lease_token=lease.lease_token, worker_id="worker-a",
                         error="synthetic failure", now=now)
    assert result.status == "failed"
    assert connection.execute("SELECT error_class, attempt_count FROM task_failures").fetchall() == [("deterministic", 1)]
    assert connection.execute("SELECT COUNT(*) FROM task_job_leases").fetchone()[0] == 0


def test_failure_mid_transaction_rolls_back_fact_state_and_lease():
    connection, claims, lease, now = claimed()
    connection.execute("""CREATE TRIGGER reject_failure_update BEFORE UPDATE ON task_jobs
        WHEN NEW.status = 'failed' BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END""")
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="synthetic write failure"):
        claims.fail(job_id=lease.job_id, org_id=lease.job.org_id,
                    lease_token=lease.lease_token, worker_id="worker-a", error="synthetic", now=now)
    assert connection.execute("SELECT COUNT(*) FROM task_failures").fetchone()[0] == 0
    assert connection.execute("SELECT status FROM task_jobs").fetchone()[0] == "leased"
    assert connection.execute("SELECT lease_token FROM task_job_leases").fetchone()[0] == lease.lease_token


@pytest.mark.parametrize("change", ["missing", "expired", "wrong_attempt", "wrong_token", "wrong_tenant"])
def test_leased_failure_rejects_invalid_ownership_without_writes(change):
    from infra.foundation.task_failure import TaskFailureStore, TaskFailureError

    connection, _, lease, now = claimed()
    args = dict(job_id=lease.job_id, org_id=lease.job.org_id, lease_token=lease.lease_token,
                worker_id="worker-a", error_class="transient", error_code="TEST",
                trace_id="trace", occurred_at=now, attempt_count=lease.job.attempt_count)
    if change == "missing":
        args["lease_token"] = None
    elif change == "expired":
        args["occurred_at"] = now + timedelta(seconds=30)
    elif change == "wrong_attempt":
        args["attempt_count"] += 1
    elif change == "wrong_token":
        args["lease_token"] = "invalid"
    else:
        args["org_id"] = str(uuid4())
    with pytest.raises(TaskFailureError):
        TaskFailureStore(connection).record_failure(**args)
    assert connection.execute("SELECT COUNT(*) FROM task_failures").fetchone()[0] == 0
    assert connection.execute("SELECT status FROM task_jobs").fetchone()[0] == "leased"
