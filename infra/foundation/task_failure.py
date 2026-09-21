"""Append-only task failures, retry decisions, human review, and DLQ requeue.

The implementation is deliberately DB-API based so the same decision logic can
run against the repository's synthetic SQLite fixture and a PostgreSQL adapter.
No provider client or network side effect is part of failure handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import random
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from .task_queue import TaskJob


ERROR_CLASSES = frozenset({"deterministic", "transient", "unknown"})
HUMAN_TASK_TYPE = "unknown_result"


class DBAPICursor(Protocol):
    description: object

    def fetchone(self) -> object: ...

    def fetchall(self) -> list[object]: ...


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class TaskFailureError(RuntimeError):
    """Stable error returned by failure/retry commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InvalidTaskFailureError(TaskFailureError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_TASK_FAILURE", message)


class RetryNotAllowedError(TaskFailureError):
    def __init__(self, message: str = "the task failure is not retryable") -> None:
        super().__init__("RETRY_NOT_ALLOWED", message)


class MaxAttemptsExceededError(TaskFailureError):
    def __init__(self, message: str = "maximum task attempts have been exceeded") -> None:
        super().__init__("MAX_ATTEMPTS_EXCEEDED", message)


class UnknownResultRequiresReviewError(TaskFailureError):
    def __init__(self, message: str = "unknown result requires human review") -> None:
        super().__init__("UNKNOWN_RESULT_REQUIRES_REVIEW", message)


class TenantScopeViolationError(TaskFailureError):
    def __init__(self, message: str = "task belongs to a different organization") -> None:
        super().__init__("TENANT_SCOPE_VIOLATION", message)


class JobNotFoundError(TaskFailureError):
    def __init__(self, message: str = "task job was not found") -> None:
        super().__init__("JOB_NOT_FOUND", message)


class RequeueNotAllowedError(TaskFailureError):
    def __init__(self, message: str = "only dead-letter tasks can be requeued") -> None:
        super().__init__("REQUEUE_NOT_ALLOWED", message)


def _required(value: object, name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise InvalidTaskFailureError(f"{name} must not be empty")
    return normalized


def _uuid(value: str, name: str) -> str:
    try:
        return str(UUID(_required(value, name)))
    except ValueError as exc:
        raise InvalidTaskFailureError(f"{name} must be a UUID") from exc


def _utc(value: datetime, name: str = "now") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidTaskFailureError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat(timespec="microseconds")


def _row_mapping(cursor: DBAPICursor, row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if not cursor.description:
        raise RuntimeError("task failure query did not return column metadata")
    names = [column[0] for column in cursor.description]  # type: ignore[index]
    return dict(zip(names, row))  # type: ignore[arg-type]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff policy.

    ``jitter`` is a ratio in ``[0, 1]``.  A zero jitter (the default) keeps
    synthetic tests deterministic; callers may inject a random value when
    using jitter in production.
    """

    backoff_base_ms: int = 1_000
    backoff_cap_ms: int = 60_000
    jitter: float = 0.0
    jitter_ms: int = 0
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        if self.backoff_base_ms <= 0:
            raise InvalidTaskFailureError("backoff_base_ms must be greater than zero")
        if self.backoff_cap_ms <= 0:
            raise InvalidTaskFailureError("backoff_cap_ms must be greater than zero")
        if self.backoff_cap_ms < self.backoff_base_ms:
            raise InvalidTaskFailureError("backoff_cap_ms must be at least backoff_base_ms")
        if not 0 <= self.jitter <= 1:
            raise InvalidTaskFailureError("jitter must be between zero and one")
        if self.jitter_ms < 0:
            raise InvalidTaskFailureError("jitter_ms must be zero or greater")
        if self.max_attempts is not None and self.max_attempts < 1:
            raise InvalidTaskFailureError("max_attempts must be at least one")

    def delay_ms(self, attempt_count: int, *, random_value: float | None = None) -> int:
        if attempt_count < 1:
            raise InvalidTaskFailureError("attempt_count must be at least one")
        bounded = min(self.backoff_cap_ms, self.backoff_base_ms * (2 ** (attempt_count - 1)))
        if self.jitter == 0 and self.jitter_ms == 0:
            return int(bounded)
        sample = random.random() if random_value is None else random_value
        if not 0 <= sample <= 1:
            raise InvalidTaskFailureError("random_value must be between zero and one")
        jittered = bounded * (1 + ((sample * 2) - 1) * self.jitter)
        jittered += ((sample * 2) - 1) * self.jitter_ms
        return max(0, min(self.backoff_cap_ms, int(round(jittered))))

    compute_delay_ms = delay_ms
    backoff_delay_ms = delay_ms


@dataclass(frozen=True)
class TaskFailure:
    id: str
    org_id: str
    job_id: str
    attempt_count: int
    error_class: str
    error_code: str
    message_redacted: str | None
    retryable: bool
    trace_id: str
    occurred_at: str

    def as_contract(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class HumanTask:
    id: str
    org_id: str
    task_type: str
    aggregate_type: str
    aggregate_id: str
    input_version: int
    workflow_run_id: str | None
    approval_id: str | None
    status: str
    assigned_to: str | None
    claim_lease_until: str | None
    priority: str
    sla_policy_id: str | None
    due_at: str | None
    input_snapshot: dict[str, Any]
    result: dict[str, Any]
    completed_by: str | None
    override_expires_at: str | None
    created_at: str
    completed_at: str | None

    def as_contract(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True)
class RetryDecision:
    failure: TaskFailure
    job: TaskJob
    code: str | None
    status: str
    available_at: str
    human_task: HumanTask | None = None
    duplicate: bool = False

    @property
    def failure_id(self) -> str:
        return self.failure.id

    @property
    def error_class(self) -> str:
        return self.failure.error_class

    @property
    def error_code(self) -> str:
        return self.failure.error_code

    @property
    def retryable(self) -> bool:
        return self.failure.retryable

    def as_contract(self) -> dict[str, Any]:
        return {
            "failure": self.failure.as_contract(),
            "job": self.job.as_contract(),
            "code": self.code,
            "status": self.status,
            "available_at": self.available_at,
            "human_task": self.human_task.as_contract() if self.human_task else None,
            "duplicate": self.duplicate,
        }


_FAILURE_COLUMNS = (
    "id", "org_id", "job_id", "attempt_count", "error_class", "error_code",
    "message_redacted", "retryable", "trace_id", "occurred_at",
)
_FAILURE_COLUMN_SQL = ", ".join(_FAILURE_COLUMNS)
_HUMAN_COLUMNS = (
    "id", "org_id", "task_type", "aggregate_type", "aggregate_id", "input_version",
    "workflow_run_id", "approval_id", "status", "assigned_to", "claim_lease_until",
    "priority", "sla_policy_id", "due_at", "input_snapshot", "result", "completed_by",
    "override_expires_at", "created_at", "completed_at",
)
_HUMAN_COLUMN_SQL = ", ".join(_HUMAN_COLUMNS)
_JOB_COLUMNS = tuple(TaskJob.__dataclass_fields__)
_JOB_COLUMN_SQL = ", ".join(_JOB_COLUMNS)


class TaskFailureStore:
    """Tenant-scoped failure facts and retry state transitions."""

    def __init__(
        self,
        connection: DBAPIConnection,
        *,
        policy: RetryPolicy | None = None,
        dialect: str = "sqlite",
        random_value: float | None = None,
    ) -> None:
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError("dialect must be sqlite or postgresql")
        self.connection = connection
        self.policy = policy or RetryPolicy()
        self.dialect = dialect
        self.random_value = random_value

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor:
        if self.dialect == "postgresql":
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, parameters)

    def _begin(self) -> None:
        if self.dialect == "sqlite" and not getattr(self.connection, "in_transaction", False):
            self._execute("BEGIN IMMEDIATE")

    def _load_job(self, job_id: str, *, for_update: bool = False) -> TaskJob | None:
        suffix = " FOR UPDATE" if for_update and self.dialect == "postgresql" else ""
        cursor = self._execute(
            f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs WHERE id = ?{suffix}", (_uuid(job_id, "job_id"),)
        )
        row = cursor.fetchone()
        return TaskJob(**_row_mapping(cursor, row)) if row is not None else None

    def _load_failure(self, job_id: str, attempt_count: int, error_code: str) -> TaskFailure | None:
        cursor = self._execute(
            f"SELECT {_FAILURE_COLUMN_SQL} FROM task_failures "
            "WHERE job_id = ? AND attempt_count = ? AND error_code = ?",
            (_uuid(job_id, "job_id"), attempt_count, error_code),
        )
        row = cursor.fetchone()
        return self._failure_from_row(_row_mapping(cursor, row)) if row is not None else None

    @staticmethod
    def _failure_from_row(row: Mapping[str, Any]) -> TaskFailure:
        return TaskFailure(
            id=str(row["id"]), org_id=str(row["org_id"]), job_id=str(row["job_id"]),
            attempt_count=int(row["attempt_count"]), error_class=str(row["error_class"]),
            error_code=str(row["error_code"]), message_redacted=row["message_redacted"],
            retryable=bool(row["retryable"]), trace_id=str(row["trace_id"]),
            occurred_at=str(row["occurred_at"]),
        )

    def _failure_from_id(self, failure_id: str) -> TaskFailure | None:
        cursor = self._execute(
            f"SELECT {_FAILURE_COLUMN_SQL} FROM task_failures WHERE id = ?",
            (_uuid(failure_id, "failure_id"),),
        )
        row = cursor.fetchone()
        return self._failure_from_row(_row_mapping(cursor, row)) if row is not None else None

    def _load_human_task(self, task_id: str, org_id: str) -> HumanTask | None:
        cursor = self._execute(
            f"SELECT {_HUMAN_COLUMN_SQL} FROM human_tasks WHERE id = ? AND org_id = ?",
            (_uuid(task_id, "human_task_id"), _uuid(org_id, "org_id")),
        )
        row = cursor.fetchone()
        return self._human_from_row(_row_mapping(cursor, row)) if row is not None else None

    @staticmethod
    def _human_from_row(row: Mapping[str, Any]) -> HumanTask:
        snapshot = row["input_snapshot"]
        result = row["result"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        if isinstance(result, str):
            result = json.loads(result)
        return HumanTask(
            id=str(row["id"]), org_id=str(row["org_id"]), task_type=str(row["task_type"]),
            aggregate_type=str(row["aggregate_type"]), aggregate_id=str(row["aggregate_id"]),
            input_version=int(row["input_version"]), workflow_run_id=row["workflow_run_id"],
            approval_id=row["approval_id"], status=str(row["status"]), assigned_to=row["assigned_to"],
            claim_lease_until=row["claim_lease_until"], priority=str(row["priority"]),
            sla_policy_id=row["sla_policy_id"], due_at=row["due_at"], input_snapshot=dict(snapshot),
            result=dict(result), completed_by=row["completed_by"],
            override_expires_at=row["override_expires_at"], created_at=str(row["created_at"]),
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _job_from_row(cursor: DBAPICursor, row: object) -> TaskJob:
        return TaskJob(**_row_mapping(cursor, row))

    def _ensure_tenant(self, job: TaskJob, org_id: str) -> str:
        tenant = _uuid(org_id, "org_id")
        if job.org_id != tenant:
            raise TenantScopeViolationError()
        return tenant

    def _clear_lease(self, job_id: str) -> None:
        self._execute(
            "UPDATE task_jobs SET lease_until = NULL, locked_by = NULL WHERE id = ?",
            (_uuid(job_id, "job_id"),),
        )
        # The lease table is owned by FOUND-004C and may not exist in a unit
        # test that exercises only the failure tables.
        try:
            self._execute("DELETE FROM task_job_leases WHERE job_id = ?", (_uuid(job_id, "job_id"),))
        except Exception as exc:
            if "no such table" not in str(exc).lower() and "does not exist" not in str(exc).lower():
                raise

    def _insert_human_task(self, job: TaskJob, failure: TaskFailure, now: str) -> HumanTask:
        snapshot = {
            "job_id": job.id,
            "failure_id": failure.id,
            "attempt_count": failure.attempt_count,
            "error_code": failure.error_code,
            "message_redacted": failure.message_redacted,
            "trace_id": failure.trace_id,
        }
        existing_cursor = self._execute(
            f"SELECT {_HUMAN_COLUMN_SQL} FROM human_tasks WHERE org_id = ? AND task_type = ? "
            "AND aggregate_id = ? AND input_version = ?",
            (job.org_id, HUMAN_TASK_TYPE, job.aggregate_id, job.aggregate_version),
        )
        existing_row = existing_cursor.fetchone()
        if existing_row is not None:
            return self._human_from_row(_row_mapping(existing_cursor, existing_row))
        human_id = str(uuid4())
        self._execute(
            f"INSERT INTO human_tasks ({_HUMAN_COLUMN_SQL}) VALUES ({', '.join('?' for _ in _HUMAN_COLUMNS)})",
            (
                human_id, job.org_id, HUMAN_TASK_TYPE, job.aggregate_type, job.aggregate_id,
                job.aggregate_version, None, None, "queued", None, None, "high", None, None,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "{}", None, None, now, None,
            ),
        )
        return self._load_human_task(human_id, job.org_id)  # type: ignore[return-value]

    def _decision(
        self,
        failure: TaskFailure,
        job_id: str,
        *,
        code: str | None,
        status: str,
        available_at: str,
        human_task: HumanTask | None = None,
        duplicate: bool = False,
    ) -> RetryDecision:
        job = self._load_job(job_id)
        if job is None:  # pragma: no cover - protected by the transaction
            raise JobNotFoundError()
        return RetryDecision(failure, job, code, status, available_at, human_task, duplicate)

    def record_failure(
        self,
        *,
        job_id: str,
        org_id: str,
        error_class: str,
        error_code: str,
        trace_id: str,
        attempt_count: int | None = None,
        message_redacted: str | None = None,
        retryable: bool | None = None,
        occurred_at: datetime | None = None,
        expected_version: int | None = None,
        lease_token: str | None = None,
        worker_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> RetryDecision:
        """Append one failure fact and apply exactly one retry state transition."""
        tenant = _uuid(org_id, "org_id")
        job_key = _uuid(job_id, "job_id")
        if error_class not in ERROR_CLASSES:
            raise InvalidTaskFailureError("error_class must be deterministic, transient, or unknown")
        code_value = _required(error_code, "error_code")
        trace = _required(trace_id, "trace_id")
        if idempotency_key is not None:
            _required(idempotency_key, "idempotency_key")
        if attempt_count is not None and (
            isinstance(attempt_count, bool) or not isinstance(attempt_count, int) or attempt_count < 0
        ):
            raise InvalidTaskFailureError("attempt_count must be zero or greater")
        if expected_version is not None and (
            isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1
        ):
            raise InvalidTaskFailureError("expected_version must be at least one")
        now_dt = _utc(occurred_at or datetime.now(timezone.utc), "occurred_at")
        now = _timestamp(now_dt)
        redacted = None if message_redacted is None else " ".join(str(message_redacted).split())[:512]
        retry_flag = error_class == "transient"
        if retryable is not None and bool(retryable) != retry_flag:
            raise InvalidTaskFailureError(
                f"retryable must be {str(retry_flag).lower()} for {error_class} failures"
            )
        try:
            self._begin()
            job = self._load_job(job_key, for_update=True)
            if job is None:
                raise JobNotFoundError()
            self._ensure_tenant(job, tenant)
            if lease_token is not None or job.status in {"leased", "running"}:
                from .task_claim import TaskClaimStore, TaskClaimError

                try:
                    TaskClaimStore(self.connection, dialect=self.dialect)._validate_lease(
                        job.id, lease_token, org_id=tenant, worker_id=worker_id, now=now_dt,
                    )
                except (TaskClaimError, ValueError) as exc:
                    raise InvalidTaskFailureError("failure lease is missing, expired or not owned by worker") from exc
                if attempt_count is not None and attempt_count != job.attempt_count:
                    raise InvalidTaskFailureError("leased failure must match current attempt")
            if expected_version is not None and job.aggregate_version != expected_version:
                raise InvalidTaskFailureError("expected_version does not match aggregate version")
            if attempt_count is not None and attempt_count not in {
                job.attempt_count,
                job.attempt_count + 1,
            }:
                raise InvalidTaskFailureError(
                    "attempt_count must match the current task attempt or the next attempt"
                )
            if job.status in {"succeeded", "cancelled"}:
                raise RetryNotAllowedError("terminal task cannot receive another failure")
            if job.status == "dead_letter":
                raise MaxAttemptsExceededError()
            attempt = job.attempt_count if attempt_count is None else attempt_count
            duplicate = self._load_failure(job.id, attempt, code_value)
            if duplicate is not None:
                duplicate_human = (
                    self._insert_human_task(job, duplicate, now)
                    if duplicate.error_class == "unknown" else None
                )
                duplicate_code = (
                    "UNKNOWN_RESULT_REQUIRES_REVIEW" if duplicate.error_class == "unknown"
                    else "RETRY_NOT_ALLOWED" if duplicate.error_class == "deterministic"
                    else "MAX_ATTEMPTS_EXCEEDED" if job.status == "dead_letter"
                    else "RETRY_SCHEDULED" if job.status == "retry_scheduled" else None
                )
                self.connection.commit()
                return self._decision(
                    duplicate, job.id, code=duplicate_code, status=job.status,
                    available_at=job.available_at, human_task=duplicate_human, duplicate=True,
                )
            failure = TaskFailure(
                id=str(uuid4()), org_id=tenant, job_id=job.id, attempt_count=attempt,
                error_class=error_class, error_code=code_value, message_redacted=redacted,
                retryable=retry_flag, trace_id=trace, occurred_at=now,
            )
            self._execute(
                f"INSERT INTO task_failures ({_FAILURE_COLUMN_SQL}) VALUES ({', '.join('?' for _ in _FAILURE_COLUMNS)})",
                tuple(failure.as_contract().values()),
            )
            status = "failed"
            decision_code: str | None = None
            available_dt = now_dt
            human_task: HumanTask | None = None
            if error_class == "deterministic":
                decision_code = "RETRY_NOT_ALLOWED"
                status = "failed"
            elif error_class == "unknown":
                decision_code = "UNKNOWN_RESULT_REQUIRES_REVIEW"
                status = "failed"
                human_task = self._insert_human_task(job, failure, now)
            elif attempt >= job.max_attempts:
                decision_code = "MAX_ATTEMPTS_EXCEEDED"
                status = "dead_letter"
            else:
                delay = self.policy.delay_ms(max(1, attempt), random_value=self.random_value)
                available_dt = now_dt + timedelta(milliseconds=delay)
                status = "retry_scheduled"
                decision_code = "RETRY_SCHEDULED"
            self._execute(
                "UPDATE task_jobs SET status = ?, last_error = ?, available_at = ?, "
                "attempt_count = CASE WHEN attempt_count < ? THEN ? ELSE attempt_count END, "
                "lease_until = NULL, locked_by = NULL, updated_at = ? WHERE id = ? AND org_id = ?",
                (status, redacted or code_value, _timestamp(available_dt), attempt, attempt, now, job.id, tenant),
            )
            self._clear_lease(job.id)
            self.connection.commit()
            return self._decision(
                failure, job.id, code=decision_code, status=status,
                available_at=_timestamp(available_dt), human_task=human_task,
            )
        except Exception:
            self.connection.rollback()
            raise

    # Explicit aliases make the command seam easy to discover and keep the
    # public API compatible with workers that call ``fail`` or ``handle_failure``.
    fail = record_failure
    handle_failure = record_failure
    record = record_failure
    process_failure = record_failure

    def get_failure(self, failure_id: str, *, org_id: str) -> TaskFailure:
        failure = self._failure_from_id(failure_id)
        if failure is None:
            raise JobNotFoundError("task failure was not found")
        if failure.org_id != _uuid(org_id, "org_id"):
            raise TenantScopeViolationError()
        return failure

    def list_failures(self, *, job_id: str, org_id: str) -> tuple[TaskFailure, ...]:
        tenant = _uuid(org_id, "org_id")
        job_key = _uuid(job_id, "job_id")
        job = self._load_job(job_key)
        if job is None:
            raise JobNotFoundError()
        self._ensure_tenant(job, tenant)
        cursor = self._execute(
            f"SELECT {_FAILURE_COLUMN_SQL} FROM task_failures WHERE org_id = ? AND job_id = ? "
            "ORDER BY attempt_count ASC, occurred_at ASC, id ASC", (tenant, job_key),
        )
        return tuple(self._failure_from_row(_row_mapping(cursor, row)) for row in cursor.fetchall())

    def _latest_failure(self, *, job_id: str, org_id: str) -> TaskFailure | None:
        failures = self.list_failures(job_id=job_id, org_id=org_id)
        return failures[-1] if failures else None

    def retry(
        self,
        *,
        job_id: str,
        org_id: str,
        trace_id: str,
        error_code: str = "MANUAL_RETRY",
        message_redacted: str | None = "manual retry requested",
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> RetryDecision:
        """Schedule a failed job when its latest failure permits retry."""
        tenant = _uuid(org_id, "org_id")
        job_key = _uuid(job_id, "job_id")
        _required(trace_id, "trace_id")
        current = _utc(now or datetime.now(timezone.utc), "now")
        job = self._load_job(job_key)
        if job is None:
            raise JobNotFoundError()
        self._ensure_tenant(job, tenant)
        if job.status == "dead_letter" or job.attempt_count >= job.max_attempts:
            raise MaxAttemptsExceededError()
        if job.status in {"succeeded", "cancelled"}:
            raise RetryNotAllowedError("task is not in a retryable state")
        latest = self._latest_failure(job_id=job.id, org_id=tenant)
        if latest is not None and latest.error_class == "unknown":
            raise UnknownResultRequiresReviewError()
        if latest is not None and (latest.error_class == "deterministic" or not latest.retryable):
            raise RetryNotAllowedError()
        if job.status == "retry_scheduled" and latest is not None:
            return RetryDecision(
                latest, job, "RETRY_SCHEDULED", job.status, job.available_at, duplicate=True
            )
        return self.record_failure(
            job_id=job_key, org_id=tenant, error_class="transient", error_code=error_code,
            trace_id=trace_id, attempt_count=job.attempt_count,
            message_redacted=message_redacted, retryable=True, occurred_at=current,
        )

    def requeue_dead(
        self,
        *,
        job_id: str,
        org_id: str,
        reason: str,
        idempotency_key: str | None = None,
        trace_id: str | None = None,
        failure_id: str | None = None,
        now: datetime | None = None,
    ) -> TaskJob:
        """Create a fresh queued job while retaining the dead-letter facts."""
        tenant = _uuid(org_id, "org_id")
        job_key = _uuid(job_id, "job_id")
        reason_value = _required(reason, "reason")[:500]
        current = _utc(now or datetime.now(timezone.utc), "now")
        try:
            self._begin()
            old = self._load_job(job_key)
            if old is None:
                raise JobNotFoundError()
            self._ensure_tenant(old, tenant)
            if failure_id is not None:
                latest = self._failure_from_id(failure_id)
                if latest is None or latest.org_id != tenant or latest.job_id != old.id:
                    raise TenantScopeViolationError("failure does not belong to the requested task")
            else:
                latest_cursor = self._execute(
                    f"SELECT {_FAILURE_COLUMN_SQL} FROM task_failures WHERE org_id = ? AND job_id = ? "
                    "ORDER BY attempt_count DESC, occurred_at DESC, id DESC LIMIT 1",
                    (tenant, old.id),
                )
                latest_row = latest_cursor.fetchone()
                latest = self._failure_from_row(_row_mapping(latest_cursor, latest_row)) if latest_row is not None else None
            failure_id = latest.id if latest else "none"
            key = _required(idempotency_key, "idempotency_key") if idempotency_key else f"dead-requeue:{old.id}:{failure_id}"
            existing_cursor = self._execute(
                f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs WHERE org_id = ? AND job_type = ? AND idempotency_key = ?",
                (tenant, old.job_type, key),
            )
            existing_row = existing_cursor.fetchone()
            if existing_row is not None:
                existing = self._job_from_row(existing_cursor, existing_row)
                self.connection.commit()
                return existing
            if old.status != "dead_letter":
                raise RequeueNotAllowedError()
            new_id = str(uuid4())
            new_trace = _required(trace_id, "trace_id") if trace_id else old.trace_id
            replay_reason = f"{reason_value}; failure_id={failure_id}"
            timestamp = _timestamp(current)
            self._execute(
                f"INSERT INTO task_jobs ({_JOB_COLUMN_SQL}) VALUES ({', '.join('?' for _ in _JOB_COLUMNS)})",
                (
                    new_id, tenant, old.job_type, old.queue_name, old.aggregate_type, old.aggregate_id,
                    old.aggregate_version, old.payload_ref, old.payload_hash, "queued", 0, old.max_attempts,
                    timestamp, None, None, None, old.id, latest.attempt_count if latest else old.attempt_count, replay_reason, key,
                    new_trace, timestamp, timestamp,
                ),
            )
            new_job = self._load_job(new_id)
            if new_job is None:  # pragma: no cover - protected by the transaction
                raise RuntimeError("requeued task disappeared")
            self.connection.commit()
            return new_job
        except Exception:
            self.connection.rollback()
            raise


task_failure_store = TaskFailureStore
FailureStore = TaskFailureStore
TaskFailureManager = TaskFailureStore


__all__ = [
    "ERROR_CLASSES", "HumanTask", "InvalidTaskFailureError", "JobNotFoundError",
    "MaxAttemptsExceededError", "RequeueNotAllowedError", "RetryDecision", "RetryNotAllowedError",
    "RetryPolicy", "TaskFailure", "TaskFailureError", "TaskFailureStore", "FailureStore", "TaskFailureManager",
    "TenantScopeViolationError", "UnknownResultRequiresReviewError",
]
