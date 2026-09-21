"""Deterministic, tenant-scoped outbox and task-job lifecycle for workflow.

This module is the domain seam for WORKFLOW-CORE-003.  It keeps the lifecycle
rules independent from a database driver or publisher SDK; the foundation
adapters can persist the same states behind this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4


class DispatchError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _text(value: object, name: str) -> str:
    result = value.strip() if isinstance(value, str) else ""
    if not result:
        raise DispatchError("INVALID_COMMAND", f"{name} is required")
    return result


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(_text(value, name))
    except (TypeError, ValueError) as exc:
        raise DispatchError("INVALID_COMMAND", f"{name} must be a UUID") from exc


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise DispatchError("INVALID_COMMAND", "timestamp must include a timezone")
    return current.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _payload_hash(payload: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise DispatchError("INVALID_COMMAND", "payload must be JSON serializable") from exc
    return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OutboxEvent:
    event_id: UUID
    event_type: str
    org_id: UUID
    trace_id: str
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    idempotency_key: str
    payload: dict[str, Any]
    payload_hash: str
    status: str = "pending"
    attempt_count: int = 0
    last_error: str | None = None
    available_at: str = ""
    lease_until: str | None = None
    locked_by: str | None = None
    published_at: str | None = None

    def as_contract(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id), "event_type": self.event_type,
            "event_schema_version": 1, "occurred_at": self.available_at,
            "org_id": str(self.org_id), "trace_id": self.trace_id,
            "correlation_id": None, "causation_id": None,
            "aggregate_type": self.aggregate_type, "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version, "actor_type": "worker", "actor_id": None,
            "idempotency_key": self.idempotency_key, "payload": self.payload,
            "payload_hash": self.payload_hash, "published_at": self.published_at,
            "attempt_count": self.attempt_count, "last_error": self.last_error,
            "status": self.status, "available_at": self.available_at,
            "lease_until": self.lease_until, "locked_by": self.locked_by,
        }


@dataclass(frozen=True)
class TaskJob:
    id: UUID
    org_id: UUID
    job_type: str
    queue_name: str
    aggregate_type: str
    aggregate_id: UUID
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
    replayed_from_job_id: UUID | None
    replayed_from_attempt_count: int | None
    replay_reason: str | None
    idempotency_key: str
    trace_id: str
    created_at: str
    updated_at: str

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "job_type": self.job_type,
                "queue_name": self.queue_name, "aggregate_type": self.aggregate_type,
                "aggregate_id": str(self.aggregate_id), "aggregate_version": self.aggregate_version,
                "payload_ref": self.payload_ref, "payload_hash": self.payload_hash,
                "status": self.status, "attempt_count": self.attempt_count,
                "max_attempts": self.max_attempts, "available_at": self.available_at,
                "lease_until": self.lease_until, "locked_by": self.locked_by,
                "last_error": self.last_error, "replayed_from_job_id": str(self.replayed_from_job_id) if self.replayed_from_job_id else None,
                "replayed_from_attempt_count": self.replayed_from_attempt_count,
                "replay_reason": self.replay_reason, "idempotency_key": self.idempotency_key,
                "trace_id": self.trace_id, "created_at": self.created_at, "updated_at": self.updated_at}


@dataclass(frozen=True)
class DispatchAttempt:
    event_id: UUID
    org_id: UUID
    worker_id: str
    trace_id: str
    status: str
    attempt_count: int
    started_at: str
    completed_at: str | None = None
    error: str | None = None


Publisher = Callable[[OutboxEvent], str | None]


class OutboxDispatcher:
    """In-memory reference lifecycle with the same rules as the DB adapter."""

    def __init__(self, publisher: Publisher | None = None, *, lease_seconds: int = 30, max_attempts: int = 3) -> None:
        if lease_seconds < 1 or max_attempts < 1:
            raise ValueError("lease_seconds and max_attempts must be positive")
        self.publisher = publisher or (lambda event: "published")
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.events: dict[UUID, OutboxEvent] = {}
        self.jobs: dict[UUID, TaskJob] = {}
        self.dispatch_attempts: list[DispatchAttempt] = []
        self._event_keys: dict[tuple[UUID, str], str] = {}
        self._job_keys: dict[tuple[UUID, str], tuple[str, UUID]] = {}
        self._command_keys: dict[tuple[UUID, str], tuple[str, Any]] = {}

    def append_event(self, *, org_id: UUID | str, event_type: str, trace_id: str, aggregate_type: str,
                     aggregate_id: UUID | str, aggregate_version: int, idempotency_key: str,
                     payload: Mapping[str, Any], event_id: UUID | str | None = None,
                     available_at: datetime | None = None) -> OutboxEvent:
        tenant = _uuid(org_id, "org_id")
        aggregate = _uuid(aggregate_id, "aggregate_id")
        key = _text(idempotency_key, "idempotency_key")
        if aggregate_version < 1:
            raise DispatchError("INVALID_COMMAND", "aggregate_version must be positive")
        kind = _text(event_type, "event_type")
        trace = _text(trace_id, "trace_id")
        digest = _payload_hash(payload)
        existing_hash = self._event_keys.get((tenant, key))
        if existing_hash is not None:
            if existing_hash != digest:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return next(event for event in self.events.values() if event.org_id == tenant and event.idempotency_key == key)
        identifier = _uuid(event_id or uuid4(), "event_id")
        if identifier in self.events:
            raise DispatchError("OUTBOX_DUPLICATE", "event_id already exists")
        timestamp = _stamp(_utc(available_at))
        event = OutboxEvent(identifier, kind, tenant, trace, _text(aggregate_type, "aggregate_type"), aggregate,
                            aggregate_version, key, dict(payload), digest, available_at=timestamp)
        self.events[identifier] = event
        self._event_keys[(tenant, key)] = digest
        return event

    def dispatch_once(self, *, worker_id: str, idempotency_key: str, now: datetime | None = None,
                      org_id: UUID | str | None = None, limit: int = 10) -> tuple[DispatchAttempt, ...]:
        worker = _text(worker_id, "worker_id")
        key = _text(idempotency_key, "idempotency_key")
        if limit < 1:
            raise DispatchError("INVALID_COMMAND", "limit must be positive")
        current = _utc(now)
        tenant = _uuid(org_id, "org_id") if org_id is not None else None
        command_tenant = tenant or UUID(int=0)
        command_hash = _payload_hash({"worker_id": worker, "org_id": str(tenant) if tenant else None, "limit": limit})
        prior = self._command_keys.get((command_tenant, key))
        if prior is not None:
            if prior[0] != command_hash:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return prior[1]
        claimed: list[OutboxEvent] = []
        for event in sorted(self.events.values(), key=lambda item: (item.available_at, str(item.event_id))):
            if len(claimed) >= limit or (tenant is not None and event.org_id != tenant):
                continue
            lease_expired = event.lease_until is not None and datetime.fromisoformat(event.lease_until) <= current
            if event.status == "pending" and datetime.fromisoformat(event.available_at) <= current or event.status == "publishing" and lease_expired:
                claimed_event = replace(event, status="publishing", attempt_count=event.attempt_count + 1,
                                        locked_by=worker, lease_until=_stamp(current + timedelta(seconds=self.lease_seconds)))
                self.events[event.event_id] = claimed_event
                claimed.append(claimed_event)
        attempts: list[DispatchAttempt] = []
        for event in claimed:
            started = _stamp(current)
            try:
                result = self.publisher(event)
                if result == "unknown":
                    raise DispatchError("OUTBOX_PUBLISH_UNKNOWN", "publisher result is unknown")
                if result == "retryable":
                    raise DispatchError("OUTBOX_PUBLISH_RETRYABLE", "publisher requested retry")
                published = replace(event, status="published", published_at=started, lease_until=None, locked_by=None, last_error=None)
                self.events[event.event_id] = published
                self._create_job_from_event(published, current)
                attempt = DispatchAttempt(event.event_id, event.org_id, worker, event.trace_id, "published", event.attempt_count, started, started)
            except DispatchError as exc:
                terminal = exc.code == "OUTBOX_PUBLISH_UNKNOWN" or event.attempt_count >= self.max_attempts
                status = "dead_letter" if terminal else "failed"
                failed = replace(event, status=status, last_error=str(exc), lease_until=None if terminal else event.lease_until,
                                 locked_by=None if terminal else event.locked_by)
                self.events[event.event_id] = failed
                attempt = DispatchAttempt(event.event_id, event.org_id, worker, event.trace_id, status, event.attempt_count, started, started, exc.code)
            attempts.append(attempt)
            self.dispatch_attempts.append(attempt)
        result = tuple(attempts)
        self._command_keys[(command_tenant, key)] = (command_hash, result)
        return result

    def claim_job(self, *, org_id: UUID | str, job_id: UUID | str, worker_id: str,
                  idempotency_key: str, now: datetime | None = None) -> TaskJob:
        tenant = _uuid(org_id, "org_id")
        job = self._job(job_id, tenant)
        key = _text(idempotency_key, "idempotency_key")
        command_hash = _payload_hash({"job_id": str(job.id), "worker_id": worker_id})
        prior = self._command_keys.get((tenant, key))
        if prior is not None:
            if prior[0] != command_hash:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return prior[1]
        current = _utc(now)
        active = job.lease_until and datetime.fromisoformat(job.lease_until) > current
        if job.status not in {"queued", "retry_scheduled"} and not (job.status in {"leased", "running"} and not active):
            raise DispatchError("JOB_NOT_CLAIMABLE", "job is not currently claimable")
        worker = _text(worker_id, "worker_id")
        updated = replace(job, status="leased", attempt_count=job.attempt_count + 1, locked_by=worker,
                          lease_until=_stamp(current + timedelta(seconds=self.lease_seconds)), updated_at=_stamp(current))
        self.jobs[job.id] = updated
        self._command_keys[(tenant, key)] = (command_hash, updated)
        return updated

    def retry_job(self, *, org_id: UUID | str, job_id: UUID | str, error_class: str,
                  error: str, idempotency_key: str, now: datetime | None = None) -> TaskJob:
        tenant = _uuid(org_id, "org_id")
        job = self._job(job_id, tenant)
        key = _text(idempotency_key, "idempotency_key")
        kind = _text(error_class, "error_class")
        if kind not in {"deterministic", "transient", "unknown"}:
            raise DispatchError("INVALID_COMMAND", "error_class is invalid")
        message = _text(error, "error")[:500]
        command_hash = _payload_hash({"job_id": str(job.id), "error_class": kind, "error": message})
        prior = self._command_keys.get((tenant, key))
        if prior is not None:
            if prior[0] != command_hash:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return prior[1]
        current = _utc(now)
        if kind == "transient" and job.attempt_count < job.max_attempts:
            status = "retry_scheduled"
        elif kind == "unknown":
            status = "failed"
        else:
            status = "dead_letter"
        updated = replace(job, status=status, last_error=message, lease_until=None, locked_by=None,
                          available_at=_stamp(current), updated_at=_stamp(current))
        self.jobs[job.id] = updated
        self._command_keys[(tenant, key)] = (command_hash, updated)
        return updated

    def replay_job(self, *, org_id: UUID | str, job_id: UUID | str, reason: str,
                   idempotency_key: str, trace_id: str, now: datetime | None = None) -> TaskJob:
        tenant = _uuid(org_id, "org_id")
        source = self._job(job_id, tenant)
        key = _text(idempotency_key, "idempotency_key")
        trace = _text(trace_id, "trace_id")
        reason_value = _text(reason, "reason")[:500]
        command_hash = _payload_hash({"job_id": str(source.id), "reason": reason_value})
        prior_command = self._command_keys.get((tenant, key))
        if prior_command is not None:
            if prior_command[0] != command_hash:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return prior_command[1]
        existing = self._job_keys.get((tenant, key))
        if existing is not None:
            payload_hash, existing_id = existing
            if payload_hash != source.payload_hash or existing_id not in self.jobs:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "idempotency key belongs to another replay")
            return self.jobs[existing_id]
        if source.status not in {"failed", "dead_letter"}:
            raise DispatchError("REPLAY_NOT_ALLOWED", "only failed or dead-letter jobs may be replayed")
        current = _stamp(_utc(now))
        replay = replace(source, id=uuid4(), status="queued", attempt_count=0, lease_until=None, locked_by=None,
                         last_error=None, replayed_from_job_id=source.id, replayed_from_attempt_count=source.attempt_count,
                         replay_reason=reason_value, idempotency_key=key, trace_id=trace, available_at=current, updated_at=current)
        self.jobs[replay.id] = replay
        self._job_keys[(tenant, key)] = (source.payload_hash, replay.id)
        self._command_keys[(tenant, key)] = (command_hash, replay)
        return replay

    def _create_job_from_event(self, event: OutboxEvent, now: datetime) -> TaskJob | None:
        spec = event.payload.get("task_job")
        if not isinstance(spec, Mapping):
            return None
        key = str(spec.get("idempotency_key", event.idempotency_key))
        payload = spec.get("payload", event.payload)
        if not isinstance(payload, Mapping):
            raise DispatchError("INVALID_COMMAND", "task_job payload must be an object")
        existing = self._job_keys.get((event.org_id, key))
        digest = _payload_hash(payload)
        if existing is not None:
            if existing[0] != digest:
                raise DispatchError("IDEMPOTENCY_KEY_REUSED", "task job idempotency key payload differs")
            return self.jobs[existing[1]]
        timestamp = _stamp(now)
        job = TaskJob(uuid4(), event.org_id, _text(spec.get("job_type", event.event_type), "job_type"),
                      _text(spec.get("queue_name", "default"), "queue_name"), event.aggregate_type, event.aggregate_id,
                      event.aggregate_version, _text(spec.get("payload_ref", "private://workflow"), "payload_ref"),
                      digest, "queued", 0, int(spec.get("max_attempts", self.max_attempts)), timestamp, None, None, None,
                      None, None, None, key, event.trace_id, timestamp, timestamp)
        self.jobs[job.id] = job
        self._job_keys[(event.org_id, key)] = (digest, job.id)
        return job

    def _job(self, job_id: UUID | str, org_id: UUID) -> TaskJob:
        identifier = _uuid(job_id, "job_id")
        job = self.jobs.get(identifier)
        if job is None:
            raise DispatchError("JOB_NOT_FOUND", "task job was not found")
        if job.org_id != org_id:
            raise DispatchError("TENANT_SCOPE_VIOLATION", "task job belongs to another organization")
        return job


__all__ = ["DispatchAttempt", "DispatchError", "OutboxDispatcher", "OutboxEvent", "TaskJob"]
