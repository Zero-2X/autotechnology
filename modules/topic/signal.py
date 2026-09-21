"""Manual TopicSignal import with row-level validation and durable deduplication."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
from time import perf_counter
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.signal_schema import initialize


ROOT = Path(__file__).resolve().parents[2]
SIGNAL_SCHEMA = ROOT / "packages/contracts/jsonschema/topic-signal.schema.json"
SIGNAL_VALIDATOR = Draft202012Validator(
    json.loads(SIGNAL_SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
)
REQUIRED_FIELDS = (
    "source_type", "source_ref", "captured_at", "locale", "region", "title", "summary",
    "usage_rights_status", "terms_snapshot_ref", "license_ref", "permitted_use", "confidence",
)
SOURCE_TYPES = frozenset({"manual", "rss", "api", "import"})
RIGHTS_STATUSES = frozenset({"unknown", "verified", "restricted", "rejected"})
PERMITTED_USES = frozenset({"research", "editorial", "commercial", "none"})
POLICY_SNAPSHOT = "manual-topic-signal-import/v1"


class TopicSignalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise TopicSignalError("INVALID_TENANT_CONTEXT", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise TopicSignalError("INVALID_FIELD", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _optional_ref(value: object, name: str) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, name, 2048)


def _captured_at(value: object) -> str:
    if not isinstance(value, str):
        raise TopicSignalError("INVALID_CAPTURED_AT", "captured_at must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise TopicSignalError("INVALID_CAPTURED_AT", "captured_at must be a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TopicSignalError("INVALID_CAPTURED_AT", "captured_at must use UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _validate_row(row: object, org_id: str, actor_id: str, *, csv_mode: bool) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise TopicSignalError("INVALID_ROW", "row must be an object")
    if "org_id" in row or "created_by" in row or "dedupe_key" in row or "id" in row:
        raise TopicSignalError("TENANT_SCOPE_VIOLATION", "server-owned fields are not accepted")
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
        raise TopicSignalError("MISSING_REQUIRED_FIELD", f"missing {missing[0]}")
    extra = set(row) - set(REQUIRED_FIELDS)
    if extra:
        raise TopicSignalError("UNEXPECTED_FIELD", "row contains unknown fields")
    source_type = row["source_type"]
    if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
        raise TopicSignalError("INVALID_SOURCE_TYPE", "source_type is invalid")
    rights = row["usage_rights_status"]
    if not isinstance(rights, str) or rights not in RIGHTS_STATUSES:
        raise TopicSignalError("INVALID_USAGE_RIGHTS", "usage_rights_status is invalid")
    permitted_use = row["permitted_use"]
    if not isinstance(permitted_use, str) or permitted_use not in PERMITTED_USES:
        raise TopicSignalError("INVALID_PERMITTED_USE", "permitted_use is invalid")
    raw_confidence = row["confidence"]
    if isinstance(raw_confidence, bool):
        raise TopicSignalError("INVALID_CONFIDENCE", "confidence must be between 0 and 1")
    if not csv_mode and not isinstance(raw_confidence, (int, float)):
        raise TopicSignalError("INVALID_CONFIDENCE", "JSON confidence must be a number")
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError) as exc:
        raise TopicSignalError("INVALID_CONFIDENCE", "confidence must be between 0 and 1") from exc
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise TopicSignalError("INVALID_CONFIDENCE", "confidence must be between 0 and 1")
    source_ref = _text(row["source_ref"], "source_ref", 2048)
    captured = _captured_at(row["captured_at"])
    terms_ref = _optional_ref(row["terms_snapshot_ref"], "terms_snapshot_ref")
    license_ref = _optional_ref(row["license_ref"], "license_ref")
    if rights == "verified" and not (terms_ref or license_ref):
        raise TopicSignalError("RIGHTS_EVIDENCE_REQUIRED", "verified rights require terms or license evidence")
    result = {
        "id": str(uuid4()), "org_id": org_id, "source_type": source_type,
        "source_ref": source_ref, "captured_at": captured,
        "locale": _text(row["locale"], "locale", 64),
        "region": _text(row["region"], "region", 64),
        "title": _text(row["title"], "title", 512),
        "summary": _text(row["summary"], "summary", 8192),
        "usage_rights_status": rights, "terms_snapshot_ref": terms_ref,
        "license_ref": license_ref, "permitted_use": permitted_use,
        "confidence": confidence,
        "dedupe_key": sha256(f"{org_id}|{source_type}|{source_ref}|{captured}".encode("utf-8")).hexdigest(),
        "created_by": actor_id, "created_at": _now(),
    }
    result["normalized_question"] = " ".join(result["title"].casefold().split())
    result["snapshot_hash"] = _digest({field: result[field] for field in REQUIRED_FIELDS})
    errors = list(SIGNAL_VALIDATOR.iter_errors(result))
    if errors:
        raise TopicSignalError("INVALID_TOPIC_SIGNAL", errors[0].message)
    return result


class TopicSignalImportService:
    """A batch is atomic for storage, while validation is independent per row."""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self._connection = sqlite3.connect(str(database), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        initialize(self._connection)
        self._lock = RLock()

    def close(self) -> None:
        self._connection.close()

    def import_json(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, rows: Sequence[object],
    ) -> dict[str, Any]:
        if isinstance(rows, (str, bytes, Mapping)) or not isinstance(rows, Sequence):
            raise TopicSignalError("INVALID_BATCH", "JSON body must be an array")
        entries = [(index, row) for index, row in enumerate(rows, start=1)]
        return self._import_entries(org_id, actor_id, trace_id, idempotency_key, entries, csv_mode=False)

    def import_csv(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, content: str | bytes,
    ) -> dict[str, Any]:
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise TopicSignalError("INVALID_CSV_ENCODING", "CSV must be UTF-8") from exc
        try:
            reader = csv.DictReader(io.StringIO(content, newline=""), restkey="__extra__", strict=True)
            columns = reader.fieldnames
            if not columns or len(columns) != len(set(columns)):
                raise TopicSignalError("INVALID_CSV_HEADER", "CSV header is missing or duplicated")
            entries: list[tuple[int, object]] = []
            while True:
                line_number = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    break
                entries.append((line_number, row))
                if len(entries) > 1000:
                    raise TopicSignalError("BATCH_TOO_LARGE", "at most 1000 rows are allowed")
        except csv.Error as exc:
            raise TopicSignalError("INVALID_CSV", "CSV is malformed") from exc
        return self._import_entries(org_id, actor_id, trace_id, idempotency_key, entries, csv_mode=True)

    def _import_entries(
        self, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, entries: list[tuple[int, object]], *, csv_mode: bool,
    ) -> dict[str, Any]:
        if not entries:
            raise TopicSignalError("INVALID_BATCH", "batch must contain at least one row")
        if len(entries) > 1000:
            raise TopicSignalError("BATCH_TOO_LARGE", "at most 1000 rows are allowed")
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        digest = _digest(entries)
        started = perf_counter()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._connection.execute(
                    "SELECT payload_hash, response FROM topic_signal_imports WHERE org_id = ? AND idempotency_key = ?",
                    (tenant, key),
                ).fetchone()
                if prior is not None:
                    if prior["payload_hash"] != digest:
                        raise TopicSignalError("IDEMPOTENCY_KEY_REUSED", "batch payload differs from prior import")
                    self._connection.commit()
                    return json.loads(prior["response"])
                results: list[dict[str, Any]] = []
                for line_number, raw_row in entries:
                    try:
                        signal = _validate_row(raw_row, tenant, actor, csv_mode=csv_mode)
                    except TopicSignalError as exc:
                        event_id = str(uuid4())
                        payload = {"aggregate_id": event_id, "aggregate_version": 1,
                                   "line_number": line_number, "reason_code": exc.code,
                                   "input_hash": _digest(raw_row)}
                        envelope = {
                            "event_id": event_id, "event_type": "topic_signal.rejected",
                            "event_schema_version": 1, "occurred_at": _now(), "org_id": tenant,
                            "trace_id": trace, "correlation_id": None, "causation_id": None,
                            "aggregate_type": "TopicSignalImportRow", "aggregate_id": event_id,
                            "aggregate_version": 1, "actor_type": "user", "actor_id": actor,
                            "idempotency_key": f"{key}:row:{line_number}",
                            "payload": payload, "payload_hash": _digest(payload),
                        }
                        self._connection.execute(
                            "INSERT INTO topic_signal_events (event_id, event_type, org_id, idempotency_key, envelope) "
                            "VALUES (?, ?, ?, ?, ?)",
                            (event_id, "topic_signal.rejected", tenant, key,
                             json.dumps(envelope, ensure_ascii=False, sort_keys=True)),
                        )
                        results.append({"line_number": line_number, "status": "rejected", "signal_id": None,
                                        "error_code": exc.code, "event_id": event_id})
                        continue
                    prior_signal = self._connection.execute(
                        "SELECT id FROM topic_signals WHERE org_id = ? AND dedupe_key = ?",
                        (tenant, signal["dedupe_key"]),
                    ).fetchone()
                    if prior_signal is not None:
                        results.append({"line_number": line_number, "status": "duplicate",
                                        "signal_id": prior_signal["id"], "error_code": None, "event_id": None})
                        continue
                    self._connection.execute(
                        "INSERT INTO topic_signals (id, org_id, dedupe_key, usage_rights_status, permitted_use, "
                        "terms_snapshot_ref, license_ref, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (signal["id"], tenant, signal["dedupe_key"], signal["usage_rights_status"],
                         signal["permitted_use"], signal["terms_snapshot_ref"], signal["license_ref"],
                         json.dumps(signal, ensure_ascii=False, sort_keys=True)),
                    )
                    results.append({"line_number": line_number, "status": "accepted", "signal_id": signal["id"],
                                    "error_code": None, "event_id": None})
                response = {
                    "results": results,
                    "accepted": sum(item["status"] == "accepted" for item in results),
                    "rejected": sum(item["status"] == "rejected" for item in results),
                    "duplicate": sum(item["status"] == "duplicate" for item in results),
                }
                self._connection.execute(
                    "INSERT INTO topic_signal_imports (org_id, idempotency_key, payload_hash, actor_id, trace_id, "
                    "policy_snapshot_ref, duration_ms, cost_usd, response) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tenant, key, digest, actor, trace, POLICY_SNAPSHOT,
                     max(0, int((perf_counter() - started) * 1000)), "0", json.dumps(response, sort_keys=True)),
                )
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def get(self, *, org_id: UUID | str, signal_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        identity = _uuid(signal_id, "signal_id")
        row = self._connection.execute(
            "SELECT payload FROM topic_signals WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise TopicSignalError("TENANT_SCOPE_VIOLATION", "signal is not available in this organization")
        return json.loads(row["payload"])

    def list(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT payload FROM topic_signals WHERE org_id = ? ORDER BY id", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def list_publishable(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        """Only verified rights with evidence and editorial/commercial use may advance."""
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT payload FROM topic_signals WHERE org_id = ? AND usage_rights_status = 'verified' "
            "AND permitted_use IN ('editorial', 'commercial') "
            "AND (terms_snapshot_ref IS NOT NULL OR license_ref IS NOT NULL) ORDER BY id",
            (tenant,),
        ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def rejection_events(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        rows = self._connection.execute(
            "SELECT envelope FROM topic_signal_events WHERE org_id = ? ORDER BY event_id", (tenant,)
        ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


__all__ = ["TopicSignalError", "TopicSignalImportService"]
