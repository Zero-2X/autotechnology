from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
from uuid import uuid4

from test_found_004d_failure_retry_integration import _fixture


NOW = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self) -> None:
        self.current = NOW

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class RecordingDispatcher:
    def __init__(self, count: int = 1) -> None:
        self.count = count
        self.calls: list[dict[str, object]] = []

    def dispatch_once(self, **kwargs):
        self.calls.append(kwargs)
        return tuple(object() for _ in range(self.count))


def _enqueue(connection: sqlite3.Connection, org_id: str, *, job_type: str = "render"):
    from infra.foundation.task_queue import TaskJobQueue

    job = TaskJobQueue(connection).enqueue(
        org_id=org_id,
        job_type=job_type,
        aggregate_type="Content",
        aggregate_id=str(uuid4()),
        aggregate_version=1,
        payload_ref="private://fixture/worker-input",
        idempotency_key=str(uuid4()),
        trace_id=f"trace-{uuid4()}",
        max_attempts=3,
        now=NOW,
    )
    connection.commit()
    return job


def _runtime(connection, org_id, handlers, *, clock=None, shutdown=None, dispatcher=None, capacity=None, **settings):
    from apps.worker.main import create_worker_runtime
    from apps.worker.runtime import ShutdownToken, WorkerSettings
    from infra.foundation.task_claim import TaskClaimStore
    from infra.foundation.task_failure import RetryPolicy, TaskFailureStore
    from infra.foundation.task_failure_facade import TaskFailureFacade

    clock = clock or FakeClock()
    claim_store = TaskClaimStore(connection, lease_seconds=30)
    failure_store = TaskFailureStore(
        connection,
        policy=RetryPolicy(backoff_base_ms=100, backoff_cap_ms=100, jitter=0),
    )
    runtime = create_worker_runtime(
        settings=WorkerSettings(worker_id="worker-runtime", org_id=org_id, **settings),
        claim_store=claim_store,
        failure_facade=TaskFailureFacade(failure_store),
        handlers=handlers,
        outbox_dispatcher=dispatcher,
        shutdown=shutdown or ShutdownToken(),
        clock=clock,
        sleeper=lambda _seconds: None,
        capacity_provider=capacity,
    )
    return runtime, clock


