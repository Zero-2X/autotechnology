"""Dependency-free append-only audit log with trace and evidence correlation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "packages" / "contracts" / "jsonschema" / "audit-log.schema.json"


class AuditError(ValueError):
    """Stable error raised by audit commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str | None, name: str, *, required: bool = True) -> UUID | None:
    if value is None:
        if required:
            raise AuditError("INVALID_AUDIT_RECORD", f"{name} is required")
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AuditError("INVALID_AUDIT_RECORD", f"{name} must be a UUID") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditError("INVALID_AUDIT_RECORD", f"{name} is required")
    return value.strip()


def _stamp(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise AuditError("INVALID_AUDIT_RECORD", "created_at must include a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return _text(value, "created_at")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AuditError("INVALID_AUDIT_RECORD", "payload must be finite JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _input_hash(input_hash: str | None, input_payload: Any) -> str | None:
    calculated = _hash(input_payload) if input_payload is not None else None
    if input_hash is not None:
        normalized = _text(input_hash, "input_hash").lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise AuditError("INVALID_AUDIT_RECORD", "input_hash must be a SHA-256 hex digest")
        if calculated is not None and normalized != calculated:
            raise AuditError("INPUT_HASH_MISMATCH", "input_hash does not match input_payload")
        return normalized
    return calculated


def validate_audit_log(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a copy of the public audit-log contract."""

    candidate = dict(value)
    errors = sorted(Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()).iter_errors(candidate), key=lambda item: list(item.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "audit_log"
        raise AuditError("INVALID_AUDIT_RECORD", f"{location}: {errors[0].message}")
    return candidate


@dataclass(frozen=True)
class AuditLogEntry:
    id: UUID
    org_id: UUID
    trace_id: str
    actor_type: str
    actor_id: UUID | None
    action: str
    subject_type: str
    subject_id: UUID | None
    input_hash: str | None
    result: str
    reason: str | None
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "trace_id": self.trace_id,
            "actor_type": self.actor_type,
            "actor_id": str(self.actor_id) if self.actor_id else None,
            "action": self.action,
            "subject_type": self.subject_type,
            "subject_id": str(self.subject_id) if self.subject_id else None,
            "input_hash": self.input_hash,
            "result": self.result,
            "reason": self.reason,
            "created_at": self.created_at,
        }

    @classmethod
    def create(
        cls,
        *,
        org_id: UUID | str,
        trace_id: str,
        actor_type: str,
        actor_id: UUID | str | None,
        action: str,
        subject_type: str,
        subject_id: UUID | str | None,
        result: str,
        reason: str | None = None,
        input_hash: str | None = None,
        input_payload: Any = None,
        id: UUID | str | None = None,
        created_at: datetime | str | None = None,
    ) -> "AuditLogEntry":
        entry = cls(
            id=_uuid(id, "id", required=False) or uuid4(),
            org_id=_uuid(org_id, "org_id"),  # type: ignore[arg-type]
            trace_id=_text(trace_id, "trace_id"),
            actor_type=_text(actor_type, "actor_type"),
            actor_id=_uuid(actor_id, "actor_id", required=False),
            action=_text(action, "action"),
            subject_type=_text(subject_type, "subject_type"),
            subject_id=_uuid(subject_id, "subject_id", required=False),
            input_hash=_input_hash(input_hash, input_payload),
            result=_text(result, "result"),
            reason=_redact(reason) if reason else None,
            created_at=_stamp(created_at),
        )
        validate_audit_log(entry.as_contract())
        return entry


@dataclass(frozen=True)
class MetricSample:
    name: str
    value: int
    recorded_at: str
    labels: tuple[tuple[str, str], ...] = ()

    def as_contract(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "recorded_at": self.recorded_at,
            "labels": dict(self.labels),
        }


@dataclass(frozen=True)
class EvidencePackage:
    id: UUID
    org_id: UUID
    trace_id: str
    record_ids: tuple[UUID, ...]
    evidence_refs: tuple[tuple[str, str], ...]
    content_hash: str
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "trace_id": self.trace_id,
            "record_ids": [str(item) for item in self.record_ids],
            "evidence_refs": dict(self.evidence_refs),
            "content_hash": self.content_hash,
            "created_at": self.created_at,
        }


class AuditLogService:
    """SQLite-backed append-only audit log; pass a file path for durable records.

    The default private in-memory database is for offline fixtures. Production
    deployment must supply durable storage and enforce authenticated tenant context.
    """

    def __init__(self, database: str | Path = ":memory:") -> None:
        from .infrastructure.audit_schema import initialize

        self._connection = sqlite3.connect(str(database), check_same_thread=False)
        initialize(self._connection)
        self._lock = RLock()
        self._failures = 0

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    @property
    def entries(self) -> tuple[AuditLogEntry, ...]:
        """Local fixture diagnostics; public reads use the audited query/get APIs."""
        with self._lock:
            return tuple(_entry(json.loads(row[0])) for row in self._connection.execute(
                "SELECT payload FROM audit_logs ORDER BY rowid"))

    @property
    def records(self) -> tuple[AuditLogEntry, ...]:
        return self.entries

    @property
    def metrics(self) -> dict[str, int]:
        with self._lock:
            counts = dict(self._connection.execute("SELECT action, COUNT(*) FROM audit_logs GROUP BY action"))
            return {"audit_records_total": sum(counts.values()), "audit_queries_total": counts.get("audit.query", 0),
                    "audit_exports_total": counts.get("audit.export", 0), "audit_failures_total": self._failures}

    def metric(self, name: str) -> int:
        return self.metrics.get(_text(name, "name"), 0)

    def metric_samples(self) -> tuple[MetricSample, ...]:
        return tuple(MetricSample(name, value, _stamp(None)) for name, value in sorted(self.metrics.items()))

    def _prior(self, tenant: UUID, key: str, payload_hash: str):
        row = self._connection.execute(
            "SELECT payload_hash, response FROM audit_commands WHERE org_id = ? AND idempotency_key = ?",
            (str(tenant), key)).fetchone()
        if row is None:
            return None
        if row[0] != payload_hash:
            self._failures += 1
            raise AuditError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
        return json.loads(row[1])

    def _save(self, tenant: UUID, key: str, payload_hash: str, response: Any, entry: AuditLogEntry) -> None:
        self._connection.execute(
            "INSERT INTO audit_logs (id, org_id, trace_id, action, payload) VALUES (?, ?, ?, ?, ?)",
            (str(entry.id), str(tenant), entry.trace_id, entry.action, _canonical(entry.as_contract())))
        self._connection.execute(
            "INSERT INTO audit_commands (org_id, idempotency_key, payload_hash, response) VALUES (?, ?, ?, ?)",
            (str(tenant), key, payload_hash, _canonical(response)))

    def record(self, *, org_id: UUID | str, trace_id: str, actor_type: str, actor_id: UUID | str | None,
               action: str, subject_type: str, subject_id: UUID | str | None = None, result: str = "success",
               reason: str | None = None, input_hash: str | None = None, input_payload: Any = None,
               idempotency_key: str, created_at: datetime | str | None = None) -> AuditLogEntry:
        key = _text(idempotency_key, "idempotency_key")
        candidate = AuditLogEntry.create(org_id=org_id, trace_id=trace_id, actor_type=actor_type,
            actor_id=actor_id, action=action, subject_type=subject_type, subject_id=subject_id, result=result,
            reason=reason, input_hash=input_hash, input_payload=input_payload, created_at=created_at)
        spec = candidate.as_contract()
        for field in ("id", "created_at", "trace_id"):
            spec.pop(field)
        digest = _hash({"operation": "record", **spec})
        with self._transaction():
            prior = self._prior(candidate.org_id, key, digest)
            if prior is not None:
                return _entry(prior)
            self._save(candidate.org_id, key, digest, candidate.as_contract(), candidate)
            return candidate

    def query(self, *, org_id: UUID | str, trace_id: str, idempotency_key: str, actor_type: str = "system",
              actor_id: UUID | str | None = None, trace_filter: str | None = None, action: str | None = None,
              subject_type: str | None = None, subject_id: UUID | str | None = None, result: str | None = None,
              limit: int = 100, entry_id: UUID | str | None = None) -> tuple[AuditLogEntry, ...]:
        tenant = _uuid(org_id, "org_id")
        key = _text(idempotency_key, "idempotency_key")
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise AuditError("INVALID_AUDIT_QUERY", "limit must be between 1 and 10000")
        subject = _uuid(subject_id, "subject_id", required=False)
        identifier = _uuid(entry_id, "entry_id", required=False)
        spec = {"trace": trace_filter, "action": action, "subject_type": subject_type,
                "subject_id": str(subject) if subject else None, "result": result, "limit": limit,
                "entry_id": str(identifier) if identifier else None}
        audit = AuditLogEntry.create(org_id=tenant, trace_id=trace_id, actor_type=actor_type, actor_id=actor_id,
            action="audit.query", subject_type="audit_log", subject_id=identifier, result="success", input_payload=spec)
        digest = _hash({"operation": "query", **spec, "actor_type": actor_type, "actor_id": str(audit.actor_id)})
        with self._transaction():
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return tuple(_entry(item) for item in prior)
            rows = self._connection.execute("SELECT payload FROM audit_logs WHERE org_id = ? ORDER BY rowid", (str(tenant),))
            selected = []
            for row in rows:
                item = _entry(json.loads(row[0]))
                if ((trace_filter is None or item.trace_id == trace_filter)
                    and (action is None or item.action == action)
                    and (subject_type is None or item.subject_type == subject_type)
                    and (subject is None or item.subject_id == subject)
                    and (identifier is None or item.id == identifier)
                    and (result is None or item.result == result)):
                    selected.append(item)
                    if len(selected) == limit:
                        break
            self._save(tenant, key, digest, [item.as_contract() for item in selected], audit)
            return tuple(selected)

    def export(self, *, org_id: UUID | str, trace_id: str, idempotency_key: str,
               evidence_refs: Mapping[str, str] | None = None, actor_type: str = "system",
               actor_id: UUID | str | None = None, trace_filter: str | None = None,
               action: str | None = None, limit: int = 1000) -> EvidencePackage:
        tenant = _uuid(org_id, "org_id")
        key = _text(idempotency_key, "idempotency_key")
        refs = tuple(sorted((_text(k, "evidence_name"), _safe_ref(v)) for k, v in (evidence_refs or {}).items()))
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise AuditError("INVALID_AUDIT_EXPORT", "limit must be between 1 and 10000")
        spec = {"trace": trace_filter, "action": action, "limit": limit, "evidence_refs": dict(refs)}
        audit = AuditLogEntry.create(org_id=tenant, trace_id=trace_id, actor_type=actor_type, actor_id=actor_id,
            action="audit.export", subject_type="evidence_package", subject_id=uuid4(), result="success", input_payload=spec)
        digest = _hash({"operation": "export", **spec, "actor_type": actor_type, "actor_id": str(audit.actor_id)})
        with self._transaction():
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return _package(prior)
            selected = []
            for row in self._connection.execute("SELECT payload FROM audit_logs WHERE org_id = ? ORDER BY rowid", (str(tenant),)):
                item = json.loads(row[0])
                if (trace_filter is None or item["trace_id"] == trace_filter) and (action is None or item["action"] == action):
                    selected.append(item)
                    if len(selected) == limit:
                        break
            package = EvidencePackage(audit.subject_id, tenant, trace_id, tuple(UUID(item["id"]) for item in selected),
                refs, _hash({"org_id": str(tenant), "records": selected, "evidence_refs": dict(refs)}), audit.created_at)
            self._save(tenant, key, digest, package.as_contract(), audit)
            return package

    def get(self, *, org_id: UUID | str, entry_id: UUID | str, trace_id: str, idempotency_key: str,
            actor_type: str = "system", actor_id: UUID | str | None = None) -> AuditLogEntry:
        rows = self.query(org_id=org_id, entry_id=entry_id, trace_id=trace_id,
            idempotency_key=idempotency_key, actor_type=actor_type, actor_id=actor_id, limit=1)
        if not rows:
            with self._lock:
                row = self._connection.execute("SELECT org_id FROM audit_logs WHERE id = ?", (str(_uuid(entry_id, "entry_id")),)).fetchone()
            if row is not None and row[0] != str(_uuid(org_id, "org_id")):
                raise AuditError("TENANT_SCOPE_VIOLATION", "audit record belongs to another organization")
            raise AuditError("AUDIT_RECORD_NOT_FOUND", "audit record not found in organization")
        return rows[0]


def _entry(value: Mapping[str, Any]) -> AuditLogEntry:
    return AuditLogEntry.create(**dict(value))


def _package(value: Mapping[str, Any]) -> EvidencePackage:
    return EvidencePackage(UUID(value["id"]), UUID(value["org_id"]), value["trace_id"],
        tuple(UUID(item) for item in value["record_ids"]), tuple(sorted(value["evidence_refs"].items())),
        value["content_hash"], value["created_at"])


def _redact(value: str) -> str:
    text = _text(value, "reason")
    return re.sub(r"(?i)(?:bearer\s+[^\s,;]+|(?:token|secret|password|authorization)\s*[:=]\s*[^\s,;]+)",
                  "[REDACTED]", text)[:512]


def _safe_ref(value: str) -> str:
    from urllib.parse import urlsplit

    ref = _text(value, "evidence_ref")
    parsed = urlsplit(ref)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment or _redact(ref) != ref
        or any(ord(c) < 32 for c in ref)):
        raise AuditError("INVALID_AUDIT_EXPORT", "evidence references must not contain credentials or URL parameters")
    return ref
