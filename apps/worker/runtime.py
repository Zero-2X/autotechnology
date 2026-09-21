"""Bounded worker composition loop over the accepted foundation stores.

The runtime owns orchestration only. Domain work stays in registered handlers;
claim, lease, completion, failure and outbox semantics stay in their stores.
Handlers are synchronous and must call ``context.checkpoint()`` while doing
long work so the lease can be heartbeated and shutdown/timeout observed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Event
from time import sleep as default_sleep
from typing import Callable, Mapping, Protocol

from infra.foundation.task_claim import JobNotClaimableError, TaskClaimStore, TaskLease
from infra.foundation.task_failure import RetryDecision
from infra.foundation.task_failure_facade import FailureCommand, TaskFailureFacade
from infra.foundation.task_queue import TaskJob


Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("worker clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class WorkerSettings:
    worker_id: str
    org_id: str
    batch_size: int = 10
    max_in_flight: int = 10
    poll_interval_seconds: float = 5.0
    heartbeat_interval_seconds: float = 10.0
    execution_timeout_seconds: float = 60.0
    outbox_batch_size: int = 10

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id must not be empty")
        if not self.org_id.strip():
            raise ValueError("org_id must not be empty")
        for name in ("batch_size", "max_in_flight", "outbox_batch_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("poll_interval_seconds", "heartbeat_interval_seconds", "execution_timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be positive")


class ShutdownToken:
    """Thread-safe cooperative shutdown signal."""

    def __init__(self) -> None:
        self._event = Event()

    def request(self) -> None:
        self._event.set()

    @property
    def requested(self) -> bool:
        return self._event.is_set()


class TaskExecutionError(RuntimeError):
    """Expected handler failure with an explicit retry classification."""

    error_class = "unknown"
    default_code = "WORKER_TASK_ERROR"

    def __init__(self, error_code: str | None = None, *, message_redacted: str | None = None) -> None:
        self.error_code = (error_code or self.default_code).strip()
        if not self.error_code:
            raise ValueError("error_code must not be empty")
        self.message_redacted = message_redacted
        super().__init__(self.error_code)


class DeterministicTaskError(TaskExecutionError):
    error_class = "deterministic"
    default_code = "WORKER_DETERMINISTIC_FAILURE"


class TransientTaskError(TaskExecutionError):
    error_class = "transient"
    default_code = "WORKER_TRANSIENT_FAILURE"


class UnknownTaskResult(TaskExecutionError):
    error_class = "unknown"
    default_code = "WORKER_UNKNOWN_RESULT"


class WorkerShutdownRequested(TransientTaskError):
    default_code = "WORKER_SHUTDOWN"


class WorkerExecutionTimeout(UnknownTaskResult):
    default_code = "WORKER_EXECUTION_TIMEOUT"


@dataclass
class WorkerExecutionContext:
    """Lease-aware cooperative controls exposed to one domain handler."""

    claim_store: TaskClaimStore
    lease: TaskLease
    settings: WorkerSettings
    shutdown: ShutdownToken
    clock: Clock
    started_at: datetime
    last_heartbeat_at: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.started_at = _utc(self.started_at)
        self.last_heartbeat_at = self.started_at

    @property
    def deadline(self) -> datetime:
        return self.started_at + timedelta(seconds=self.settings.execution_timeout_seconds)

    def heartbeat(self) -> TaskLease:
        now = _utc(self.clock())
        if now >= self.deadline:
            raise WorkerExecutionTimeout()
        self.lease = self.claim_store.heartbeat(
            job_id=self.lease.job_id,
            lease_token=self.lease.lease_token,
            worker_id=self.settings.worker_id,
            org_id=self.settings.org_id,
            now=now,
        )
        self.last_heartbeat_at = now
        return self.lease

    def checkpoint(self) -> None:
        """Observe timeout/shutdown and extend the lease when it is due."""
        now = _utc(self.clock())
        if now >= self.deadline:
            raise WorkerExecutionTimeout()
        if self.shutdown.requested:
            raise WorkerShutdownRequested()
        if (now - self.last_heartbeat_at).total_seconds() >= self.settings.heartbeat_interval_seconds:
            self.heartbeat()


TaskHandler = Callable[[TaskJob, WorkerExecutionContext], None]


class OutboxDispatcherLike(Protocol):
    def dispatch_once(
        self, *, worker_id: str, now: datetime | None = None, limit: int = 10, org_id: str | None = None
    ) -> tuple[object, ...]: ...


@dataclass(frozen=True)
class TaskRunResult:
    job_id: str
    job_type: str
    status: str
    error_code: str | None = None


@dataclass(frozen=True)
class WorkerTick:
    status: str
    claimed_jobs: int
    completed_jobs: int
    failed_jobs: int
    released_jobs: int
    outbox_events: int
    results: tuple[TaskRunResult, ...] = ()
    reason: str | None = None


class WorkerRuntime:
    """Compose task leasing, registered handlers, failure facts and outbox."""

    def __init__(
        self,
        *,
        settings: WorkerSettings,
        claim_store: TaskClaimStore,
        failure_facade: TaskFailureFacade,
        handlers: Mapping[str, TaskHandler],
        outbox_dispatcher: OutboxDispatcherLike | None = None,
        shutdown: ShutdownToken | None = None,
        clock: Clock | None = None,
        sleeper: Sleeper = default_sleep,
        capacity_provider: Callable[[], int] | None = None,
    ) -> None:
        self.settings = settings
        self.claim_store = claim_store
        self.failure_facade = failure_facade
        self.handlers = dict(handlers)
        self.outbox_dispatcher = outbox_dispatcher
        self.shutdown = shutdown or ShutdownToken()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleeper = sleeper
        self.capacity_provider = capacity_provider or (lambda: settings.max_in_flight)

    def _capacity(self) -> int:
        available = self.capacity_provider()
        if isinstance(available, bool) or not isinstance(available, int):
            raise ValueError("capacity_provider must return an integer")
        return max(0, min(available, self.settings.max_in_flight, self.settings.batch_size))

    def _fail(self, lease: TaskLease, error: TaskExecutionError, *, now: datetime) -> RetryDecision:
        return self.failure_facade.handle(
            FailureCommand(
                job_id=lease.job_id,
                org_id=self.settings.org_id,
                error_class=error.error_class,
                error_code=error.error_code,
                trace_id=lease.job.trace_id,
                lease_token=lease.lease_token,
                worker_id=self.settings.worker_id,
                attempt_count=lease.job.attempt_count,
                message_redacted=error.message_redacted,
                expected_version=lease.job.aggregate_version,
                occurred_at=now,
            )
        )

    def _execute(self, lease: TaskLease) -> TaskRunResult:
        job = lease.job
        now = _utc(self.clock())
        if self.shutdown.requested:
            failure = WorkerShutdownRequested(message_redacted="worker stopped before task start")
            decision = self._fail(lease, failure, now=now)
            return TaskRunResult(job.id, job.job_type, decision.status, failure.error_code)

        handler = self.handlers.get(job.job_type)
        if handler is None:
            failure = DeterministicTaskError(
                "TASK_HANDLER_NOT_REGISTERED", message_redacted="no registered handler for task type"
            )
            decision = self._fail(lease, failure, now=now)
            return TaskRunResult(job.id, job.job_type, decision.status, failure.error_code)

        self.claim_store.start(
            job_id=job.id,
            lease_token=lease.lease_token,
            worker_id=self.settings.worker_id,
            org_id=self.settings.org_id,
            now=now,
        )
        context = WorkerExecutionContext(
            claim_store=self.claim_store,
            lease=lease,
            settings=self.settings,
            shutdown=self.shutdown,
            clock=self.clock,
            started_at=now,
        )
        try:
            handler(job, context)
            finished_at = _utc(self.clock())
            if finished_at >= context.deadline:
                raise WorkerExecutionTimeout(message_redacted="task exceeded its execution deadline")
        except TaskExecutionError as exc:
            decision = self._fail(context.lease, exc, now=_utc(self.clock()))
            return TaskRunResult(job.id, job.job_type, decision.status, exc.error_code)
        except Exception as exc:
            # The exception type aids diagnosis without persisting exception text,
            # which can contain payloads, credentials or provider responses.
            failure = UnknownTaskResult(
                "WORKER_UNHANDLED_EXCEPTION",
                message_redacted=f"unhandled handler exception type: {type(exc).__name__}",
            )
            decision = self._fail(context.lease, failure, now=_utc(self.clock()))
            return TaskRunResult(job.id, job.job_type, decision.status, failure.error_code)

        self.claim_store.complete(
            job_id=job.id,
            lease_token=context.lease.lease_token,
            worker_id=self.settings.worker_id,
            expected_version=job.aggregate_version,
            org_id=self.settings.org_id,
            now=finished_at,
        )
        return TaskRunResult(job.id, job.job_type, "succeeded")

    def run_once(self) -> WorkerTick:
        if self.shutdown.requested:
            return WorkerTick("stopped", 0, 0, 0, 0, 0, reason="shutdown_requested")
        if self.claim_store.is_paused(self.settings.org_id):
            return WorkerTick("paused", 0, 0, 0, 0, 0, reason="recovery_queue_paused")
        capacity = self._capacity()
        if capacity == 0:
            return WorkerTick("backpressure", 0, 0, 0, 0, 0, reason="no_available_capacity")

        claimed: tuple[TaskLease, ...]
        try:
            claimed = self.claim_store.claim(
                org_id=self.settings.org_id,
                worker_id=self.settings.worker_id,
                now=_utc(self.clock()),
                limit=capacity,
            )
        except JobNotClaimableError:
            claimed = ()

        results = tuple(self._execute(lease) for lease in claimed)
        outbox_count = 0
        if self.outbox_dispatcher is not None and not self.shutdown.requested:
            outbox_count = len(
                self.outbox_dispatcher.dispatch_once(
                    worker_id=self.settings.worker_id,
                    org_id=self.settings.org_id,
                    now=_utc(self.clock()),
                    limit=self.settings.outbox_batch_size,
                )
            )
        completed = sum(item.status == "succeeded" for item in results)
        released = sum(item.error_code == "WORKER_SHUTDOWN" for item in results)
        failed = len(results) - completed
        status = "stopping" if self.shutdown.requested else "ok"
        reason = "idle" if not claimed and outbox_count == 0 else None
        return WorkerTick(status, len(claimed), completed, failed, released, outbox_count, results, reason)

    def run_until_stopped(self, *, max_ticks: int | None = None) -> tuple[WorkerTick, ...]:
        if max_ticks is not None and max_ticks < 1:
            raise ValueError("max_ticks must be positive")
        ticks: list[WorkerTick] = []
        while not self.shutdown.requested and (max_ticks is None or len(ticks) < max_ticks):
            tick = self.run_once()
            ticks.append(tick)
            if not self.shutdown.requested and (max_ticks is None or len(ticks) < max_ticks):
                self.sleeper(self.settings.poll_interval_seconds)
        return tuple(ticks)
