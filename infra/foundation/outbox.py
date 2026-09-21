"""Transactional Outbox storage and an account-free dispatcher seam.

The store owns the database transaction that persists business state and its
immutable event together.  Dispatch is deliberately publisher-agnostic: a
publisher receives a complete event envelope and can be replaced by a fake in
tests.  No platform SDK, credential, or network client is imported here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4


EVENT_TYPE_RE = re.compile(r"^[a-z0-9_.]+$")
OUTBOX_STATUSES = frozenset({"pending", "publishing", "published", "failed", "dead_letter"})
ACTOR_TYPES = frozenset({"user", "service", "system", "worker"})


class OutboxError(RuntimeError):
    """Base error with a stable contract code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class OutboxValidationError(OutboxError):
    def __init__(self, message: str) -> None:
        super().__init__("INVALID_EVENT_ENVELOPE", message)


class OutboxDuplicateError(OutboxError):
    def __init__(self, message: str = "event_id already exists") -> None:
        super().__init__("OUTBOX_DUPLICATE", message)


class IdempotencyKeyReusedError(OutboxError):
    def __init__(self, message: str = "idempotency key was reused with a different payload") -> None:
        super().__init__("IDEMPOTENCY_KEY_REUSED", message)


class TenantScopeViolation(OutboxError):
    def __init__(self, message: str = "event does not belong to the requested organization") -> None:
        super().__init__("TENANT_SCOPE_VIOLATION", message)


