"""Tenant-scoped task claiming, leases, and completion controls.

This module extends the accepted ``task_jobs`` SQL baseline without changing
its schema.  Lease tokens are stored in ``task_job_leases`` (FOUND-004C) and
all state/token transitions use one short database transaction.  The DB-API
seam is intentionally usable with the synthetic SQLite fixture and keeps a
PostgreSQL ``FOR UPDATE SKIP LOCKED`` query for production adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from .task_queue import TaskJob


_JOB_COLUMNS = tuple(TaskJob.__dataclass_fields__)
_JOB_COLUMN_SQL = ", ".join(_JOB_COLUMNS)
_QUEUE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class TaskClaimError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class JobNotClaimableError(TaskClaimError):
    def __init__(self, message: str = "job is not currently claimable") -> None:
        super().__init__("JOB_NOT_CLAIMABLE", message)


class LeaseTokenInvalidError(TaskClaimError):
    def __init__(self, message: str = "lease token is invalid or expired") -> None:
        super().__init__("LEASE_TOKEN_INVALID", message)


class JobVersionConflictError(TaskClaimError):
    def __init__(self, message: str = "job version does not match expected version") -> None:
        super().__init__("JOB_VERSION_CONFLICT", message)


class JobLeaseExpiredError(TaskClaimError):
    def __init__(self, message: str = "job lease has expired") -> None:
        super().__init__("JOB_LEASE_EXPIRED", message)


class TenantScopeViolationError(TaskClaimError):
    def __init__(self, message: str = "job belongs to a different organization") -> None:
        super().__init__("TENANT_SCOPE_VIOLATION", message)


class DBAPICursor(Protocol):
    description: object

    def fetchone(self) -> object: ...

    def fetchall(self) -> list[object]: ...


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def _required(value: object, name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _uuid(value: str, name: str) -> str:
    try:
        return str(UUID(_required(value, name)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a UUID") from exc


def _utc(value: datetime, name: str = "now") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat(timespec="microseconds")


def _row_mapping(cursor: DBAPICursor, row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if not cursor.description:
        raise RuntimeError("task claim query did not return column metadata")
    names = [column[0] for column in cursor.description]  # type: ignore[index]
    return dict(zip(names, row))  # type: ignore[arg-type]


@dataclass(frozen=True)
class TaskLease:
    job: TaskJob
    worker_id: str
    lease_token: str
    lease_until: str
    claim_version: int

    @property
    def job_id(self) -> str:
        return self.job.id

    def as_contract(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "org_id": self.job.org_id,
            "worker_id": self.worker_id,
            "lease_token": self.lease_token,
            "lease_until": self.lease_until,
            "claim_version": self.claim_version,
            "job_status": self.job.status,
            "attempt_count": self.job.attempt_count,
        }


class TaskClaimStore:
    """Atomic claim/heartbeat/complete/fail operations for one DB connection."""

    POSTGRES_CLAIM_SQL = (
        "SELECT " + _JOB_COLUMN_SQL + " FROM task_jobs "
        "WHERE ((status IN ('queued', 'retry_scheduled') AND available_at <= %s) "
        "OR (status IN ('leased', 'running') AND lease_until IS NOT NULL AND lease_until <= %s)) "
        "AND org_id = %s AND queue_name = %s ORDER BY available_at, created_at, id LIMIT %s "
        "FOR UPDATE SKIP LOCKED"
    )

    def __init__(
        self,
        connection: DBAPIConnection,
        *,
        queue_name: str = "default",
        lease_seconds: int = 30,
        dialect: str = "sqlite",
    ) -> None:
        if not _QUEUE_NAME_RE.fullmatch(queue_name):
            raise ValueError("queue_name is invalid")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError("dialect must be sqlite or postgresql")
        self.connection = connection
        self.queue_name = queue_name
        self.lease_seconds = lease_seconds
        self.dialect = dialect

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor:
        if self.dialect == "postgresql":
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, parameters)

    def _begin(self) -> None:
        if self.dialect == "sqlite" and not getattr(self.connection, "in_transaction", False):
            self._execute("BEGIN IMMEDIATE")

    def is_paused(self, org_id: str) -> bool:
        """A restored tenant queue stays closed until recovery validation releases it."""
        tenant = _uuid(org_id, "org_id")
        if self.dialect == "sqlite":
            exists = self._execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_recovery_queue_pauses'"
            ).fetchone()
            if exists is None:
                return False
        row = self._execute(
            "SELECT paused FROM audit_recovery_queue_pauses WHERE org_id = ? AND queue_name = ?",
            (tenant, self.queue_name),
        ).fetchone()
        return bool(row[0]) if row else False

    def _load_job(
        self,
        job_id: str,
        *,
        org_id: str | None = None,
        for_update: bool = False,
    ) -> TaskJob | None:
        params: tuple[object, ...] = (_uuid(job_id, "job_id"),)
        clause = "id = ?"
        if org_id is not None:
            clause += " AND org_id = ?"
            params += (_uuid(org_id, "org_id"),)
        suffix = " FOR UPDATE" if for_update and self.dialect == "postgresql" else ""
        cursor = self._execute(f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs WHERE {clause}{suffix}", params)
        row = cursor.fetchone()
        return TaskJob(**_row_mapping(cursor, row)) if row is not None else None

    def _load_lease(self, job_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update and self.dialect == "postgresql" else ""
        cursor = self._execute(
            "SELECT job_id, org_id, worker_id, lease_token, lease_until, claimed_at, heartbeat_at, claim_version "
            f"FROM task_job_leases WHERE job_id = ?{suffix}",
            (_uuid(job_id, "job_id"),),
        )
        row = cursor.fetchone()
        return _row_mapping(cursor, row) if row is not None else None

    def _expire_exhausted(self, *, org_id: str, now: str) -> None:
        """Retire expired leases that have already consumed max_attempts."""
        cursor = self._execute(
            "SELECT id FROM task_jobs WHERE org_id = ? AND queue_name = ? "
            "AND status IN ('leased', 'running') AND lease_until IS NOT NULL "
            "AND lease_until <= ? AND attempt_count >= max_attempts",
            (org_id, self.queue_name, now),
        )
        job_ids = [str(row[0]) for row in cursor.fetchall()]
        if not job_ids:
            return
        placeholders = ", ".join("?" for _ in job_ids)
        self._execute(
            "UPDATE task_jobs SET status = 'dead_letter', last_error = ?, "
            "lease_until = NULL, locked_by = NULL, updated_at = ? "
            f"WHERE org_id = ? AND id IN ({placeholders})",
            ("MAX_ATTEMPTS_EXCEEDED", now, org_id, *job_ids),
        )
        self._execute(
            f"DELETE FROM task_job_leases WHERE org_id = ? AND job_id IN ({placeholders})",
            (org_id, *job_ids),
        )

    def claim(
        self,
        *,
        org_id: str,
        worker_id: str,
        now: datetime | None = None,
        limit: int = 1,
    ) -> tuple[TaskLease, ...]:
        tenant = _uuid(org_id, "org_id")
        worker = _required(worker_id, "worker_id")
        if limit < 1:
            raise ValueError("limit must be positive")
        current_dt = _utc(now or datetime.now(timezone.utc))
        current = _timestamp(current_dt)
        lease_until = _timestamp(current_dt + timedelta(seconds=self.lease_seconds))
        try:
            self._begin()
            if self.is_paused(tenant):
                self.connection.commit()
                return ()
            self._expire_exhausted(org_id=tenant, now=current)
            if self.dialect == "postgresql":
                cursor = self.connection.execute(
                    self.POSTGRES_CLAIM_SQL,
                    (current, current, tenant, self.queue_name, limit),
                )
            else:
                cursor = self._execute(
                    f"SELECT {_JOB_COLUMN_SQL} FROM task_jobs "
                    "WHERE ((status IN ('queued', 'retry_scheduled') AND available_at <= ?) "
                    "OR (status IN ('leased', 'running') AND lease_until IS NOT NULL AND lease_until <= ?)) "
                    "AND org_id = ? AND queue_name = ? "
                    "ORDER BY available_at ASC, created_at ASC, id ASC LIMIT ?",
                    (current, current, tenant, self.queue_name, limit),
                )
            rows = [_row_mapping(cursor, row) for row in cursor.fetchall()]
            if not rows:
                self.connection.commit()
                raise JobNotClaimableError()
            leases: list[TaskLease] = []
            for row in rows:
                job_id = str(row["id"])
                existing = self._load_lease(job_id)
                claim_version = int(existing["claim_version"]) + 1 if existing else 1
                token = uuid4().hex
                self._execute(
                    "UPDATE task_jobs SET status = 'leased', attempt_count = attempt_count + 1, "
                    "lease_until = ?, locked_by = ?, updated_at = ? WHERE id = ? AND org_id = ?",
                    (lease_until, worker, current, job_id, tenant),
                )
                self._execute(
                    "INSERT INTO task_job_leases "
                    "(job_id, org_id, worker_id, lease_token, lease_until, claimed_at, heartbeat_at, claim_version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(job_id) DO UPDATE SET org_id = excluded.org_id, worker_id = excluded.worker_id, "
                    "lease_token = excluded.lease_token, lease_until = excluded.lease_until, "
                    "claimed_at = excluded.claimed_at, heartbeat_at = excluded.heartbeat_at, "
                    "claim_version = excluded.claim_version",
                    (job_id, tenant, worker, token, lease_until, current, current, claim_version),
                )
                updated = self._load_job(job_id, org_id=tenant)
                if updated is None:  # pragma: no cover - protected by the transaction
                    raise RuntimeError("claimed task disappeared")
                leases.append(TaskLease(updated, worker, token, lease_until, claim_version))
            self.connection.commit()
            return tuple(leases)
        except Exception:
            self.connection.rollback()
            raise

    def _validate_lease(
        self,
        job_id: str,
        lease_token: str,
        *,
        org_id: str | None,
        worker_id: str | None = None,
        now: datetime,
    ) -> tuple[TaskJob, dict[str, Any]]:
        job = self._load_job(job_id, for_update=True)
        if job is None:
            raise JobNotClaimableError("job was not found")
        if org_id is not None and job.org_id != _uuid(org_id, "org_id"):
            raise TenantScopeViolationError()
        lease = self._load_lease(job.id, for_update=True)
        if lease is None or lease["lease_token"] != _required(lease_token, "lease_token"):
            raise LeaseTokenInvalidError()
        if worker_id is not None and lease["worker_id"] != _required(worker_id, "worker_id"):
            raise LeaseTokenInvalidError("lease token is owned by another worker")
        if str(lease["lease_until"]) <= _timestamp(now):
            raise JobLeaseExpiredError()
        if job.status not in {"leased", "running"}:
            raise JobNotClaimableError("job is no longer leased")
        return job, lease

    def heartbeat(
        self,
        *,
        job_id: str,
        lease_token: str,
        worker_id: str | None = None,
        now: datetime | None = None,
        org_id: str | None = None,
    ) -> TaskLease:
        current_dt = _utc(now or datetime.now(timezone.utc))
        current = _timestamp(current_dt)
        lease_until = _timestamp(current_dt + timedelta(seconds=self.lease_seconds))
        try:
            self._begin()
            job, lease = self._validate_lease(job_id, lease_token, org_id=org_id, worker_id=worker_id, now=current_dt)
            lease_update = self._execute(
                "UPDATE task_job_leases SET lease_until = ?, heartbeat_at = ? WHERE job_id = ? AND lease_token = ?",
                (lease_until, current, job.id, lease_token),
            )
            if getattr(lease_update, "rowcount", None) == 0:
                raise LeaseTokenInvalidError()
            job_update = self._execute(
                "UPDATE task_jobs SET lease_until = ?, updated_at = ? WHERE id = ? AND locked_by = ?",
                (lease_until, current, job.id, lease["worker_id"]),
            )
            if getattr(job_update, "rowcount", None) == 0:
                raise LeaseTokenInvalidError()
            updated = self._load_job(job.id, org_id=job.org_id)
            self.connection.commit()
            if updated is None:  # pragma: no cover
                raise RuntimeError("heartbeated task disappeared")
            return TaskLease(updated, str(lease["worker_id"]), str(lease_token), lease_until, int(lease["claim_version"]))
        except Exception:
            self.connection.rollback()
            raise

    def start(
        self,
        *,
        job_id: str,
        lease_token: str,
        worker_id: str | None = None,
        org_id: str | None = None,
        now: datetime | None = None,
    ) -> TaskJob:
        current_dt = _utc(now or datetime.now(timezone.utc))
        try:
            self._begin()
            job, lease = self._validate_lease(job_id, lease_token, org_id=org_id, worker_id=worker_id, now=current_dt)
            updated_cursor = self._execute(
                "UPDATE task_jobs SET status = 'running', updated_at = ? WHERE id = ? AND status = 'leased' AND locked_by = ?",
                (_timestamp(current_dt), job.id, lease["worker_id"]),
            )
            if getattr(updated_cursor, "rowcount", None) == 0:
                raise JobNotClaimableError("job is no longer leased")
            updated = self._load_job(job.id, org_id=job.org_id)
            self.connection.commit()
            if updated is None:  # pragma: no cover
                raise RuntimeError("started task disappeared")
            return updated
        except Exception:
            self.connection.rollback()
            raise

    def complete(
        self,
        *,
        job_id: str,
        lease_token: str,
        worker_id: str | None = None,
        expected_version: int | None = None,
        org_id: str | None = None,
        now: datetime | None = None,
    ) -> TaskJob:
        current_dt = _utc(now or datetime.now(timezone.utc))
        try:
            self._begin()
            job, lease = self._validate_lease(job_id, lease_token, org_id=org_id, worker_id=worker_id, now=current_dt)
            if expected_version is not None and job.aggregate_version != expected_version:
                raise JobVersionConflictError()
            updated_cursor = self._execute(
                "UPDATE task_jobs SET status = 'succeeded', lease_until = NULL, locked_by = NULL, updated_at = ? "
                "WHERE id = ? AND status IN ('leased', 'running') AND locked_by = ?",
                (_timestamp(current_dt), job.id, lease["worker_id"]),
            )
            if getattr(updated_cursor, "rowcount", None) == 0:
                raise LeaseTokenInvalidError()
            self._execute("DELETE FROM task_job_leases WHERE job_id = ? AND lease_token = ?", (job.id, lease_token))
            updated = self._load_job(job.id, org_id=job.org_id)
            self.connection.commit()
            if updated is None:  # pragma: no cover
                raise RuntimeError("completed task disappeared")
            return updated
        except Exception:
            self.connection.rollback()
            raise

    def fail(
        self,
        *,
        job_id: str,
        lease_token: str,
        worker_id: str | None = None,
        error: str,
        expected_version: int | None = None,
        org_id: str | None = None,
        now: datetime | None = None,
    ) -> TaskJob:
        # Compatibility entry: delegate to the same atomic failure transaction.
        from .task_failure import TaskFailureStore, TaskFailureError

        message = _required(error, "error")[:500]
        job = self._load_job(job_id)
        if job is None:
            raise JobNotClaimableError("job was not found")
        try:
            decision = TaskFailureStore(self.connection, dialect=self.dialect).record_failure(
                job_id=job.id, org_id=org_id or job.org_id,
                error_class="deterministic", error_code="WORKER_FAILURE",
                trace_id=job.trace_id, message_redacted=message,
                lease_token=lease_token, worker_id=worker_id,
                expected_version=expected_version, occurred_at=now,
            )
        except TaskFailureError as exc:
            raise TaskClaimError(exc.code, str(exc)) from exc
        return decision.job
