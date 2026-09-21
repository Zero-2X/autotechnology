"""PostgreSQL task-job polling configuration and an account-free DB-API seam.

The queue seam is intentionally limited to idempotent enqueue and read-only
polling. Claim, lease, retry, dead-letter and real PostgreSQL driver behavior
belong to later tasks. No Redis client or network connection is used here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4


DEFAULT_QUEUE_NAME = "default"
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_POLL_BATCH_SIZE = 10
QUEUE_BACKEND = "postgresql"
_QUEUE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class TaskQueueConfigurationError(ValueError):
    """Raised when task polling configuration is invalid."""


class TaskQueueValidationError(ValueError):
    """Raised when an enqueue or poll command is invalid."""


class TaskQueueConflictError(RuntimeError):
    """Raised when an idempotency key is reused with a different command."""


def _positive_int(raw: str | None, *, name: str, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise TaskQueueConfigurationError(f"{name} must be an integer") from exc
    if value <= 0:
        raise TaskQueueConfigurationError(f"{name} must be greater than zero")
    return value


def _queue_name(raw: str | None) -> str:
    value = (raw or DEFAULT_QUEUE_NAME).strip()
    if not _QUEUE_NAME_PATTERN.fullmatch(value):
        raise TaskQueueConfigurationError(
            "TASK_QUEUE_NAME must contain only letters, numbers, dot, underscore, or hyphen"
        )
    return value


@dataclass(frozen=True)
class PollingSettings:
    """Validated, non-secret configuration for PostgreSQL task polling."""

    queue_name: str = DEFAULT_QUEUE_NAME
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    batch_size: int = DEFAULT_POLL_BATCH_SIZE
    source: str = "environment"

    def __post_init__(self) -> None:
        _queue_name(self.queue_name)
        if self.poll_interval_seconds <= 0:
            raise TaskQueueConfigurationError(
                "poll_interval_seconds must be greater than zero"
            )
        if self.batch_size <= 0:
            raise TaskQueueConfigurationError("batch_size must be greater than zero")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "PollingSettings":
        values = os.environ if environ is None else environ
        return cls(
            queue_name=_queue_name(values.get("TASK_QUEUE_NAME")),
            poll_interval_seconds=_positive_int(
                values.get("TASK_QUEUE_POLL_INTERVAL_SECONDS"),
                name="TASK_QUEUE_POLL_INTERVAL_SECONDS",
                default=DEFAULT_POLL_INTERVAL_SECONDS,
            ),
            batch_size=_positive_int(
                values.get("TASK_QUEUE_POLL_BATCH_SIZE"),
                name="TASK_QUEUE_POLL_BATCH_SIZE",
                default=DEFAULT_POLL_BATCH_SIZE,
            ),
        )

    @property
    def config_hash(self) -> str:
        payload = json.dumps(self.as_contract(), sort_keys=True, separators=(",", ":"))
        return f"sha256:{sha256(payload.encode('utf-8')).hexdigest()}"

    def as_contract(self) -> dict[str, Any]:
        return {
            "backend": QUEUE_BACKEND,
            "queue_name": self.queue_name,
            "poll_interval_seconds": self.poll_interval_seconds,
            "batch_size": self.batch_size,
            "eligible_status": "queued",
            "ordering": ["available_at", "created_at", "id"],
            "redis_required": False,
            "credentials_in_repository": False,
            "source": self.source,
        }


def _required_text(value: object, *, name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise TaskQueueValidationError(f"{name} must not be empty")
    return normalized


def _uuid_text(value: str, *, name: str) -> str:
    normalized = _required_text(value, name=name)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise TaskQueueValidationError(f"{name} must be a UUID") from exc


def _utc_datetime(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TaskQueueValidationError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class TaskJob:
    id: str
    org_id: str
    job_type: str
    queue_name: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    payload_ref: str
    payload_hash: str
    status: str
    attempt_count: int
    max_attempts: int
    available_at: str
    lease_until: str | None
    locked_by: str | None
    last_error: str | None
    replayed_from_job_id: str | None
    replayed_from_attempt_count: int | None
    replay_reason: str | None
    idempotency_key: str
    trace_id: str
    created_at: str
    updated_at: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TaskJob":
        return cls(**{name: value[name] for name in cls.__dataclass_fields__})

    def as_contract(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


class DBAPICursor(Protocol):
    description: object

    def fetchone(self) -> object: ...

    def fetchall(self) -> list[object]: ...


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor: ...


_JOB_COLUMNS = tuple(TaskJob.__dataclass_fields__)
_JOB_COLUMN_SQL = ", ".join(_JOB_COLUMNS)


def _row_mapping(cursor: DBAPICursor, row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    description = cursor.description
    if not description:
        raise RuntimeError("task queue query did not return column metadata")
    names = [column[0] for column in description]  # type: ignore[index]
    return dict(zip(names, row))  # type: ignore[arg-type]


class TaskJobQueue:
    """Minimal DB-API queue seam for deterministic local/CI verification.

    ``enqueue()`` participates in the caller's transaction and deliberately
    does not commit.  This lets a future application service atomically persist
    business state, a task job, and an Outbox event on one connection.
    """

    def __init__(
        self,
        connection: DBAPIConnection,
        settings: PollingSettings | None = None,
    ) -> None:
        self.connection = connection
        self.settings = settings or PollingSettings()

    def enqueue(
        self,
        *,
        org_id: str,
        job_type: str,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_version: int,
        payload_ref: str,
        idempotency_key: str,
        trace_id: str,
        max_attempts: int = 3,
        available_at: datetime | None = None,
        now: datetime | None = None,
    ) -> TaskJob:
        """Insert or return one idempotent task without committing."""
        tenant = _uuid_text(org_id, name="org_id")
        aggregate = _uuid_text(aggregate_id, name="aggregate_id")
        job_kind = _required_text(job_type, name="job_type")
        aggregate_kind = _required_text(aggregate_type, name="aggregate_type")
        idem_key = _required_text(idempotency_key, name="idempotency_key")
        trace = _required_text(trace_id, name="trace_id")
        if aggregate_version <= 0:
            raise TaskQueueValidationError("aggregate_version must be greater than zero")
        if max_attempts <= 0:
            raise TaskQueueValidationError("max_attempts must be greater than zero")
        if not payload_ref.startswith("private://"):
            raise TaskQueueValidationError("payload_ref must be a private:// object reference")

        current = _utc_datetime(now or datetime.now(timezone.utc), name="now")
        ready_at = _utc_datetime(available_at or current, name="available_at")
        command = {
            "org_id": tenant,
            "job_type": job_kind,
            "queue_name": self.settings.queue_name,
            "aggregate_type": aggregate_kind,
            "aggregate_id": aggregate,
            "aggregate_version": aggregate_version,
            "payload_ref": payload_ref,
            "max_attempts": max_attempts,
            "available_at": _timestamp(ready_at) if available_at is not None else None,
        }
        payload_hash = sha256(
            json.dumps(command, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        existing = self._find_idempotent(tenant, job_kind, idem_key)
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise TaskQueueConflictError(
                    "idempotency key reused with a different task command"
                )
            return existing

        timestamp = _timestamp(current)
        job = TaskJob(
            id=str(uuid4()),
            org_id=tenant,
            job_type=job_kind,
            queue_name=self.settings.queue_name,
            aggregate_type=aggregate_kind,
            aggregate_id=aggregate,
            aggregate_version=aggregate_version,
            payload_ref=payload_ref,
            payload_hash=payload_hash,
            status="queued",
            attempt_count=0,
            max_attempts=max_attempts,
            available_at=_timestamp(ready_at),
            lease_until=None,
            locked_by=None,
            last_error=None,
            replayed_from_job_id=None,
            replayed_from_attempt_count=None,
            replay_reason=None,
            idempotency_key=idem_key,
            trace_id=trace,
            created_at=timestamp,
            updated_at=timestamp,
        )
        placeholders = ", ".join("?" for _ in _JOB_COLUMNS)
        self.connection.execute(
            f"INSERT INTO task_jobs ({_JOB_COLUMN_SQL}) VALUES ({placeholders})",
            tuple(getattr(job, name) for name in _JOB_COLUMNS),
        )
        return job

    def _find_idempotent(
        self,
        org_id: str,
        job_type: str,
        idempotency_key: str,
    ) -> TaskJob | None:
        cursor = self.connection.execute(
            f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs "
            "WHERE org_id = ? AND job_type = ? AND idempotency_key = ?",
            (org_id, job_type, idempotency_key),
        )
        row = cursor.fetchone()
        return TaskJob.from_mapping(_row_mapping(cursor, row)) if row is not None else None

    def poll_ready(
        self,
        *,
        org_id: str,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[TaskJob, ...]:
        """Read ready jobs without claiming or mutating them."""
        tenant = _uuid_text(org_id, name="org_id")
        current = _utc_datetime(now or datetime.now(timezone.utc), name="now")
        requested_limit = self.settings.batch_size if limit is None else limit
        if requested_limit <= 0:
            raise TaskQueueValidationError("limit must be greater than zero")
        cursor = self.connection.execute(
            f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs "
            "WHERE org_id = ? AND queue_name = ? AND status IN ('queued', 'retry_scheduled') "
            "AND available_at <= ? "
            "ORDER BY available_at ASC, created_at ASC, id ASC LIMIT ?",
            (
                tenant,
                self.settings.queue_name,
                _timestamp(current),
                requested_limit,
            ),
        )
        return tuple(
            TaskJob.from_mapping(_row_mapping(cursor, row))
            for row in cursor.fetchall()
        )

    def claim(self, **kwargs: Any):
        """Delegate claim lifecycle operations to the FOUND-004C store."""
        from .task_claim import TaskClaimStore

        return TaskClaimStore(self.connection, queue_name=self.settings.queue_name).claim(**kwargs)

    def heartbeat(self, **kwargs: Any):
        from .task_claim import TaskClaimStore

        return TaskClaimStore(self.connection, queue_name=self.settings.queue_name).heartbeat(**kwargs)

    def start(self, **kwargs: Any):
        from .task_claim import TaskClaimStore

        return TaskClaimStore(self.connection, queue_name=self.settings.queue_name).start(**kwargs)

    def complete(self, **kwargs: Any):
        from .task_claim import TaskClaimStore

        return TaskClaimStore(self.connection, queue_name=self.settings.queue_name).complete(**kwargs)

    def fail(self, **kwargs: Any):
        from .task_claim import TaskClaimStore

        return TaskClaimStore(self.connection, queue_name=self.settings.queue_name).fail(**kwargs)

    def record_failure(self, **kwargs: Any):
        from .task_failure import TaskFailureStore

        return TaskFailureStore(self.connection).record_failure(**kwargs)

    def retry(self, **kwargs: Any):
        from .task_failure import TaskFailureStore

        return TaskFailureStore(self.connection).retry(**kwargs)

    def requeue_dead(self, **kwargs: Any):
        from .task_failure import TaskFailureStore

        return TaskFailureStore(self.connection).requeue_dead(**kwargs)

    def replay(self, **kwargs: Any):
        from .task_replay import TaskReplayStore

        return TaskReplayStore(self.connection).replay(**kwargs)


task_job_queue = TaskJobQueue