class OutboxPublishError(OutboxError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(
            "OUTBOX_PUBLISH_RETRYABLE" if retryable else "OUTBOX_DEAD_LETTER",
            message,
            retryable=retryable,
        )


class OutboxUnknownResult(OutboxError):
    def __init__(self, message: str = "publisher result is unknown") -> None:
        super().__init__("OUTBOX_PUBLISH_UNKNOWN", message, retryable=False)


class OutboxLeaseLostError(OutboxError):
    """Raised when a worker loses its lease before completing a transition."""

    def __init__(self, message: str = "event lease is no longer owned by this worker") -> None:
        super().__init__("OUTBOX_LEASE_LOST", message, retryable=True)


class DBAPICursor(Protocol):
    description: object

    def fetchone(self) -> object: ...

    def fetchall(self) -> list[object]: ...


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


StateWriter = Callable[[DBAPIConnection], None]


def _required_text(value: object, *, name: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise OutboxValidationError(f"{name} must not be empty")
    return normalized


def _uuid_text(value: str, *, name: str) -> str:
    normalized = _required_text(value, name=name)
    try:
        return str(UUID(normalized))
    except ValueError as exc:
        raise OutboxValidationError(f"{name} must be a UUID") from exc


def _utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OutboxValidationError(f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, name="timestamp").isoformat(timespec="microseconds")


def _canonical_payload(payload: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(payload, Mapping):
        raise OutboxValidationError("payload must be an object")
    try:
        encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise OutboxValidationError("payload must be JSON serializable") from exc
    return encoded, sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EventEnvelope:
    event_id: str
    event_type: str
    event_schema_version: int
    occurred_at: str
    org_id: str
    trace_id: str
    correlation_id: str | None
    causation_id: str | None
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    actor_type: str
    actor_id: str | None
    idempotency_key: str
    payload: dict[str, Any]
    payload_hash: str

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        event_schema_version: int,
        occurred_at: datetime,
        org_id: str,
        trace_id: str,
        aggregate_type: str,
        aggregate_id: str,
        aggregate_version: int,
        actor_type: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        event_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        actor_id: str | None = None,
    ) -> "EventEnvelope":
        if not isinstance(event_type, str) or not EVENT_TYPE_RE.fullmatch(event_type):
            raise OutboxValidationError("event_type must match ^[a-z0-9_.]+$")
        if isinstance(event_schema_version, bool) or not isinstance(event_schema_version, int) or event_schema_version < 1:
            raise OutboxValidationError("event_schema_version must be at least one")
        if aggregate_version < 1:
            raise OutboxValidationError("aggregate_version must be at least one")
        if actor_type not in ACTOR_TYPES:
            raise OutboxValidationError("actor_type is invalid")
        encoded, payload_hash = _canonical_payload(payload)
        del encoded
        event_uuid = _uuid_text(event_id or str(uuid4()), name="event_id")
        organization = _uuid_text(org_id, name="org_id")
        aggregate = _uuid_text(aggregate_id, name="aggregate_id")
        actor = _uuid_text(actor_id, name="actor_id") if actor_id is not None else None
        return cls(
            event_id=event_uuid,
            event_type=event_type,
            event_schema_version=event_schema_version,
            occurred_at=_timestamp(occurred_at),
            org_id=organization,
            trace_id=_required_text(trace_id, name="trace_id"),
            correlation_id=_required_text(correlation_id, name="correlation_id") if correlation_id else None,
            causation_id=_required_text(causation_id, name="causation_id") if causation_id else None,
            aggregate_type=_required_text(aggregate_type, name="aggregate_type"),
            aggregate_id=aggregate,
            aggregate_version=aggregate_version,
            actor_type=actor_type,
            actor_id=actor,
            idempotency_key=_required_text(idempotency_key, name="idempotency_key"),
            payload=dict(payload),
            payload_hash=payload_hash,
        )

    def as_contract(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_schema_version": self.event_schema_version,
            "occurred_at": self.occurred_at,
            "org_id": self.org_id,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "idempotency_key": self.idempotency_key,
            "payload": self.payload,
            "payload_hash": self.payload_hash,
        }


@dataclass(frozen=True)
class OutboxEvent:
    envelope: EventEnvelope
    published_at: str | None
    attempt_count: int
    last_error: str | None
    status: str
    available_at: str
    lease_until: str | None
    locked_by: str | None

    @property
    def event_id(self) -> str:
        return self.envelope.event_id

    @property
    def org_id(self) -> str:
        return self.envelope.org_id

    def as_contract(self) -> dict[str, Any]:
        value = self.envelope.as_contract()
        value.update(
            {
                "published_at": self.published_at,
                "attempt_count": self.attempt_count,
                "last_error": self.last_error,
                "status": self.status,
                "available_at": self.available_at,
                "lease_until": self.lease_until,
                "locked_by": self.locked_by,
            }
        )
        return value


@dataclass(frozen=True)
class PublishResult:
    status: str = "published"
    message: str | None = None


@dataclass(frozen=True)
class DispatchResult:
    event_id: str
    status: str
    code: str | None
    attempt_count: int
    error: str | None = None


_EVENT_COLUMNS = (
    "event_id", "event_type", "event_schema_version", "occurred_at", "org_id", "trace_id",
    "correlation_id", "causation_id", "aggregate_type", "aggregate_id", "aggregate_version",
    "actor_type", "actor_id", "idempotency_key", "payload", "payload_hash", "published_at",
    "attempt_count", "last_error", "status", "available_at", "lease_until", "locked_by",
)
_EVENT_COLUMN_SQL = ", ".join(_EVENT_COLUMNS)


def _row_mapping(cursor: DBAPICursor, row: object) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    if not cursor.description:
        raise RuntimeError("outbox query did not return column metadata")
    names = [column[0] for column in cursor.description]  # type: ignore[index]
    return dict(zip(names, row))  # type: ignore[arg-type]


def _redact_error(error: BaseException) -> str:
    message = str(error).replace("\r", " ").replace("\n", " ").strip()
    return f"{type(error).__name__}: {message[:500]}" if message else type(error).__name__


class OutboxStore:
    """DB-API Outbox store with tenant-scoped idempotency and short leases."""

    POSTGRES_CLAIM_SQL = (
        "SELECT " + _EVENT_COLUMN_SQL + " FROM outbox_events "
        "WHERE (status = 'pending' OR (status = 'publishing' AND lease_until <= %s)) "
        "AND available_at <= %s ORDER BY available_at, event_id LIMIT %s "
        "FOR UPDATE SKIP LOCKED"
    )

    def __init__(
        self,
        connection: DBAPIConnection,
        *,
        max_attempts: int = 3,
        lease_seconds: int = 30,
        retry_base_seconds: int = 5,
        dialect: str = "sqlite",
    ) -> None:
        if max_attempts < 1 or lease_seconds < 1 or retry_base_seconds < 1:
            raise ValueError("attempt, lease, and retry settings must be positive")
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError("dialect must be sqlite or postgresql")
        self.connection = connection
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds
        self.dialect = dialect

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> DBAPICursor:
        if self.dialect == "postgresql":
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, parameters)

    def _event_from_row(self, row: Mapping[str, Any]) -> OutboxEvent:
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise OutboxValidationError("stored payload is not valid JSON") from exc
        envelope = EventEnvelope(
            event_id=str(row["event_id"]),
            event_type=str(row["event_type"]),
            event_schema_version=int(row["event_schema_version"]),
            occurred_at=str(row["occurred_at"]),
            org_id=str(row["org_id"]),
            trace_id=str(row["trace_id"]),
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=str(row["aggregate_id"]),
            aggregate_version=int(row["aggregate_version"]),
            actor_type=str(row["actor_type"]),
            actor_id=row["actor_id"],
            idempotency_key=str(row["idempotency_key"]),
            payload=dict(payload),
            payload_hash=str(row["payload_hash"]),
        )
        return OutboxEvent(
            envelope=envelope,
            published_at=row["published_at"],
            attempt_count=int(row["attempt_count"]),
            last_error=row["last_error"],
            status=str(row["status"]),
            available_at=str(row["available_at"]),
            lease_until=row["lease_until"],
            locked_by=row["locked_by"],
        )

    def _find_by_event_id(self, event_id: str) -> OutboxEvent | None:
        cursor = self._execute(
            f"SELECT {_EVENT_COLUMN_SQL} FROM outbox_events WHERE event_id = ?", (event_id,)
        )
        row = cursor.fetchone()
        return self._event_from_row(_row_mapping(cursor, row)) if row is not None else None

    def _find_by_idempotency(self, org_id: str, idempotency_key: str) -> OutboxEvent | None:
        cursor = self._execute(
            f"SELECT {_EVENT_COLUMN_SQL} FROM outbox_events WHERE org_id = ? AND idempotency_key = ?",
            (org_id, idempotency_key),
        )
        row = cursor.fetchone()
        return self._event_from_row(_row_mapping(cursor, row)) if row is not None else None

    def append(self, envelope: EventEnvelope, *, available_at: datetime | None = None) -> OutboxEvent:
        """Insert one immutable event without committing the caller's transaction."""
        encoded, calculated_hash = _canonical_payload(envelope.payload)
        if calculated_hash != envelope.payload_hash:
            raise OutboxValidationError("payload_hash does not match payload")
        existing_id = self._find_by_event_id(envelope.event_id)
        if existing_id is not None:
            raise OutboxDuplicateError()
        existing_key = self._find_by_idempotency(envelope.org_id, envelope.idempotency_key)
        if existing_key is not None:
            if existing_key.envelope.payload_hash != envelope.payload_hash:
                raise IdempotencyKeyReusedError()
            return existing_key
        ready_at = _timestamp(available_at or datetime.now(timezone.utc))
        self._execute(
            f"INSERT INTO outbox_events ({_EVENT_COLUMN_SQL}) VALUES ({', '.join('?' for _ in _EVENT_COLUMNS)})",
            (
                envelope.event_id, envelope.event_type, envelope.event_schema_version, envelope.occurred_at,
                envelope.org_id, envelope.trace_id, envelope.correlation_id, envelope.causation_id,
                envelope.aggregate_type, envelope.aggregate_id, envelope.aggregate_version, envelope.actor_type,
                envelope.actor_id, envelope.idempotency_key, encoded, envelope.payload_hash, None, 0, None,
                "pending", ready_at, None, None,
            ),
        )
        return OutboxEvent(envelope, None, 0, None, "pending", ready_at, None, None)

    def commit_state_and_event(self, state_writer: StateWriter, envelope: EventEnvelope) -> OutboxEvent:
        """Commit a business-state callback and Outbox insert as one transaction."""
        existing = self._find_by_event_id(envelope.event_id)
        if existing is not None:
            raise OutboxDuplicateError()
        existing = self._find_by_idempotency(envelope.org_id, envelope.idempotency_key)
        if existing is not None:
            if existing.envelope.payload_hash != envelope.payload_hash:
                raise IdempotencyKeyReusedError()
            return existing
        try:
            if not getattr(self.connection, "in_transaction", False):
                self._execute("BEGIN")
            state_writer(self.connection)
            event = self.append(envelope)
            self.connection.commit()
            return event
        except Exception:
            self.connection.rollback()
            raise

    def get(self, event_id: str, *, org_id: str | None = None) -> OutboxEvent:
        event = self._find_by_event_id(_uuid_text(event_id, name="event_id"))
        if event is None:
            raise OutboxDuplicateError("event_id was not found")
        if org_id is not None and event.org_id != _uuid_text(org_id, name="org_id"):
            raise TenantScopeViolation()
        return event

    def retry_due(self, *, now: datetime | None = None, org_id: str | None = None) -> int:
        current = _timestamp(now or datetime.now(timezone.utc))
        params: tuple[object, ...] = (current,)
        where = "status = 'failed' AND available_at <= ?"
        if org_id is not None:
            where += " AND org_id = ?"
            params += (_uuid_text(org_id, name="org_id"),)
        cursor = self._execute(
            "UPDATE outbox_events SET status = 'pending', lease_until = NULL, locked_by = NULL WHERE " + where,
            params,
        )
        self.connection.commit()
        rowcount = getattr(cursor, "rowcount", 0)
        return max(int(rowcount), 0)

    def claim(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        limit: int = 10,
        org_id: str | None = None,
    ) -> tuple[OutboxEvent, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        worker = _required_text(worker_id, name="worker_id")
        current_dt = _utc(now or datetime.now(timezone.utc), name="now")
        current = _timestamp(current_dt)
        lease_until = _timestamp(current_dt + timedelta(seconds=self.lease_seconds))
        tenant_clause = " AND org_id = ?" if org_id is not None else ""
        tenant_params: tuple[object, ...] = (_uuid_text(org_id, name="org_id"),) if org_id is not None else ()
        try:
            if self.dialect == "sqlite" and not getattr(self.connection, "in_transaction", False):
                self._execute("BEGIN IMMEDIATE")
            if self.dialect == "postgresql":
                postgres_tenant = " AND org_id = %s" if org_id is not None else ""
                cursor = self.connection.execute(
                    "SELECT " + _EVENT_COLUMN_SQL + " FROM outbox_events "
                    "WHERE ((status = 'pending' AND available_at <= %s) "
                    "OR (status = 'publishing' AND lease_until IS NOT NULL AND lease_until <= %s))"
                    + postgres_tenant + " ORDER BY available_at ASC, event_id ASC LIMIT %s FOR UPDATE SKIP LOCKED",
                    (current, current, *tenant_params, limit),
                )
            else:
                cursor = self._execute(
                    f"SELECT {_EVENT_COLUMN_SQL} FROM outbox_events "
                    "WHERE ((status = 'pending' AND available_at <= ?) "
                    "OR (status = 'publishing' AND lease_until IS NOT NULL AND lease_until <= ?))"
                    + tenant_clause + " ORDER BY available_at ASC, event_id ASC LIMIT ?",
                    (current, current, *tenant_params, limit),
                )
            selected = [_row_mapping(cursor, row) for row in cursor.fetchall()]
            events: list[OutboxEvent] = []
            for row in selected:
                event_id = str(row["event_id"])
                self._execute(
                    "UPDATE outbox_events SET status = 'publishing', attempt_count = attempt_count + 1, "
                    "lease_until = ?, locked_by = ? WHERE event_id = ?",
                    (lease_until, worker, event_id),
                )
                updated = dict(row)
                updated.update(
                    {"status": "publishing", "attempt_count": int(row["attempt_count"]) + 1,
                     "lease_until": lease_until, "locked_by": worker}
                )
                events.append(self._event_from_row(updated))
            self.connection.commit()
            return tuple(events)
        except Exception:
            self.connection.rollback()
            raise

    def mark_published(
        self, event_id: str, *, worker_id: str, now: datetime | None = None, org_id: str | None = None
    ) -> OutboxEvent:
        try:
            event = self.get(event_id, org_id=org_id)
            if event.status != "publishing" or event.locked_by != worker_id:
                raise OutboxError("OUTBOX_DUPLICATE", "event is not leased by this worker")
            timestamp = _timestamp(now or datetime.now(timezone.utc))
            updated = self._execute(
                "UPDATE outbox_events SET status = 'published', published_at = ?, lease_until = NULL, "
                "locked_by = NULL, last_error = NULL WHERE event_id = ? AND status = 'publishing' AND locked_by = ?",
                (timestamp, event.event_id, worker_id),
            )
            if getattr(updated, "rowcount", None) != 1:
                raise OutboxLeaseLostError()
            self.connection.commit()
            return self.get(event.event_id, org_id=org_id)
        except Exception:
            self.connection.rollback()
            raise

    def mark_failed(
        self,
        event_id: str,
        *,
        worker_id: str,
        error: BaseException,
        now: datetime | None = None,
        retryable: bool = True,
        org_id: str | None = None,
    ) -> tuple[OutboxEvent, str]:
        try:
            event = self.get(event_id, org_id=org_id)
            if event.status != "publishing" or event.locked_by != worker_id:
                raise OutboxError("OUTBOX_DUPLICATE", "event is not leased by this worker")
            timestamp_dt = _utc(now or datetime.now(timezone.utc), name="now")
            redacted = _redact_error(error)
            terminal = not retryable or event.attempt_count >= self.max_attempts
            status = "dead_letter" if terminal else "failed"
            available = timestamp_dt if terminal else timestamp_dt + timedelta(
                seconds=self.retry_base_seconds * (2 ** max(event.attempt_count - 1, 0))
            )
            updated = self._execute(
                "UPDATE outbox_events SET status = ?, last_error = ?, available_at = ?, lease_until = NULL, "
                "locked_by = NULL WHERE event_id = ? AND status = 'publishing' AND locked_by = ?",
                (status, redacted, _timestamp(available), event.event_id, worker_id),
            )
            if getattr(updated, "rowcount", None) != 1:
                raise OutboxLeaseLostError()
            self.connection.commit()
            return self.get(event.event_id, org_id=org_id), (
                "OUTBOX_DEAD_LETTER" if terminal else "OUTBOX_PUBLISH_RETRYABLE"
            )
        except Exception:
            self.connection.rollback()
            raise


class Publisher(Protocol):
    def publish(self, envelope: EventEnvelope) -> PublishResult | None: ...


class OutboxDispatcher:
    """At-least-once publisher loop over the Outbox store."""

    def __init__(self, store: OutboxStore, publisher: Publisher | Callable[[EventEnvelope], PublishResult | None]) -> None:
        self.store = store
        self.publisher = publisher

    def _publish(self, envelope: EventEnvelope) -> PublishResult:
        method = getattr(self.publisher, "publish", None)
        result = method(envelope) if method is not None else self.publisher(envelope)  # type: ignore[operator]
        if result is None:
            return PublishResult()
        if not isinstance(result, PublishResult):
            raise OutboxPublishError("publisher returned an invalid result", retryable=False)
        if result.status == "published":
            return result
        if result.status == "retryable":
            raise OutboxPublishError(result.message or "publisher requested retry", retryable=True)
        if result.status == "unknown":
            raise OutboxUnknownResult(result.message or "publisher result is unknown")
        raise OutboxPublishError("publisher returned an invalid status", retryable=False)

    def dispatch_once(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        limit: int = 10,
        org_id: str | None = None,
    ) -> tuple[DispatchResult, ...]:
        current = now or datetime.now(timezone.utc)
        self.store.retry_due(now=current, org_id=org_id)
        claimed = self.store.claim(worker_id=worker_id, now=current, limit=limit, org_id=org_id)
        results: list[DispatchResult] = []
        for event in claimed:
            try:
                self._publish(event.envelope)
            except OutboxPublishError as exc:
                failed, code = self.store.mark_failed(
                    event.event_id,
                    worker_id=worker_id,
                    error=exc,
                    now=current,
                    retryable=exc.retryable,
                    org_id=org_id,
                )
                results.append(DispatchResult(failed.event_id, failed.status, code, failed.attempt_count, failed.last_error))
            except OutboxUnknownResult as exc:
                # Preserve ``publishing`` until the lease expires: an unknown
                # provider result must not create a second external request.
                results.append(
                    DispatchResult(
                        event.event_id,
                        event.status,
                        exc.code,
                        event.attempt_count,
                        str(exc),
                    )
                )
            except Exception as exc:
                failed, code = self.store.mark_failed(
                    event.event_id,
                    worker_id=worker_id,
                    error=exc,
                    now=current,
                    retryable=True,
                    org_id=org_id,
                )
                results.append(DispatchResult(failed.event_id, failed.status, code, failed.attempt_count, failed.last_error))
            else:
                published = self.store.mark_published(event.event_id, worker_id=worker_id, now=current, org_id=org_id)
                results.append(DispatchResult(published.event_id, published.status, None, published.attempt_count))
        return tuple(results)
