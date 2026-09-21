"""Synthetic backup and restore drill primitives for OBS-CORE-002."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from threading import RLock
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from .service import AuditLogService


class RecoveryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise RecoveryError("INVALID_RECOVERY_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecoveryError("INVALID_RECOVERY_COMMAND", f"{name} is required")
    return value.strip()


def _utc(value: datetime | str, name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RecoveryError("INVALID_RECOVERY_COMMAND", f"{name} must be ISO-8601") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise RecoveryError("INVALID_RECOVERY_COMMAND", f"{name} must include a timezone")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat(timespec="microseconds")


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BackupSnapshot:
    id: UUID
    org_id: UUID
    database_snapshot_ref: str
    object_snapshot_ref: str
    captured_at: str
    latest_event_at: str
    payload_hash: str
    status: str
    version: int = 1

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "database_snapshot_ref": self.database_snapshot_ref,
            "object_snapshot_ref": self.object_snapshot_ref,
            "captured_at": self.captured_at,
            "latest_event_at": self.latest_event_at,
            "payload_hash": self.payload_hash,
            "status": self.status,
            "version": self.version,
        }


@dataclass(frozen=True)
class RecoveryMeasurement:
    rpo_minutes: float
    rto_minutes: float
    missing_event_count: int
    rpo_target_minutes: int
    rto_target_minutes: int
    target_met: bool

    def as_contract(self) -> dict[str, Any]:
        return {
            "rpo_minutes": self.rpo_minutes,
            "rto_minutes": self.rto_minutes,
            "missing_event_count": self.missing_event_count,
            "rpo_target_minutes": self.rpo_target_minutes,
            "rto_target_minutes": self.rto_target_minutes,
            "target_met": self.target_met,
        }


@dataclass(frozen=True)
class RestoreRun:
    id: UUID
    org_id: UUID
    snapshot_id: UUID
    trace_id: str
    failure_started_at: str
    restored_at: str
    latest_recovered_event_at: str
    measurement: RecoveryMeasurement
    status: str
    queues_paused: bool
    version: int = 1

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "snapshot_id": str(self.snapshot_id),
            "trace_id": self.trace_id,
            "failure_started_at": self.failure_started_at,
            "restored_at": self.restored_at,
            "latest_recovered_event_at": self.latest_recovered_event_at,
            "measurement": self.measurement.as_contract(),
            "status": self.status,
            "queues_paused": self.queues_paused,
            "version": self.version,
        }


@dataclass(frozen=True)
class QueuePause:
    org_id: UUID
    queue_name: str
    restore_id: UUID
    paused: bool
    version: int


class RecoveryService:
    """Account-free recovery drill with explicit queue safety state."""

    def __init__(self, *, audit_log: AuditLogService | None = None,
                 rpo_target_minutes: int = 60, rto_target_minutes: int = 240) -> None:
        if rpo_target_minutes < 0 or rto_target_minutes < 0:
            raise RecoveryError("INVALID_RECOVERY_POLICY", "recovery targets must be non-negative")
        self.rpo_target_minutes = rpo_target_minutes
        self.rto_target_minutes = rto_target_minutes
        self.snapshots: dict[UUID, BackupSnapshot] = {}
        self.restores: dict[UUID, RestoreRun] = {}
        self.queue_states: dict[tuple[UUID, str], QueuePause] = {}
        self._snapshot_payloads: dict[UUID, tuple[Any, Any]] = {}
        self._commands: dict[tuple[UUID, str], tuple[str, Any]] = {}
        self._audit_log = audit_log
        self._lock = RLock()

    def create_backup(
        self,
        *,
        org_id: UUID | str,
        database_payload: Any,
        object_payload: Any,
        latest_event_at: datetime | str,
        captured_at: datetime | str,
        idempotency_key: str,
        trace_id: str,
        actor_type: str = "system",
        actor_id: UUID | str | None = None,
    ) -> BackupSnapshot:
        tenant = _uuid(org_id, "org_id")
        key = self._key(idempotency_key)
        captured = _utc(captured_at, "captured_at")
        latest = _utc(latest_event_at, "latest_event_at")
        if latest > captured:
            raise RecoveryError("INVALID_RECOVERY_TIMELINE", "latest_event_at cannot be after captured_at")
        command_hash = _hash({"database": database_payload, "objects": object_payload,
                              "latest_event_at": _stamp(latest), "captured_at": _stamp(captured)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != command_hash:
                    raise RecoveryError("IDEMPOTENCY_KEY_REUSED", "backup idempotency key payload differs")
                return prior[1]
            snapshot = BackupSnapshot(
                id=uuid4(), org_id=tenant,
                database_snapshot_ref=f"synthetic://database/{uuid4()}",
                object_snapshot_ref=f"synthetic://objects/{uuid4()}",
                captured_at=_stamp(captured), latest_event_at=_stamp(latest),
                payload_hash=_hash({"database": database_payload, "objects": object_payload}),
                status="available",
            )
            self.snapshots[snapshot.id] = snapshot
            self._snapshot_payloads[snapshot.id] = (database_payload, object_payload)
            self._commands[(tenant, key)] = (command_hash, snapshot)
            self._audit("backup.created", tenant, trace_id, actor_type, actor_id, snapshot.id, key,
                        {"payload_hash": snapshot.payload_hash})
            return snapshot

    def restore(
        self,
        *,
        org_id: UUID | str,
        snapshot_id: UUID | str,
        failure_started_at: datetime | str,
        idempotency_key: str,
        trace_id: str,
        restored_at: datetime | str | None = None,
        latest_recovered_event_at: datetime | str | None = None,
        missing_event_count: int = 0,
        queue_names: Iterable[str] = ("default",),
        actor_type: str = "system",
        actor_id: UUID | str | None = None,
    ) -> RestoreRun:
        tenant = _uuid(org_id, "org_id")
        snapshot = self._snapshot(snapshot_id, tenant)
        key = self._key(idempotency_key)
        failure = _utc(failure_started_at, "failure_started_at")
        recovered = _utc(latest_recovered_event_at, "latest_recovered_event_at") if latest_recovered_event_at is not None else _utc(snapshot.latest_event_at, "latest_event_at")
        if recovered > failure:
            raise RecoveryError("INVALID_RECOVERY_TIMELINE", "restore timestamps are not ordered")
        if missing_event_count < 0:
            raise RecoveryError("INVALID_RECOVERY_COMMAND", "missing_event_count must be non-negative")
        queue_names = tuple(dict.fromkeys(_text(name, "queue_name") for name in queue_names))
        if not queue_names:
            raise RecoveryError("INVALID_RECOVERY_COMMAND", "at least one queue is required")
        explicit_restored = _utc(restored_at, "restored_at") if restored_at is not None else None
        command_hash = _hash({"snapshot_id": str(snapshot.id), "failure": _stamp(failure),
                              "restored": _stamp(explicit_restored) if explicit_restored else None, "recovered": _stamp(recovered),
                              "missing_event_count": missing_event_count, "queues": sorted(queue_names)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != command_hash:
                    raise RecoveryError("IDEMPOTENCY_KEY_REUSED", "restore idempotency key payload differs")
                return prior[1]
            restored = explicit_restored or datetime.now(timezone.utc)
            if restored < failure:
                raise RecoveryError("INVALID_RECOVERY_TIMELINE", "restore timestamps are not ordered")
            rpo = max(0.0, (failure - recovered).total_seconds() / 60)
            rto = max(0.0, (restored - failure).total_seconds() / 60)
            measurement = RecoveryMeasurement(rpo, rto, missing_event_count,
                                              self.rpo_target_minutes, self.rto_target_minutes,
                                              rpo <= self.rpo_target_minutes and rto <= self.rto_target_minutes and missing_event_count == 0)
            restore = RestoreRun(
                id=uuid4(), org_id=tenant, snapshot_id=snapshot.id, trace_id=_text(trace_id, "trace_id"),
                failure_started_at=_stamp(failure), restored_at=_stamp(restored),
                latest_recovered_event_at=_stamp(recovered), measurement=measurement,
                status="completed", queues_paused=True,
            )
            self.restores[restore.id] = restore
            self._pause_queues(tenant, restore.id, queue_names)
            self._commands[(tenant, key)] = (command_hash, restore)
            self._audit("restore.completed", tenant, trace_id, actor_type, actor_id, restore.id, key,
                        {"target_met": measurement.target_met, "rpo_minutes": rpo, "rto_minutes": rto})
            return restore

    def release_queues(
        self, *, org_id: UUID | str, restore_id: UUID | str, expected_version: int,
        idempotency_key: str, trace_id: str, actor_type: str = "system",
        actor_id: UUID | str | None = None,
    ) -> RestoreRun:
        tenant = _uuid(org_id, "org_id")
        restore = self._restore(restore_id, tenant)
        key = self._key(idempotency_key)
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != _hash({"restore_id": str(restore.id), "expected_version": expected_version}):
                    raise RecoveryError("IDEMPOTENCY_KEY_REUSED", "release idempotency key payload differs")
                return prior[1]
            if restore.version != expected_version:
                raise RecoveryError("VERSION_CONFLICT", "restore version changed")
            if not restore.measurement.target_met:
                raise RecoveryError("RECOVERY_TARGET_NOT_MET", "queues remain paused until RPO/RTO targets are met")
            updated = replace(restore, queues_paused=False, version=restore.version + 1)
            self.restores[restore.id] = updated
            for key_state, state in list(self.queue_states.items()):
                if key_state[0] == tenant and state.restore_id == restore.id:
                    self.queue_states[key_state] = replace(state, paused=False, version=state.version + 1)
            command_hash = _hash({"restore_id": str(restore.id), "expected_version": expected_version})
            self._commands[(tenant, key)] = (command_hash, updated)
            self._audit("restore.queues_released", tenant, trace_id, actor_type, actor_id, restore.id, key, {})
            return updated

    def _pause_queues(self, tenant: UUID, restore_id: UUID, queue_names: Iterable[str]) -> None:
        names = tuple(queue_names)
        for name in names:
            current = self.queue_states.get((tenant, name))
            self.queue_states[(tenant, name)] = QueuePause(tenant, name, restore_id, True, (current.version + 1 if current else 1))

    def _snapshot(self, value: UUID | str, tenant: UUID) -> BackupSnapshot:
        snapshot = self.snapshots.get(_uuid(value, "snapshot_id"))
        if snapshot is None or snapshot.org_id != tenant:
            raise RecoveryError("TENANT_SCOPE_VIOLATION", "backup snapshot does not belong to organization")
        return snapshot

    def _restore(self, value: UUID | str, tenant: UUID) -> RestoreRun:
        restore = self.restores.get(_uuid(value, "restore_id"))
        if restore is None or restore.org_id != tenant:
            raise RecoveryError("TENANT_SCOPE_VIOLATION", "restore run does not belong to organization")
        return restore

    @staticmethod
    def _key(value: str) -> str:
        return _text(value, "idempotency_key")

    def _audit(self, action: str, org_id: UUID, trace_id: str, actor_type: str,
               actor_id: UUID | str | None, subject_id: UUID, key: str, payload: Mapping[str, Any]) -> None:
        if self._audit_log is None:
            return
        self._audit_log.record(org_id=org_id, trace_id=trace_id, actor_type=actor_type,
                               actor_id=actor_id, action=action, subject_type="recovery_run",
                               subject_id=subject_id, input_payload=payload,
                               idempotency_key=f"recovery:{key}")


__all__ = ["BackupSnapshot", "QueuePause", "RecoveryError", "RecoveryMeasurement", "RecoveryService", "RestoreRun"]
