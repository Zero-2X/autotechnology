"""Tenant-scoped, account-free replay of one task job.

Replay creates a new queued ``task_jobs`` row and never mutates the source job
or its append-only failure facts.  Policy and kill-switch decisions are hooks so
the foundation layer does not import a domain policy engine or a provider SDK.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4

from .task_queue import TaskJob


class DBAPICursor(Protocol):
    description: object

    def fetchone(self) -> object: ...

    def fetchall(self) -> list[object]: ...


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class TaskReplayError(RuntimeError):
    """Stable error returned by replay validation and commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReplaySourceNotFoundError(TaskReplayError):
    def __init__(self, message: str = "replay source task was not found") -> None:
        super().__init__("REPLAY_SOURCE_NOT_FOUND", message)


class ReplayNotAllowedError(TaskReplayError):
    def __init__(self, message: str = "task state is not replayable") -> None:
        super().__init__("REPLAY_NOT_ALLOWED", message)


class ReplaySecretInputError(TaskReplayError):
    def __init__(self, message: str = "replay input contains a secret or external reference") -> None:
        super().__init__("REPLAY_SECRET_INPUT", message)


class ReplayVersionConflictError(TaskReplayError):
    def __init__(self, message: str = "replay source attempt or idempotency version conflicts") -> None:
        super().__init__("REPLAY_VERSION_CONFLICT", message)


class TenantScopeViolationError(TaskReplayError):
    def __init__(self, message: str = "task belongs to a different organization") -> None:
        super().__init__("TENANT_SCOPE_VIOLATION", message)


