"""Tenant-scoped Source and immutable SourceSnapshot use cases."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.source_schema import initialize


ROOT = Path(__file__).resolve().parents[2]
SOURCE_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/source.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
SNAPSHOT_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/source-snapshot.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
SOURCE_TYPES = frozenset({"url", "file", "api", "manual", "support"})
FETCH_METHODS = frozenset({"url", "file", "api", "manual", "support", "rss", "crawler", "upload"})
SNAPSHOT_STATES = frozenset({"captured", "quarantined", "usable", "expired", "revoked", "blocked"})
SOURCE_STATES = frozenset({"none", "ingested", "quarantined", "usable", "expired", "revoked", "blocked"})
TRANSITIONS = {
    "quarantine": {"captured": "quarantined"},
    "mark_usable": {"quarantined": "usable"},
    "expire": {"captured": "expired", "quarantined": "expired", "usable": "expired"},
    "revoke": {"captured": "revoked", "quarantined": "revoked", "usable": "revoked"},
    "block": {"captured": "blocked", "quarantined": "blocked", "usable": "blocked"},
}
EVENT_TYPES = {
    "quarantine": "source.snapshot.quarantined",
    "mark_usable": "source.snapshot.usable",
    "expire": "source.snapshot.expired",
    "revoke": "source.snapshot.revoked",
    "block": "source.snapshot.blocked",
}
SOURCE_EVENT_TYPES = {
    "quarantined": "source.quarantined",
    "usable": "source.usable",
    "expired": "source.expired",
    "revoked": "source.revoked",
    "blocked": "source.blocked",
}


class SourceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise SourceError("INVALID_SOURCE_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise SourceError("INVALID_SOURCE_COMMAND", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _utc(value: str | None, name: str, *, default_now: bool = True) -> str:
    if value is None and default_now:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if not isinstance(value, str):
        raise SourceError("INVALID_SOURCE_TIMESTAMP", f"{name} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceError("INVALID_SOURCE_TIMESTAMP", f"{name} must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SourceError("INVALID_SOURCE_TIMESTAMP", f"{name} must use UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SourceError("INVALID_SOURCE_CONTENT", "content must be finite JSON or bytes") from exc


def _content_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    return _canonical(content).encode("utf-8")


def _digest(value: Any) -> str:
    if isinstance(value, bytes):
        return sha256(value).hexdigest()
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SourceError("INVALID_SOURCE_CONFIDENCE", "confidence must be a number between 0 and 1")
    result = float(value)
    if result != result or result < 0 or result > 1:
        raise SourceError("INVALID_SOURCE_CONFIDENCE", "confidence must be a number between 0 and 1")
    return result


def _private_ref(value: str | None, content_hash: str) -> str:
    if value is None or not value.strip():
        return f"private://source-snapshots/{content_hash}"
    ref = _text(value, "storage_object_ref", 4096)
    if not ref.startswith("private://"):
        raise SourceError("INVALID_STORAGE_REFERENCE", "storage_object_ref must use private://")
    return ref


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


class SourceService:
    """Atomic Source ingest, snapshot state transitions, and audit events."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        initialize(self._connection)
        self._lock = RLock()

    def close(self) -> None:
        self._connection.close()

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM source_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise SourceError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str,
                      response: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO source_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def _event(self, *, tenant: str, aggregate_type: str, aggregate_id: str, event_type: str,
               actor: str, trace: str, key: str, version: int, payload: dict[str, Any]) -> dict[str, Any]:
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM source_events "
            "WHERE org_id = ? AND aggregate_type = ? AND aggregate_id = ?",
            (tenant, aggregate_type, aggregate_id),
        ).fetchone()[0]
        event_id = str(uuid4())
        envelope = {
            "event_id": event_id, "event_type": event_type, "event_schema_version": 1,
            "occurred_at": _utc(None, "occurred_at"), "org_id": tenant, "trace_id": trace,
            "correlation_id": None, "causation_id": None, "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id, "aggregate_version": version, "actor_type": "user",
            "actor_id": actor, "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload),
        }
        self._connection.execute(
            "INSERT INTO source_events (event_id, org_id, aggregate_type, aggregate_id, event_type, sequence, envelope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, tenant, aggregate_type, aggregate_id, event_type, sequence,
             json.dumps(envelope, ensure_ascii=False, sort_keys=True)),
        )
        return envelope

    def _snapshot_event(self, *, tenant: str, snapshot_id: str, event_type: str,
                        actor: str, trace: str, key: str, version: int, payload: dict[str, Any]) -> dict[str, Any]:
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM source_snapshot_state_events "
            "WHERE org_id = ? AND snapshot_id = ?", (tenant, snapshot_id)
        ).fetchone()[0]
        event_id = str(uuid4())
        envelope = {
            "event_id": event_id, "event_type": event_type, "event_schema_version": 1,
            "occurred_at": _utc(None, "occurred_at"), "org_id": tenant, "trace_id": trace,
            "correlation_id": None, "causation_id": None, "aggregate_type": "SourceSnapshot",
            "aggregate_id": snapshot_id, "aggregate_version": version, "actor_type": "user",
            "actor_id": actor, "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload),
        }
        self._connection.execute(
            "INSERT INTO source_snapshot_state_events "
            "(event_id, org_id, snapshot_id, event_type, sequence, envelope) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, tenant, snapshot_id, event_type, sequence, json.dumps(envelope, sort_keys=True)),
        )
        return envelope

    def _validate_source(self, source: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(source)
        errors = sorted(SOURCE_VALIDATOR.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            raise SourceError("INVALID_SOURCE", errors[0].message)
        return result

    def _validate_snapshot(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(snapshot)
        errors = sorted(SNAPSHOT_VALIDATOR.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            raise SourceError("INVALID_SOURCE_SNAPSHOT", errors[0].message)
        return result

    def ingest(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        source_type: str, canonical_url: str | None = None, content: Any = None,
        storage_object_ref: str | None = None, terms_snapshot_ref: str | None = None,
        confidence: float = 0.5, fetch_method: str | None = None,
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if source_type not in SOURCE_TYPES:
            raise SourceError("INVALID_SOURCE_TYPE", "source_type is invalid")
        method = fetch_method or source_type
        if method not in FETCH_METHODS:
            raise SourceError("INVALID_FETCH_METHOD", "fetch_method is invalid")
        url = None if canonical_url is None else _text(canonical_url, "canonical_url", 4096)
        if source_type == "url" and url is None:
            raise SourceError("SOURCE_URL_REQUIRED", "url sources require canonical_url")
        score = _confidence(confidence)
        captured = _utc(captured_at, "captured_at")
        # A generated capture time is output metadata, not caller input.  Do
        # not put it in the idempotency digest or identical retries would be
        # treated as a different command a few microseconds later.
        captured_digest = captured if captured_at is not None else None
        raw = b"" if content is None else _content_bytes(content)
        content_hash = _digest(raw)
        storage_ref = _private_ref(storage_object_ref, content_hash)
        terms = None if terms_snapshot_ref is None else _text(terms_snapshot_ref, "terms_snapshot_ref", 2048)
        digest = _hash({"source_type": source_type, "canonical_url": url, "content_hash": content_hash,
                        "storage_object_ref": storage_ref, "terms_snapshot_ref": terms,
                        "confidence": score, "fetch_method": method, "captured_at": captured_digest})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                if url is not None and self._connection.execute(
                    "SELECT id FROM sources WHERE org_id = ? AND canonical_url = ?", (tenant, url)
                ).fetchone() is not None:
                    raise SourceError("SOURCE_ALREADY_EXISTS", "canonical source already exists")
                source_id, snapshot_id = str(uuid4()), str(uuid4())
                now = _utc(None, "created_at")
                source = self._validate_source({
                    "id": source_id, "org_id": tenant, "source_type": source_type,
                    "fetch_method": method, "canonical_url": url, "status": "ingested",
                    "current_snapshot_id": snapshot_id, "confidence": score, "created_at": now,
                })
                snapshot = self._validate_snapshot({
                    "id": snapshot_id, "org_id": tenant, "source_id": source_id,
                    "captured_at": captured, "content_hash": content_hash,
                    "storage_object_ref": storage_ref, "terms_snapshot_ref": terms,
                    "confidence": score, "status": "captured", "created_at": now,
                })
                self._connection.execute(
                    "INSERT INTO sources (id, org_id, source_type, fetch_method, canonical_url, status, "
                    "current_snapshot_id, confidence, version, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, tenant, source_type, method, url, "ingested", snapshot_id, score, 1, now,
                     json.dumps(source, ensure_ascii=False, sort_keys=True)),
                )
                self._connection.execute(
                    "INSERT INTO source_snapshots (id, org_id, source_id, captured_at, content_hash, "
                    "storage_object_ref, terms_snapshot_ref, confidence, status, version, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (snapshot_id, tenant, source_id, captured, content_hash, storage_ref, terms, score,
                     "captured", 0, now, json.dumps(snapshot, ensure_ascii=False, sort_keys=True)),
                )
                event = self._event(
                    tenant=tenant, aggregate_type="Source", aggregate_id=source_id,
                    event_type="source.ingested", actor=actor, trace=trace, key=key,
                    version=1, payload={"aggregate_id": source_id, "aggregate_version": 1,
                                       "snapshot_id": snapshot_id, "content_hash": content_hash,
                                       "from_state": "none", "to_state": "ingested", "command": "ingest"},
                )
                response = {"source": source, "snapshot": snapshot, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise SourceError("SOURCE_ALREADY_EXISTS", "source identity conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    # Common aliases used by callers that name the command explicitly.
    create = ingest
    ingest_source = ingest

    def create_snapshot(
        self, *, org_id: UUID | str, source_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, content: Any = None,
        storage_object_ref: str | None = None, terms_snapshot_ref: str | None = None,
        confidence: float = 0.5, captured_at: str | None = None,
    ) -> dict[str, Any]:
        tenant, source_identity, actor = _uuid(org_id, "org_id"), _uuid(source_id, "source_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        score = _confidence(confidence)
        captured = _utc(captured_at, "captured_at")
        captured_digest = captured if captured_at is not None else None
        raw = b"" if content is None else _content_bytes(content)
        content_hash = _digest(raw)
        storage_ref = _private_ref(storage_object_ref, content_hash)
        terms = None if terms_snapshot_ref is None else _text(terms_snapshot_ref, "terms_snapshot_ref", 2048)
        digest = _hash({"operation": "create_snapshot", "source_id": source_identity,
                        "content_hash": content_hash, "storage_object_ref": storage_ref,
                        "terms_snapshot_ref": terms, "confidence": score, "captured_at": captured_digest})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._connection.execute(
                    "SELECT payload, status, version FROM sources WHERE org_id = ? AND id = ?",
                    (tenant, source_identity),
                ).fetchone()
                if row is None:
                    raise SourceError("TENANT_SCOPE_VIOLATION", "source is not in this organization")
                if row["status"] in {"revoked", "blocked"}:
                    raise SourceError("SOURCE_NOT_WRITABLE", "revoked or blocked source cannot receive snapshots")
                source = json.loads(row["payload"])
                snapshot_id = str(uuid4())
                now = _utc(None, "created_at")
                snapshot = self._validate_snapshot({
                    "id": snapshot_id, "org_id": tenant, "source_id": source_identity,
                    "captured_at": captured, "content_hash": content_hash,
                    "storage_object_ref": storage_ref, "terms_snapshot_ref": terms,
                    "confidence": score, "status": "captured", "created_at": now,
                })
                version = int(row["version"]) + 1
                self._connection.execute(
                    "INSERT INTO source_snapshots (id, org_id, source_id, captured_at, content_hash, "
                    "storage_object_ref, terms_snapshot_ref, confidence, status, version, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (snapshot_id, tenant, source_identity, captured, content_hash, storage_ref, terms, score,
                     "captured", 0, now, json.dumps(snapshot, ensure_ascii=False, sort_keys=True)),
                )
                source.update(current_snapshot_id=snapshot_id, status="ingested", confidence=score)
                self._connection.execute(
                    "UPDATE sources SET current_snapshot_id = ?, status = 'ingested', confidence = ?, "
                    "version = ?, payload = ? WHERE org_id = ? AND id = ? AND version = ?",
                    (snapshot_id, score, version, json.dumps(source, ensure_ascii=False, sort_keys=True),
                     tenant, source_identity, version - 1),
                )
                response = {"source": source, "snapshot": snapshot}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def transition_snapshot(
        self, *, org_id: UUID | str, snapshot_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, action: str, expected_version: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        tenant, identity, actor = _uuid(org_id, "org_id"), _uuid(snapshot_id, "snapshot_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if action not in TRANSITIONS:
            raise SourceError("INVALID_SOURCE_ACTION", "unsupported snapshot action")
        if type(expected_version) is not int or expected_version < 0:
            raise SourceError("VERSION_CONFLICT", "expected_version must be nonnegative")
        normalized_reason = None if reason is None else _text(reason, "reason", 2048)
        if action in {"expire", "revoke", "block"} and normalized_reason is None:
            raise SourceError("REASON_REQUIRED", "this snapshot action requires a reason")
        digest = _hash({"operation": "transition_snapshot", "snapshot_id": identity, "action": action,
                        "expected_version": expected_version, "reason": normalized_reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._connection.execute(
                    "SELECT payload, source_id, status, version FROM source_snapshots WHERE org_id = ? AND id = ?",
                    (tenant, identity),
                ).fetchone()
                if row is None:
                    raise SourceError("TENANT_SCOPE_VIOLATION", "snapshot is not in this organization")
                if row["version"] != expected_version:
                    raise SourceError("VERSION_CONFLICT", "snapshot version changed")
                current = row["status"]
                target = TRANSITIONS[action].get(current)
                if target is None:
                    raise SourceError("INVALID_SOURCE_STATE", f"cannot {action} from {current}")
                snapshot = json.loads(row["payload"])
                snapshot["status"] = target
                next_version = expected_version + 1
                SNAPSHOT_VALIDATOR.validate(snapshot)
                updated = self._connection.execute(
                    "UPDATE source_snapshots SET status = ?, version = ?, payload = ? "
                    "WHERE org_id = ? AND id = ? AND version = ?",
                    (target, next_version, json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                     tenant, identity, expected_version),
                )
                if updated.rowcount != 1:
                    raise SourceError("VERSION_CONFLICT", "snapshot changed while transitioning")
                payload = {"aggregate_id": identity, "aggregate_version": next_version,
                           "from_state": current, "to_state": target, "command": action,
                           "reason": normalized_reason, "snapshot_hash": snapshot["content_hash"]}
                snapshot_event = self._snapshot_event(
                    tenant=tenant, snapshot_id=identity, event_type=EVENT_TYPES[action], actor=actor,
                    trace=trace, key=key, version=next_version, payload=payload,
                )
                source_row = self._connection.execute(
                    "SELECT payload, status, version FROM sources WHERE org_id = ? AND id = ?",
                    (tenant, row["source_id"]),
                ).fetchone()
                if source_row is None:
                    raise SourceError("SOURCE_NOT_FOUND", "parent source is missing")
                source = json.loads(source_row["payload"])
                source_event = None
                source_target = target if target in SOURCE_EVENT_TYPES else source_row["status"]
                if source_target != source_row["status"] and source_target in SOURCE_STATES:
                    source["status"] = source_target
                    source["current_snapshot_id"] = identity
                    source_version = int(source_row["version"]) + 1
                    self._connection.execute(
                        "UPDATE sources SET status = ?, current_snapshot_id = ?, version = ?, payload = ? "
                        "WHERE org_id = ? AND id = ? AND version = ?",
                        (source_target, identity, source_version, json.dumps(source, ensure_ascii=False, sort_keys=True),
                         tenant, row["source_id"], source_version - 1),
                    )
                    source_event = self._event(
                        tenant=tenant, aggregate_type="Source", aggregate_id=row["source_id"],
                        event_type=SOURCE_EVENT_TYPES[source_target], actor=actor, trace=trace,
                        key=key + ":source", version=source_version,
                        payload={"aggregate_id": row["source_id"], "aggregate_version": source_version,
                                 "from_state": source_row["status"], "to_state": source_target,
                                 "command": action, "reason": normalized_reason,
                                 "snapshot_id": identity, "snapshot_hash": snapshot["content_hash"]},
                    )
                response = {"snapshot": snapshot, "source": source, "event": snapshot_event,
                            "source_event": source_event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    transition = transition_snapshot

    def verify_snapshot(self, *, org_id: UUID | str, snapshot_id: UUID | str,
                        content: Any, actor_id: UUID | str, trace_id: str,
                        idempotency_key: str) -> dict[str, Any]:
        tenant, identity, actor = _uuid(org_id, "org_id"), _uuid(snapshot_id, "snapshot_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        supplied_hash = _digest(_content_bytes(content))
        digest = _hash({"operation": "verify_snapshot", "snapshot_id": identity, "content_hash": supplied_hash})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                snapshot = self.get_snapshot(org_id=tenant, snapshot_id=identity)
                report = {"snapshot_id": identity, "org_id": tenant,
                          "expected_hash": snapshot["content_hash"], "actual_hash": supplied_hash,
                          "verified": snapshot["content_hash"].lower() == supplied_hash.lower(),
                          "actor_id": actor, "trace_id": trace}
                self._save_command(tenant, key, digest, actor, trace, report)
                self._connection.commit()
                return report
            except Exception:
                self._connection.rollback()
                raise

    def get_source(self, *, org_id: UUID | str, source_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(source_id, "source_id")
        row = self._connection.execute(
            "SELECT payload FROM sources WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise SourceError("TENANT_SCOPE_VIOLATION", "source is not in this organization")
        return json.loads(row["payload"])

    def get_snapshot(self, *, org_id: UUID | str, snapshot_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(snapshot_id, "snapshot_id")
        row = self._connection.execute(
            "SELECT payload FROM source_snapshots WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise SourceError("TENANT_SCOPE_VIOLATION", "snapshot is not in this organization")
        return json.loads(row["payload"])

    def list_sources(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT payload FROM sources WHERE org_id = ? ORDER BY id", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def list_snapshots(self, *, org_id: UUID | str, source_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        if source_id is None:
            rows = self._connection.execute(
                "SELECT payload FROM source_snapshots WHERE org_id = ? ORDER BY id", (tenant,)
            ).fetchall()
        else:
            identity = _uuid(source_id, "source_id")
            rows = self._connection.execute(
                "SELECT payload FROM source_snapshots WHERE org_id = ? AND source_id = ? ORDER BY version, id",
                (tenant, identity),
            ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def events(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT envelope FROM source_events WHERE org_id = ? ORDER BY event_id", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)

    def snapshot_events(self, *, org_id: UUID | str, snapshot_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        if snapshot_id is None:
            rows = self._connection.execute(
                "SELECT envelope FROM source_snapshot_state_events WHERE org_id = ? ORDER BY snapshot_id, sequence",
                (tenant,),
            ).fetchall()
        else:
            identity = _uuid(snapshot_id, "snapshot_id")
            rows = self._connection.execute(
                "SELECT envelope FROM source_snapshot_state_events WHERE org_id = ? AND snapshot_id = ? ORDER BY sequence",
                (tenant, identity),
            ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


ProvenanceService = SourceService

__all__ = ["SourceError", "SourceService", "ProvenanceService"]