def test_worker_claims_starts_heartbeats_completes_and_dispatches_outbox() -> None:
    connection = _fixture()
    org_id = str(uuid4())
    job = _enqueue(connection, org_id)
    observed: dict[str, object] = {}
    dispatcher = RecordingDispatcher(count=2)
    clock = FakeClock()

    def handler(received, context) -> None:
        observed["payload_ref"] = received.payload_ref
        clock.advance(11)
        context.checkpoint()
        observed["heartbeat_at"] = connection.execute(
            "SELECT heartbeat_at FROM task_job_leases WHERE job_id = ?", (received.id,)
        ).fetchone()[0]

    runtime, _ = _runtime(connection, org_id, {"render": handler}, clock=clock, dispatcher=dispatcher)
    tick = runtime.run_once()

    assert tick.status == "ok"
    assert (tick.claimed_jobs, tick.completed_jobs, tick.failed_jobs, tick.outbox_events) == (1, 1, 0, 2)
    assert observed["payload_ref"] == "private://fixture/worker-input"
    assert str(observed["heartbeat_at"]).startswith("2026-09-18T08:00:11")
    assert connection.execute("SELECT status FROM task_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "succeeded"
    assert connection.execute("SELECT COUNT(*) FROM task_job_leases WHERE job_id = ?", (job.id,)).fetchone()[0] == 0
    assert dispatcher.calls[0]["limit"] == 10
    assert dispatcher.calls[0]["org_id"] == org_id


def test_recovery_pause_blocks_both_job_claim_and_outbox_dispatch() -> None:
    connection = _fixture()
    org_id = str(uuid4())
    job = _enqueue(connection, org_id)
    connection.execute("CREATE TABLE audit_recovery_queue_pauses ("
        "org_id TEXT NOT NULL, queue_name TEXT NOT NULL, restore_id TEXT NOT NULL, "
        "paused INTEGER NOT NULL, version INTEGER NOT NULL, PRIMARY KEY (org_id, queue_name))")
    connection.execute("INSERT INTO audit_recovery_queue_pauses VALUES (?, 'default', ?, 1, 1)",
        (org_id, str(uuid4())))
    connection.commit()
    dispatcher = RecordingDispatcher(count=1)
    runtime, _ = _runtime(connection, org_id, {"render": lambda _job, _context: None}, dispatcher=dispatcher)
    tick = runtime.run_once()
    assert tick.status == "paused"
    assert (tick.claimed_jobs, tick.outbox_events) == (0, 0)
    assert dispatcher.calls == []
    assert connection.execute("SELECT status FROM task_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "queued"


def test_expected_handler_failures_use_the_single_transactional_failure_facade() -> None:
    from apps.worker.runtime import DeterministicTaskError, TransientTaskError

    connection = _fixture()
    org_id = str(uuid4())
    deterministic = _enqueue(connection, org_id, job_type="validate")
    transient = _enqueue(connection, org_id, job_type="fetch")

    def invalid(_job, _context) -> None:
        raise DeterministicTaskError("INVALID_INPUT", message_redacted="validated input was invalid")

    def unavailable(_job, _context) -> None:
        raise TransientTaskError("DEPENDENCY_UNAVAILABLE", message_redacted="dependency temporarily unavailable")

    runtime, _ = _runtime(connection, org_id, {"validate": invalid, "fetch": unavailable})
    tick = runtime.run_once()

    assert tick.failed_jobs == 2
    rows = connection.execute(
        "SELECT job_id, error_class, error_code FROM task_failures ORDER BY error_code"
    ).fetchall()
    assert rows == [
        (transient.id, "transient", "DEPENDENCY_UNAVAILABLE"),
        (deterministic.id, "deterministic", "INVALID_INPUT"),
    ]
    statuses = dict(connection.execute("SELECT id, status FROM task_jobs").fetchall())
    assert statuses[deterministic.id] == "failed"
    assert statuses[transient.id] == "retry_scheduled"
    assert connection.execute("SELECT COUNT(*) FROM task_job_leases").fetchone()[0] == 0


def test_unexpected_exception_is_unknown_and_does_not_persist_exception_text() -> None:
    connection = _fixture()
    org_id = str(uuid4())
    job = _enqueue(connection, org_id)

    def broken(_job, _context) -> None:
        raise RuntimeError("api_token=do-not-store")

    runtime, _ = _runtime(connection, org_id, {"render": broken})
    tick = runtime.run_once()

    assert tick.results[0].error_code == "WORKER_UNHANDLED_EXCEPTION"
    failure = connection.execute(
        "SELECT error_class, error_code, message_redacted FROM task_failures WHERE job_id = ?", (job.id,)
    ).fetchone()
    assert failure == ("unknown", "WORKER_UNHANDLED_EXCEPTION", "unhandled handler exception type: RuntimeError")
    assert "do-not-store" not in str(connection.execute("SELECT input_snapshot FROM human_tasks").fetchone()[0])
    assert connection.execute("SELECT COUNT(*) FROM human_tasks").fetchone()[0] == 1


def test_timeout_after_possible_side_effect_is_unknown_and_requires_review() -> None:
    connection = _fixture()
    org_id = str(uuid4())
    job = _enqueue(connection, org_id)
    clock = FakeClock()

    def slow(_job, _context) -> None:
        clock.advance(6)

    runtime, _ = _runtime(
        connection,
        org_id,
        {"render": slow},
        clock=clock,
        execution_timeout_seconds=5,
    )
    tick = runtime.run_once()

    assert tick.results[0].error_code == "WORKER_EXECUTION_TIMEOUT"
    assert connection.execute("SELECT status FROM task_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "failed"
    assert connection.execute("SELECT COUNT(*) FROM human_tasks").fetchone()[0] == 1


def test_shutdown_finishes_current_task_and_releases_reserved_unstarted_work() -> None:
    from apps.worker.runtime import ShutdownToken

    connection = _fixture()
    org_id = str(uuid4())
    first = _enqueue(connection, org_id)
    second = _enqueue(connection, org_id)
    shutdown = ShutdownToken()
    seen: list[str] = []

    def handler(job, _context) -> None:
        seen.append(job.id)
        shutdown.request()

    runtime, _ = _runtime(connection, org_id, {"render": handler}, shutdown=shutdown)
    tick = runtime.run_once()

    assert len(seen) == 1
    assert (tick.status, tick.completed_jobs, tick.released_jobs) == ("stopping", 1, 1)
    statuses = dict(connection.execute("SELECT id, status FROM task_jobs").fetchall())
    executed_id = seen[0]
    released_id = second.id if executed_id == first.id else first.id
    assert statuses[executed_id] == "succeeded"
    assert statuses[released_id] == "retry_scheduled"
    assert connection.execute(
        "SELECT error_code FROM task_failures WHERE job_id = ?", (released_id,)
    ).fetchone()[0] == "WORKER_SHUTDOWN"


def test_backpressure_and_missing_handler_are_deterministic() -> None:
    connection = _fixture()
    org_id = str(uuid4())
    job = _enqueue(connection, org_id, job_type="unregistered")
    blocked, _ = _runtime(connection, org_id, {}, capacity=lambda: 0)

    tick = blocked.run_once()
    assert tick.status == "backpressure"
    assert connection.execute("SELECT status FROM task_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "queued"

    active, _ = _runtime(connection, org_id, {})
    failed = active.run_once()
    assert failed.results[0].error_code == "TASK_HANDLER_NOT_REGISTERED"
    assert connection.execute("SELECT status FROM task_jobs WHERE id = ?", (job.id,)).fetchone()[0] == "failed"


def test_run_until_stopped_is_bounded_and_sleeps_between_idle_ticks() -> None:
    connection = _fixture()
    org_id = str(uuid4())
    sleeps: list[float] = []
    runtime, _ = _runtime(connection, org_id, {})
    runtime.sleeper = sleeps.append

    ticks = runtime.run_until_stopped(max_ticks=3)

    assert [tick.reason for tick in ticks] == ["idle", "idle", "idle"]
    assert sleeps == [5.0, 5.0]
