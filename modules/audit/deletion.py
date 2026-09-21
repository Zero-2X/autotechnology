"""Tenant-scoped synthetic deletion propagation and manual review queue."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator

from .service import AuditLogService


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "packages" / "contracts" / "jsonschema" / "deletion-request.schema.json"
STAGES = ("relational_db", "object_storage", "vector_index", "cache", "export_package")
STAGE_ALIASES = {"database": "relational_db", "object": "object_storage", "vector": "vector_index", "export": "export_package"}


class DeletionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise DeletionError("INVALID_DELETION_REQUEST", f"{name} must be a UUID") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeletionError("INVALID_DELETION_REQUEST", f"{name} is required")
    return value.strip()


def _stamp(value: datetime | str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise DeletionError("INVALID_DELETION_REQUEST", "timestamp must include a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return _text(value, "timestamp")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def validate_deletion_request(value: Mapping[str, Any]) -> dict[str, Any]:
    candidate = dict(value)
    errors = sorted(Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).iter_errors(candidate), key=lambda item: list(item.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "deletion_request"
        raise DeletionError("INVALID_DELETION_REQUEST", f"{location}: {errors[0].message}")
    return candidate


@dataclass(frozen=True)
class DeletionRequest:
    id: UUID
    org_id: UUID
    subject_type: str
    subject_id: UUID
    requested_by: UUID
    status: str
    requested_at: str
    completed_at: str | None
    version: int = 0

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "subject_type": self.subject_type,
                "subject_id": str(self.subject_id), "requested_by": str(self.requested_by),
                "status": self.status, "requested_at": self.requested_at, "completed_at": self.completed_at}


@dataclass(frozen=True)
class DeletionStage:
    request_id: UUID
    org_id: UUID
    stage: str
    status: str
    trace_id: str
    confirmed_at: str | None = None
    error: str | None = None
    version: int = 0
    evidence_ref: str | None = None


class DeletionTarget(Protocol):
    def delete(self, *, org_id: UUID, subject_type: str, subject_id: UUID) -> str: ...
    def absent(self, *, org_id: UUID, subject_type: str, subject_id: UUID) -> bool: ...


@dataclass(frozen=True)
class ManualReviewTask:
    id: UUID
    org_id: UUID
    request_id: UUID
    stage: str
    trace_id: str
    reason: str
    status: str
    created_at: str
    resolved_at: str | None = None
    version: int = 0


class DeletionPropagationService:
    """Reference state machine; adapters only acknowledge synthetic stages."""

    def __init__(self, *, audit_log: AuditLogService | None = None, database: str | Path = ":memory:") -> None:
        from .infrastructure.deletion_schema import initialize

        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        initialize(self._connection)
        self.requests: dict[UUID, DeletionRequest] = {
            item.id: item for item in (
                _request_from_json(json.loads(row[0])) for row in self._connection.execute(
                    "SELECT payload FROM audit_deletion_requests"
                )
            )
        }
        self.stages: dict[tuple[UUID, str], DeletionStage] = {
            (item.request_id, item.stage): item for item in (
                _stage_from_json(json.loads(row[0])) for row in self._connection.execute(
                    "SELECT payload FROM audit_deletion_stages"
                )
            )
        }
        self.manual_tasks: dict[UUID, ManualReviewTask] = {
            item.id: item for item in (
                _manual_from_json(json.loads(row[0])) for row in self._connection.execute(
                    "SELECT payload FROM audit_deletion_manual_tasks"
                )
            )
        }
        self._commands: dict[tuple[UUID, str], tuple[str, DeletionRequest]] = {
            (UUID(row[0]), row[1]): (row[2], _request_from_json(json.loads(row[3])))
            for row in self._connection.execute(
                "SELECT org_id, idempotency_key, payload_hash, response FROM audit_deletion_commands"
            )
        }
        self._audit_log = audit_log
        self._lock = RLock()

    def close(self) -> None:
        self._connection.close()

    def _persist(self, *, request: DeletionRequest | None = None, stage: DeletionStage | None = None,
                 stages: tuple[DeletionStage, ...] = (),
                 manual: ManualReviewTask | None = None,
                 command: tuple[UUID, str, str, DeletionRequest] | None = None) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            if request is not None:
                self._connection.execute(
                    "INSERT OR REPLACE INTO audit_deletion_requests VALUES (?, ?, ?)",
                    (str(request.id), str(request.org_id), _canonical(asdict(request))),
                )
            for stage in (*stages, *((stage,) if stage is not None else ())):
                self._connection.execute(
                    "INSERT OR REPLACE INTO audit_deletion_stages VALUES (?, ?, ?)",
                    (str(stage.request_id), stage.stage, _canonical(asdict(stage))),
                )
            if manual is not None:
                self._connection.execute(
                    "INSERT OR REPLACE INTO audit_deletion_manual_tasks VALUES (?, ?, ?, ?)",
                    (str(manual.id), str(manual.org_id), str(manual.request_id), _canonical(asdict(manual))),
                )
            if command is not None:
                org_id, key, digest, response = command
                self._connection.execute(
                    "INSERT INTO audit_deletion_commands VALUES (?, ?, ?, ?)",
                    (str(org_id), key, digest, _canonical(asdict(response))),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def request(
        self, *, org_id: UUID | str, subject_type: str, subject_id: UUID | str,
        requested_by: UUID | str, idempotency_key: str, trace_id: str,
        requested_at: datetime | str | None = None,
    ) -> DeletionRequest:
        tenant = _uuid(org_id, "org_id")
        key = self._key(idempotency_key)
        subject = _uuid(subject_id, "subject_id")
        actor = _uuid(requested_by, "requested_by")
        kind = _text(subject_type, "subject_type")
        command_hash = _hash({"subject_type": kind, "subject_id": str(subject), "requested_by": str(actor)})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != command_hash:
                    raise DeletionError("IDEMPOTENCY_KEY_REUSED", "deletion idempotency key payload differs")
                return prior[1]
            request = DeletionRequest(uuid4(), tenant, kind, subject, actor, "requested", _stamp(requested_at), None)
            validate_deletion_request(request.as_contract())
            stages = tuple(DeletionStage(request.id, tenant, stage, "pending", _text(trace_id, "trace_id"))
                           for stage in STAGES)
            self._persist(request=request, stages=stages, command=(tenant, key, command_hash, request))
            self.requests[request.id] = request
            for value in stages:
                self.stages[(request.id, value.stage)] = value
            self._commands[(tenant, key)] = (command_hash, request)
            self._audit("deletion.requested", tenant, trace_id, actor, request.id, key, {})
            return request

    create = request

    def process_stage(
        self, *, org_id: UUID | str, request_id: UUID | str, stage: str, success: bool,
        expected_version: int, idempotency_key: str, trace_id: str,
        error: str | None = None, evidence_ref: str | None = None,
    ) -> DeletionRequest:
        tenant = _uuid(org_id, "org_id")
        request = self._request(request_id, tenant)
        canonical = self._stage(stage)
        key = self._key(idempotency_key)
        state = self.stages[(request.id, canonical)]
        if success and not evidence_ref:
            raise DeletionError("DELETION_EVIDENCE_REQUIRED", "successful stage requires verification evidence")
        if evidence_ref and re.search(r"(?i)(?:token|secret|password|authorization)\s*[:=]", evidence_ref):
            raise DeletionError("INVALID_DELETION_EVIDENCE", "evidence reference contains a credential")
        command_hash = _hash({"request_id": str(request.id), "stage": canonical, "success": success,
                              "error": error, "evidence_ref": evidence_ref})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != command_hash:
                    raise DeletionError("IDEMPOTENCY_KEY_REUSED", "stage idempotency key payload differs")
                return prior[1]
            if request.version != expected_version:
                raise DeletionError("VERSION_CONFLICT", "deletion request version changed")
            if state.status == "completed":
                raise DeletionError("INVALID_DELETION_STATE", "stage is already completed")
            if state.status not in {"pending", "failed"}:
                raise DeletionError("INVALID_DELETION_STATE", "stage is not processable")
            now = _stamp()
            redacted_error = self._redact_error(error)
            next_stage = replace(state, status="completed" if success else "failed", confirmed_at=now,
                                 error=None if success else redacted_error, trace_id=_text(trace_id, "trace_id"),
                                 version=state.version + 1, evidence_ref=evidence_ref if success else None)
            statuses = [next_stage.status if name == canonical else self.stages[(request.id, name)].status
                        for name in STAGES]
            completed = all(value == "completed" for value in statuses)
            if completed:
                next_status = "completed"
            elif any(value == "failed" for value in statuses):
                next_status = "partially_completed" if any(value == "completed" for value in statuses) else "failed"
            else:
                next_status = "running"
            updated = replace(request, status=next_status,
                              completed_at=now if completed else None,
                              version=request.version + 1)
            manual = self._new_manual(tenant, request.id, canonical, _text(trace_id, "trace_id"),
                                      redacted_error or "stage failed") if not success else None
            self._persist(request=updated, stage=next_stage,
                          manual=manual,
                          command=(tenant, key, command_hash, updated))
            self.stages[(request.id, canonical)] = next_stage
            self.requests[request.id] = updated
            if manual is not None:
                self.manual_tasks[manual.id] = manual
            self._commands[(tenant, key)] = (command_hash, updated)
            self._audit("deletion.stage.confirmed", tenant, trace_id, updated.requested_by, request.id, key,
                        {"stage": canonical, "success": success, "error": redacted_error,
                         "evidence_ref": evidence_ref if success else None})
            return updated

    confirm_stage = process_stage

    def process_all(
        self, *, org_id: UUID | str, request_id: UUID | str, outcomes: Mapping[str, bool],
        expected_version: int, idempotency_key: str, trace_id: str,
    ) -> DeletionRequest:
        tenant = _uuid(org_id, "org_id")
        request = self._request(request_id, tenant)
        normalized: dict[str, bool] = {}
        for stage_name, success in outcomes.items():
            canonical = self._stage(stage_name)
            if canonical in normalized or type(success) is not bool:
                raise DeletionError("INVALID_DELETION_COMMAND", "stages must have unique boolean outcomes")
            normalized[canonical] = success
        if set(normalized) != set(STAGES):
            raise DeletionError("INVALID_DELETION_COMMAND", "all deletion stages must be acknowledged")
        key = self._key(idempotency_key)
        command_hash = _hash({"request_id": str(request.id), "outcomes": normalized})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != command_hash:
                    raise DeletionError("IDEMPOTENCY_KEY_REUSED", "propagation idempotency key payload differs")
                return prior[1]
            if request.version != expected_version:
                raise DeletionError("VERSION_CONFLICT", "deletion request version changed")
            current = request
            for index, canonical in enumerate(STAGES):
                current = self.process_stage(org_id=tenant, request_id=current.id, stage=canonical,
                    success=normalized[canonical], expected_version=current.version,
                    idempotency_key=f"{key}:{index}", trace_id=trace_id,
                    evidence_ref=f"synthetic://{current.id}/{canonical}" if normalized[canonical] else None)
            self._persist(command=(tenant, key, command_hash, current))
            self._commands[(tenant, key)] = (command_hash, current)
            return current

    def resolve_manual_task(
        self, *, org_id: UUID | str, task_id: UUID | str, success: bool,
        expected_version: int, idempotency_key: str, trace_id: str,
    ) -> DeletionRequest:
        tenant = _uuid(org_id, "org_id")
        task = self.manual_tasks.get(_uuid(task_id, "task_id"))
        if task is None or task.org_id != tenant:
            raise DeletionError("TENANT_SCOPE_VIOLATION", "manual review task does not belong to organization")
        if task.version != expected_version:
            raise DeletionError("VERSION_CONFLICT", "manual review task version changed")
        request = self._request(task.request_id, tenant)
        if task.status != "queued":
            raise DeletionError("INVALID_DELETION_STATE", "manual review task is not queued")
        updated_request = self.process_stage(org_id=tenant, request_id=request.id, stage=task.stage, success=success,
            expected_version=request.version, idempotency_key=idempotency_key, trace_id=trace_id,
            error=None if success else task.reason,
            evidence_ref=f"manual://{task.id}" if success else None)
        updated_task = replace(task, status="resolved" if success else "queued", resolved_at=_stamp() if success else None,
                               version=task.version + 1)
        self._persist(manual=updated_task)
        self.manual_tasks[task.id] = updated_task
        return updated_request

    def propagate(
        self, *, org_id: UUID | str, request_id: UUID | str, targets: Mapping[str, DeletionTarget],
        idempotency_key: str, trace_id: str,
    ) -> DeletionRequest:
        """Run each target once and confirm only after an independent absence check."""
        tenant = _uuid(org_id, "org_id")
        request = self._request(request_id, tenant)
        key = self._key(idempotency_key)
        if set(targets) != set(STAGES):
            raise DeletionError("INVALID_DELETION_COMMAND", "all five deletion targets are required")
        for stage in STAGES:
            if self.stages[(request.id, stage)].status == "completed":
                continue
            adapter = targets[stage]
            try:
                evidence_ref = _text(adapter.delete(org_id=tenant, subject_type=request.subject_type,
                    subject_id=request.subject_id), "evidence_ref")
                if not adapter.absent(org_id=tenant, subject_type=request.subject_type,
                                      subject_id=request.subject_id):
                    raise DeletionError("DELETION_NOT_VERIFIED", f"{stage} still contains the subject")
            except Exception as exc:
                request = self.process_stage(org_id=tenant, request_id=request.id, stage=stage, success=False,
                    expected_version=request.version, idempotency_key=f"{key}:{stage}",
                    trace_id=trace_id, error=str(exc))
            else:
                request = self.process_stage(org_id=tenant, request_id=request.id, stage=stage, success=True,
                    expected_version=request.version, idempotency_key=f"{key}:{stage}",
                    trace_id=trace_id, evidence_ref=evidence_ref)
        return request

    def _status_after_stage(self, request_id: UUID, success: bool) -> str:
        statuses = [self.stages[(request_id, stage)].status for stage in STAGES]
        if all(status == "completed" for status in statuses):
            return "completed"
        if any(status == "failed" for status in statuses):
            return "partially_completed" if any(status == "completed" for status in statuses) else "failed"
        return "running"

    def _all_complete(self, request_id: UUID) -> bool:
        return all(self.stages[(request_id, stage)].status == "completed" for stage in STAGES)

    def _new_manual(self, tenant: UUID, request_id: UUID, stage: str, trace_id: str,
                    reason: str) -> ManualReviewTask | None:
        if any(task.request_id == request_id and task.stage == stage and task.status == "queued" for task in self.manual_tasks.values()):
            return None
        return ManualReviewTask(uuid4(), tenant, request_id, stage, trace_id, reason[:512], "queued", _stamp())

    def _request(self, value: UUID | str, tenant: UUID) -> DeletionRequest:
        request = self.requests.get(_uuid(value, "request_id"))
        if request is None or request.org_id != tenant:
            raise DeletionError("TENANT_SCOPE_VIOLATION", "deletion request does not belong to organization")
        return request

    @staticmethod
    def _stage(value: str) -> str:
        canonical = STAGE_ALIASES.get(_text(value, "stage"), value)
        if canonical not in STAGES:
            raise DeletionError("INVALID_DELETION_STAGE", f"unsupported deletion stage: {value}")
        return canonical

    @staticmethod
    def _key(value: str) -> str:
        return _text(value, "idempotency_key")

    @staticmethod
    def _redact_error(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(str(value).replace("\n", " ").split())
        normalized = re.sub(r"(?i)\b(?:token|secret|password|authorization)\s*[:=]\s*[^\s,;]+", "[REDACTED]", normalized)
        return normalized[:512] or "stage failed"

    def _audit(self, action: str, org_id: UUID, trace_id: str, actor_id: UUID, subject_id: UUID, key: str, payload: Mapping[str, Any]) -> None:
        if self._audit_log is not None:
            self._audit_log.record(org_id=org_id, trace_id=trace_id, actor_type="service", actor_id=actor_id,
                                   action=action, subject_type="deletion_request", subject_id=subject_id,
                                   input_payload=payload, idempotency_key=f"deletion:{key}")


__all__ = ["DeletionError", "DeletionPropagationService", "DeletionRequest", "DeletionStage", "ManualReviewTask", "STAGES", "validate_deletion_request"]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _request_from_json(value: Mapping[str, Any]) -> DeletionRequest:
    return DeletionRequest(UUID(value["id"]), UUID(value["org_id"]), value["subject_type"],
        UUID(value["subject_id"]), UUID(value["requested_by"]), value["status"],
        value["requested_at"], value["completed_at"], value["version"])


def _stage_from_json(value: Mapping[str, Any]) -> DeletionStage:
    return DeletionStage(UUID(value["request_id"]), UUID(value["org_id"]), value["stage"],
        value["status"], value["trace_id"], value["confirmed_at"], value["error"], value["version"],
        value.get("evidence_ref"))


def _manual_from_json(value: Mapping[str, Any]) -> ManualReviewTask:
    return ManualReviewTask(UUID(value["id"]), UUID(value["org_id"]), UUID(value["request_id"]),
        value["stage"], value["trace_id"], value["reason"], value["status"],
        value["created_at"], value["resolved_at"], value["version"])