class InvalidReplayCommandError(TaskReplayError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_REPLAY_COMMAND", message)


def _required(value: object, name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise InvalidReplayCommandError(f"{name} must not be empty")
    return normalized


def _uuid(value: str, name: str) -> str:
    try:
        return str(UUID(_required(value, name)))
    except ValueError as exc:
        raise InvalidReplayCommandError(f"{name} must be a UUID") from exc


def _utc(value: datetime, name: str = "now") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidReplayCommandError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat(timespec="microseconds")


def _row_mapping(cursor: DBAPICursor, row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if not cursor.description:
        raise RuntimeError("task replay query did not return column metadata")
    names = [column[0] for column in cursor.description]  # type: ignore[index]
    return dict(zip(names, row))  # type: ignore[arg-type]


@dataclass(frozen=True)
class ReplayDecision:
    source_job_id: str
    source_attempt_count: int
    job: TaskJob
    idempotency_key: str
    trace_id: str
    source_failure_id: str | None = None
    duplicate: bool = False

    @property
    def job_id(self) -> str:
        return self.job.id

    def as_contract(self) -> dict[str, Any]:
        value = self.job.as_contract()
        value.update({
            "job_id": self.job.id,
            "source_job_id": self.source_job_id,
            "source_attempt_count": self.source_attempt_count,
            "source_failure_id": self.source_failure_id,
            "idempotency_key": self.idempotency_key,
            "trace_id": self.trace_id,
            "duplicate": self.duplicate,
            "job": self.job.as_contract(),
        })
        return value


_JOB_COLUMNS = tuple(TaskJob.__dataclass_fields__)
_JOB_COLUMN_SQL = ", ".join(_JOB_COLUMNS)
_SECRET_INPUT_RE = re.compile(
    r"(?i)(?:secret|token|password|credential|oauth|authorization|private[_-]?key|\.pem|BEGIN\s+(?:RSA|OPENSSH|EC|DSA)?\s*PRIVATE\s+KEY)"
)
_EXTERNAL_REF_RE = re.compile(r"(?i)(?:https?|s3|gs|arn|platform|provider|external)://")


PolicyChecker = Callable[[TaskJob], bool]


class TaskReplayStore:
    """Create immutable replay records in the existing task_jobs table."""

    def __init__(
        self,
        connection: DBAPIConnection,
        *,
        dialect: str = "sqlite",
        policy_checker: PolicyChecker | None = None,
        kill_switch_checker: PolicyChecker | None = None,
        policy_check: PolicyChecker | None = None,
        kill_switch_check: PolicyChecker | None = None,
    ) -> None:
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError("dialect must be sqlite or postgresql")
        if policy_checker is not None and policy_check is not None:
            raise ValueError("provide only one policy checker")
        if kill_switch_checker is not None and kill_switch_check is not None:
            raise ValueError("provide only one kill-switch checker")
        self.connection = connection
        self.dialect = dialect
        self.policy_checker = policy_checker or policy_check
        self.kill_switch_checker = kill_switch_checker or kill_switch_check

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor:
        if self.dialect == "postgresql":
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, parameters)

    def _begin(self) -> None:
        if self.dialect == "sqlite" and not getattr(self.connection, "in_transaction", False):
            self._execute("BEGIN IMMEDIATE")

    def _load_job(self, job_id: str) -> TaskJob | None:
        cursor = self._execute(
            f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs WHERE id = ?", (_uuid(job_id, "job_id"),)
        )
        row = cursor.fetchone()
        return TaskJob(**_row_mapping(cursor, row)) if row is not None else None

    def _existing_by_key(self, org_id: str, job_type: str, idempotency_key: str) -> TaskJob | None:
        cursor = self._execute(
            f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs "
            "WHERE org_id = ? AND job_type = ? AND idempotency_key = ?",
            (org_id, job_type, idempotency_key),
        )
        row = cursor.fetchone()
        return TaskJob(**_row_mapping(cursor, row)) if row is not None else None

    def _latest_unknown_failure(self, source: TaskJob, org_id: str) -> tuple[str, int] | None:
        """Return ``(failure_id, attempt_count)`` when source has an unknown result."""
        try:
            cursor = self._execute(
                "SELECT id, attempt_count FROM task_failures WHERE org_id = ? AND job_id = ? "
                "AND error_class = 'unknown' ORDER BY attempt_count DESC, occurred_at DESC, id DESC LIMIT 1",
                (org_id, source.id),
            )
            row = cursor.fetchone()
        except Exception as exc:
            if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
                return None
            raise
        if row is None:
            return None
        failure = _row_mapping(cursor, row)
        try:
            human_cursor = self._execute(
                "SELECT status FROM human_tasks WHERE org_id = ? AND task_type = 'unknown_result' "
                "AND aggregate_id = ? AND input_version = ? "
                "AND status IN ('submitted', 'completed') ORDER BY created_at DESC LIMIT 1",
                (org_id, source.aggregate_id, source.aggregate_version),
            )
            human_row = human_cursor.fetchone()
        except Exception as exc:
            if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
                human_row = None
            else:
                raise
        if human_row is None:
            return None
        return str(failure["id"]), int(failure["attempt_count"])

    @staticmethod
    def _check_payload_ref(payload_ref: str) -> None:
        if _SECRET_INPUT_RE.search(payload_ref) or _EXTERNAL_REF_RE.search(payload_ref):
            raise ReplaySecretInputError()

    @staticmethod
    def _run_checker(checker: PolicyChecker | None, source: TaskJob, name: str) -> None:
        if checker is None:
            return
        try:
            allowed = checker(source)
        except Exception as exc:
            raise ReplayNotAllowedError(f"{name} check failed") from exc
        if allowed is not True:
            raise ReplayNotAllowedError(f"{name} check rejected replay")

    def replay(
        self,
        *,
        source_job_id: str,
        org_id: str,
        source_attempt_count: int,
        reason: str,
        idempotency_key: str,
        trace_id: str,
        now: datetime | None = None,
    ) -> ReplayDecision:
        """Replay one failed/dead task without mutating the source record."""
        source_key = _uuid(source_job_id, "source_job_id")
        tenant = _uuid(org_id, "org_id")
        if (
            isinstance(source_attempt_count, bool)
            or not isinstance(source_attempt_count, int)
            or source_attempt_count < 0
        ):
            raise InvalidReplayCommandError("source_attempt_count must be zero or greater")
        reason_value = _required(reason, "reason")[:500]
        idem = _required(idempotency_key, "idempotency_key")
        trace = _required(trace_id, "trace_id")
        current = _utc(now or datetime.now(timezone.utc), "now")
        timestamp = _timestamp(current)
        try:
            self._begin()
            source = self._load_job(source_key)
            if source is None:
                raise ReplaySourceNotFoundError()
            if source.org_id != tenant:
                raise TenantScopeViolationError()
            existing = self._existing_by_key(tenant, source.job_type, idem)
            if existing is not None:
                if existing.replayed_from_job_id != source.id:
                    raise ReplayVersionConflictError("idempotency key belongs to another replay source")
                self.connection.commit()
                return ReplayDecision(
                    source.id, source_attempt_count, existing, idem, existing.trace_id,
                    source_failure_id=None, duplicate=True,
                )
            if source.attempt_count != source_attempt_count:
                raise ReplayVersionConflictError("source_attempt_count does not match source task")
            if source.status not in {"failed", "dead_letter"}:
                raise ReplayNotAllowedError()
            source_failure_id: str | None = None
            unknown = self._latest_unknown_failure(source, tenant)
            if unknown is not None:
                source_failure_id = unknown[0]
            elif self._has_unknown_failure(source, tenant):
                raise ReplayNotAllowedError("unknown result requires completed human review")
            self._check_payload_ref(source.payload_ref)
            self._run_checker(self.policy_checker, source, "policy")
            self._run_checker(self.kill_switch_checker, source, "kill-switch")
            new_id = str(uuid4())
            replay_reason = reason_value
            if source_failure_id:
                replay_reason = f"{replay_reason}; failure_id={source_failure_id}"
            self._execute(
                f"INSERT INTO task_jobs ({_JOB_COLUMN_SQL}) VALUES ({', '.join('?' for _ in _JOB_COLUMNS)})",
                (
                    new_id, tenant, source.job_type, source.queue_name, source.aggregate_type,
                    source.aggregate_id, source.aggregate_version, source.payload_ref, source.payload_hash,
                    "queued", 0, source.max_attempts, timestamp, None, None, None, source.id,
                    source_attempt_count, replay_reason, idem, trace, timestamp, timestamp,
                ),
            )
            replayed = self._load_job(new_id)
            if replayed is None:  # pragma: no cover - protected by the transaction
                raise RuntimeError("replayed task disappeared")
            self.connection.commit()
            return ReplayDecision(source.id, source_attempt_count, replayed, idem, trace, source_failure_id)
        except Exception:
            self.connection.rollback()
            raise

    def _has_unknown_failure(self, source: TaskJob, org_id: str) -> bool:
        try:
            cursor = self._execute(
                "SELECT 1 FROM task_failures WHERE org_id = ? AND job_id = ? AND error_class = 'unknown' LIMIT 1",
                (org_id, source.id),
            )
            return cursor.fetchone() is not None
        except Exception as exc:
            if "no such table" in str(exc).lower() or "does not exist" in str(exc).lower():
                return False
            raise

    replay_task = replay
    create_replay = replay


task_replay_store = TaskReplayStore
ReplayStore = TaskReplayStore


__all__ = [
    "InvalidReplayCommandError", "ReplayDecision", "ReplayNotAllowedError",
    "ReplaySecretInputError", "ReplaySourceNotFoundError", "ReplayStore",
    "ReplayVersionConflictError", "TaskReplayError", "TaskReplayStore",
    "TenantScopeViolationError", "task_replay_store",
]
