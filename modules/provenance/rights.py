"""Tenant-scoped rights identities and immutable authorization versions."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.rights_schema import initialize as initialize_rights
from .infrastructure.source_schema import initialize as initialize_sources
from .source import SourceError, _hash, _text as _source_text, _uuid as _source_uuid, _utc as _source_utc


ROOT = Path(__file__).resolve().parents[2]
RIGHTS_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/rights-record.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
VERSION_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/rights-record-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
RIGHTS_STATES = frozenset({"pending", "verified", "expired", "revoked", "complaint_hold"})
TERMINAL_ACTIONS = {
    "expire": ("verified", "expired", "rights.version.expired"),
    "revoke": ("verified", "revoked", "rights.version.revoked"),
    "hold_complaint": ("verified", "complaint_hold", "rights.version.complaint_hold"),
}


class RightsError(ValueError):
    """Stable error code for rights commands and projections."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return _source_uuid(value, name)
    except SourceError as exc:
        raise RightsError("INVALID_RIGHTS_COMMAND", str(exc)) from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    try:
        return _source_text(value, name, limit)
    except SourceError as exc:
        raise RightsError("INVALID_RIGHTS_COMMAND", str(exc)) from exc


def _utc(value: str | None, name: str, *, default_now: bool = True) -> str:
    try:
        return _source_utc(value, name, default_now=default_now)
    except SourceError as exc:
        raise RightsError("INVALID_RIGHTS_TIMESTAMP", str(exc)) from exc


def _optional_utc(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    return _utc(value, name, default_now=False)


def _hash_text(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    normalized = _text(value, name, 256).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise RightsError("INVALID_RIGHTS_HASH", f"{name} must be a SHA-256 hex digest")
    return normalized


def _string_list(value: Iterable[object] | None, name: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise RightsError("INVALID_RIGHTS_SCOPE", f"{name} must be an array")
        return []
    if isinstance(value, (str, bytes, Mapping)):
        raise RightsError("INVALID_RIGHTS_SCOPE", f"{name} must be an array")
    try:
        values = list(value)
    except TypeError as exc:
        raise RightsError("INVALID_RIGHTS_SCOPE", f"{name} must be an array") from exc
    if len(values) > 256:
        raise RightsError("INVALID_RIGHTS_SCOPE", f"{name} has too many entries")
    result: list[str] = []
    for item in values:
        result.append(_text(item, name, 256))
    if required and not result:
        raise RightsError("INVALID_RIGHTS_SCOPE", f"{name} must not be empty")
    return result


def _uuid_list(value: Iterable[object] | None, name: str) -> list[str]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise RightsError("INVALID_SOURCE_SNAPSHOTS", f"{name} must be a nonempty array")
    try:
        values = list(value)
    except TypeError as exc:
        raise RightsError("INVALID_SOURCE_SNAPSHOTS", f"{name} must be a nonempty array") from exc
    if not values:
        raise RightsError("INVALID_SOURCE_SNAPSHOTS", f"{name} must be a nonempty array")
    result: list[str] = []
    for item in values:
        identity = _uuid(item, name)
        if identity not in result:
            result.append(identity)
    return result


class RightsService:
    """Create, verify, and project immutable rights versions."""

    def __init__(self, database: str | Path = ":memory:", *, connection: sqlite3.Connection | None = None) -> None:
        self._owns_connection = connection is None
        self._connection = connection or sqlite3.connect(str(database), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        initialize_sources(self._connection)
        initialize_rights(self._connection)
        self._lock = RLock()

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM rights_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise RightsError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str,
                      response: dict[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO rights_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, json.dumps(response, ensure_ascii=False, sort_keys=True)),
        )

    def _event(self, *, tenant: str, aggregate_id: str, event_type: str, actor: str, trace: str,
               key: str, version: int, payload: dict[str, Any]) -> dict[str, Any]:
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM rights_events "
            "WHERE org_id = ? AND aggregate_type = 'RightsRecordVersion' AND aggregate_id = ?",
            (tenant, aggregate_id),
        ).fetchone()[0]
        event_id = str(uuid4())
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "event_schema_version": 1,
            "occurred_at": _utc(None, "occurred_at"),
            "org_id": tenant,
            "trace_id": trace,
            "correlation_id": None,
            "causation_id": None,
            "aggregate_type": "RightsRecordVersion",
            "aggregate_id": aggregate_id,
            "aggregate_version": version,
            "actor_type": "user",
            "actor_id": actor,
            "idempotency_key": key,
            "payload": payload,
            "payload_hash": _hash(payload),
        }
        self._connection.execute(
            "INSERT INTO rights_events "
            "(event_id, org_id, aggregate_type, aggregate_id, event_type, sequence, envelope) "
            "VALUES (?, ?, 'RightsRecordVersion', ?, ?, ?, ?)",
            (event_id, tenant, aggregate_id, event_type, sequence, json.dumps(envelope, sort_keys=True)),
        )
        return envelope

    def _validate_rights(self, value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        errors = sorted(RIGHTS_VALIDATOR.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            raise RightsError("INVALID_RIGHTS_RECORD", errors[0].message)
        return result

    def _validate_version(self, value: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(value)
        errors = sorted(VERSION_VALIDATOR.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            raise RightsError("INVALID_RIGHTS_VERSION", errors[0].message)
        return result

    def _snapshot_context(self, tenant: str, snapshot_ids: list[str]) -> tuple[str, list[dict[str, Any]]]:
        placeholders = ",".join("?" for _ in snapshot_ids)
        rows = self._connection.execute(
            f"SELECT id, source_id, status, content_hash FROM source_snapshots "
            f"WHERE org_id = ? AND id IN ({placeholders})",
            (tenant, *snapshot_ids),
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        if len(by_id) != len(snapshot_ids):
            raise RightsError("TENANT_SCOPE_VIOLATION", "one or more source snapshots are unavailable")
        source_ids = {row["source_id"] for row in rows}
        if len(source_ids) != 1:
            raise RightsError("INVALID_SOURCE_SNAPSHOTS", "rights version snapshots must belong to one source")
        return next(iter(source_ids)), [dict(by_id[item]) for item in snapshot_ids]

    @staticmethod
    def recompute_snapshot_hash(version: Mapping[str, Any]) -> str:
        immutable = {
            "rights_record_id": version["rights_record_id"],
            "version_no": version["version_no"],
            "source_snapshot_ids": version["source_snapshot_ids"],
            "license_ref": version["license_ref"],
            "contract_ref": version["contract_ref"],
            "evidence_object_refs": version["evidence_object_refs"],
            "terms_snapshot_hash": version["terms_snapshot_hash"],
            "rights_holder": version["rights_holder"],
            "permitted_regions": version["permitted_regions"],
            "permitted_locales": version["permitted_locales"],
            "permitted_media": version["permitted_media"],
            "permitted_use": version["permitted_use"],
            "valid_from": version["valid_from"],
            "valid_to": version["valid_to"],
            "policy_rule_version": version["policy_rule_version"],
            "supersedes_version_id": version["supersedes_version_id"],
        }
        return sha256(json.dumps(immutable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def create_version(
        self, *, org_id: UUID | str, rights_record_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, source_snapshot_ids: Iterable[object],
        license_ref: str | None = None, contract_ref: str | None = None,
        evidence_object_refs: Iterable[object] | None = None, terms_snapshot_hash: str | None = None,
        rights_holder: str, permitted_regions: Iterable[object] | None = None,
        permitted_locales: Iterable[object] | None = None, permitted_media: Iterable[object] | None = None,
        permitted_use: str, valid_from: str | None = None, valid_to: str | None = None,
        policy_rule_version: str, supersedes_version_id: UUID | str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        tenant, record_id, actor = _uuid(org_id, "org_id"), _uuid(rights_record_id, "rights_record_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        snapshots = _uuid_list(source_snapshot_ids, "source_snapshot_ids")
        source_id, _ = self._snapshot_context(tenant, snapshots)
        if license_ref is not None:
            license_ref = _text(license_ref, "license_ref", 2048)
        if contract_ref is not None:
            contract_ref = _text(contract_ref, "contract_ref", 2048)
        evidence = _string_list(evidence_object_refs, "evidence_object_refs")
        terms_hash = _hash_text(terms_snapshot_hash, "terms_snapshot_hash")
        holder = _text(rights_holder, "rights_holder", 512)
        regions = _string_list(permitted_regions, "permitted_regions", required=True)
        locales = _string_list(permitted_locales, "permitted_locales", required=True)
        media = _string_list(permitted_media, "permitted_media", required=True)
        if permitted_use not in {"research", "derivative", "commercial"}:
            raise RightsError("INVALID_RIGHTS_USE", "permitted_use is invalid")
        policy = _text(policy_rule_version, "policy_rule_version", 256)
        start, end = _optional_utc(valid_from, "valid_from"), _optional_utc(valid_to, "valid_to")
        if start and end and datetime.fromisoformat(start.replace("Z", "+00:00")) >= datetime.fromisoformat(end.replace("Z", "+00:00")):
            raise RightsError("INVALID_RIGHTS_TERM", "valid_to must be after valid_from")
        supersedes = None if supersedes_version_id is None else _uuid(supersedes_version_id, "supersedes_version_id")
        digest = _hash({
            "operation": "create_version", "rights_record_id": record_id, "source_snapshot_ids": snapshots,
            "license_ref": license_ref, "contract_ref": contract_ref, "evidence_object_refs": evidence,
            "terms_snapshot_hash": terms_hash, "rights_holder": holder, "permitted_regions": regions,
            "permitted_locales": locales, "permitted_media": media, "permitted_use": permitted_use,
            "valid_from": start, "valid_to": end, "policy_rule_version": policy,
            "supersedes_version_id": supersedes, "expected_version": expected_version,
        })
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                record_row = self._connection.execute(
                    "SELECT payload, source_id, status, current_version_id FROM rights_records WHERE org_id = ? AND id = ?",
                    (tenant, record_id),
                ).fetchone()
                if record_row is not None and record_row["source_id"] != source_id:
                    raise RightsError("RIGHTS_SOURCE_CONFLICT", "rights record is bound to another source")
                if record_row is None:
                    version_no = 1
                    supersedes = None
                    if expected_version not in (None, 0):
                        raise RightsError("VERSION_CONFLICT", "new rights record has no prior version")
                    now = _utc(None, "created_at")
                    record = self._validate_rights({
                        "id": record_id, "org_id": tenant, "source_id": source_id,
                        "current_version_id": None, "status": "pending", "created_at": now, "updated_at": now,
                    })
                    self._connection.execute(
                        "INSERT INTO rights_records (id, org_id, source_id, current_version_id, status, created_at, updated_at, payload) "
                        "VALUES (?, ?, ?, NULL, 'pending', ?, ?, ?)",
                        (record_id, tenant, source_id, now, now, json.dumps(record, sort_keys=True)),
                    )
                else:
                    latest = self._connection.execute(
                        "SELECT id, version_no FROM rights_record_versions WHERE org_id = ? AND rights_record_id = ? "
                        "ORDER BY version_no DESC LIMIT 1", (tenant, record_id)
                    ).fetchone()
                    version_no = 1 if latest is None else int(latest["version_no"]) + 1
                    if expected_version is not None and (type(expected_version) is not int or expected_version != version_no - 1):
                        raise RightsError("VERSION_CONFLICT", "rights record version changed")
                    if supersedes is None and latest is not None:
                        supersedes = latest["id"]
                    elif supersedes is not None and latest is not None and supersedes != latest["id"]:
                        raise RightsError("VERSION_CONFLICT", "supersedes_version_id must reference the latest version")
                    record = json.loads(record_row["payload"])
                created_at = _utc(None, "created_at")
                version = self._validate_version({
                    "id": str(uuid4()), "org_id": tenant, "rights_record_id": record_id,
                    "version_no": version_no, "source_snapshot_ids": snapshots,
                    "license_ref": license_ref, "contract_ref": contract_ref,
                    "evidence_object_refs": evidence, "terms_snapshot_hash": terms_hash,
                    "rights_holder": holder, "permitted_regions": regions, "permitted_locales": locales,
                    "permitted_media": media, "permitted_use": permitted_use,
                    "valid_from": start, "valid_to": end, "status": "pending",
                    "policy_rule_version": policy, "verified_by": None, "verified_at": None,
                    "verification_reason": None, "supersedes_version_id": supersedes,
                    "snapshot_hash": "0" * 64, "created_by": actor, "created_at": created_at,
                })
                version["snapshot_hash"] = self.recompute_snapshot_hash(version)
                version = self._validate_version(version)
                # A pending revision cannot displace a still-effective verified
                # authorization.  The parent points to the version that may be
                # used, and verification performs the pointer switch.
                if record["status"] != "verified":
                    record.update(current_version_id=None, status="pending")
                record["updated_at"] = created_at
                self._connection.execute(
                    "INSERT INTO rights_record_versions (id, org_id, rights_record_id, version_no, source_snapshot_ids, "
                    "license_ref, contract_ref, evidence_object_refs, terms_snapshot_hash, rights_holder, permitted_regions, "
                    "permitted_locales, permitted_media, permitted_use, valid_from, valid_to, status, policy_rule_version, "
                    "verified_by, verified_at, verification_reason, supersedes_version_id, snapshot_hash, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (version["id"], tenant, record_id, version_no, json.dumps(snapshots, sort_keys=True), license_ref,
                     contract_ref, json.dumps(evidence, sort_keys=True), terms_hash, holder, json.dumps(regions, sort_keys=True),
                     json.dumps(locales, sort_keys=True), json.dumps(media, sort_keys=True), permitted_use, start, end,
                     "pending", policy, None, None, None, supersedes, version["snapshot_hash"], actor, created_at,
                     json.dumps(version, ensure_ascii=False, sort_keys=True)),
                )
                self._connection.execute(
                    "UPDATE rights_records SET current_version_id = ?, status = ?, updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ?",
                    (record["current_version_id"], record["status"], created_at,
                     json.dumps(record, ensure_ascii=False, sort_keys=True), tenant, record_id),
                )
                event = self._event(
                    tenant=tenant, aggregate_id=version["id"], event_type="rights.version.created", actor=actor,
                    trace=trace, key=key, version=version_no,
                    payload={"aggregate_id": version["id"], "aggregate_version": version_no,
                             "from_state": "none", "to_state": "pending", "command": "create",
                             "snapshot_hash": version["snapshot_hash"], "rights_record_id": record_id,
                             "source_snapshot_ids": snapshots},
                )
                response = {"rights_record": record, "version": version, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise RightsError("RIGHTS_CONFLICT", "rights record identity conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    create = create_version

    def verify_version(
        self, *, org_id: UUID | str, rights_record_id: UUID | str, version_id: UUID | str,
        actor_id: UUID | str, trace_id: str, idempotency_key: str, expected_version: int | None = None,
        verification_reason: str | None = None, verified_at: str | None = None,
    ) -> dict[str, Any]:
        tenant, record_id, version_id, actor = _uuid(org_id, "org_id"), _uuid(rights_record_id, "rights_record_id"), _uuid(version_id, "version_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        reason = None if verification_reason is None else _text(verification_reason, "verification_reason", 2048)
        verified_timestamp = _utc(verified_at, "verified_at") if verified_at is not None else _utc(None, "verified_at")
        digest = _hash({"operation": "verify_version", "rights_record_id": record_id, "version_id": version_id,
                        "expected_version": expected_version, "verification_reason": reason,
                        "verified_at": verified_at})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._connection.execute(
                    "SELECT * FROM rights_record_versions WHERE org_id = ? AND id = ? AND rights_record_id = ?",
                    (tenant, version_id, record_id),
                ).fetchone()
                if row is None:
                    raise RightsError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
                if expected_version is not None and row["version_no"] != expected_version:
                    raise RightsError("VERSION_CONFLICT", "rights version changed")
                if row["status"] != "pending":
                    raise RightsError("INVALID_RIGHTS_STATE", "only pending rights versions can be verified")
                latest = self._connection.execute(
                    "SELECT id FROM rights_record_versions WHERE org_id = ? AND rights_record_id = ? "
                    "ORDER BY version_no DESC LIMIT 1", (tenant, record_id)
                ).fetchone()
                if latest is None or latest["id"] != version_id:
                    raise RightsError("VERSION_CONFLICT", "only the latest rights version can be verified")
                snapshot_ids = json.loads(row["source_snapshot_ids"])
                snapshot_rows = self._connection.execute(
                    "SELECT id, status FROM source_snapshots WHERE org_id = ? AND id IN (" + ",".join("?" for _ in snapshot_ids) + ")",
                    (tenant, *snapshot_ids),
                ).fetchall()
                if len(snapshot_rows) != len(snapshot_ids) or any(item["status"] != "usable" for item in snapshot_rows):
                    raise RightsError("SOURCE_SNAPSHOT_NOT_USABLE", "all source snapshots must be usable before verification")
                if not row["license_ref"] and not row["contract_ref"] and not json.loads(row["evidence_object_refs"]):
                    raise RightsError("RIGHTS_EVIDENCE_REQUIRED", "a license, contract, or evidence reference is required")
                if not row["terms_snapshot_hash"] or not row["policy_rule_version"]:
                    raise RightsError("RIGHTS_EVIDENCE_REQUIRED", "terms snapshot hash and policy rule version are required")
                if reason is None:
                    raise RightsError("REASON_REQUIRED", "verification_reason is required")
                now = datetime.now(timezone.utc)
                if row["valid_from"] and now < datetime.fromisoformat(row["valid_from"].replace("Z", "+00:00")):
                    raise RightsError("RIGHTS_NOT_YET_VALID", "rights validity period has not started")
                if row["valid_to"] and now >= datetime.fromisoformat(row["valid_to"].replace("Z", "+00:00")):
                    raise RightsError("RIGHTS_EXPIRED", "rights validity period has ended")
                version = json.loads(row["payload"])
                if version["snapshot_hash"] != self.recompute_snapshot_hash(version):
                    raise RightsError("RIGHTS_SNAPSHOT_MISMATCH", "rights snapshot hash does not match its scope")
                version.update(status="verified", verified_by=actor, verified_at=verified_timestamp,
                               verification_reason=reason)
                version = self._validate_version(version)
                self._connection.execute(
                    "UPDATE rights_record_versions SET status = 'verified', verified_by = ?, verified_at = ?, "
                    "verification_reason = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (actor, verified_timestamp, reason, json.dumps(version, ensure_ascii=False, sort_keys=True), tenant, version_id),
                )
                record_row = self._connection.execute(
                    "SELECT payload FROM rights_records WHERE org_id = ? AND id = ?", (tenant, record_id)
                ).fetchone()
                if record_row is None:
                    raise RightsError("RIGHTS_RECORD_NOT_FOUND", "rights record is missing")
                record = json.loads(record_row["payload"])
                record.update(current_version_id=version_id, status="verified", updated_at=verified_timestamp)
                self._connection.execute(
                    "UPDATE rights_records SET current_version_id = ?, status = 'verified', updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ?",
                    (version_id, verified_timestamp, json.dumps(record, ensure_ascii=False, sort_keys=True), tenant, record_id),
                )
                event = self._event(
                    tenant=tenant, aggregate_id=version_id, event_type="rights.version.verified", actor=actor,
                    trace=trace, key=key, version=row["version_no"],
                    payload={"aggregate_id": version_id, "aggregate_version": row["version_no"],
                             "from_state": "pending", "to_state": "verified", "command": "verify",
                             "snapshot_hash": version["snapshot_hash"], "reason": reason},
                )
                response = {"rights_record": record, "version": version, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    verify = verify_version

    def transition_version(
        self, *, org_id: UUID | str, rights_record_id: UUID | str, version_id: UUID | str,
        actor_id: UUID | str, trace_id: str, idempotency_key: str, action: str,
        expected_version: int, reason: str,
    ) -> dict[str, Any]:
        tenant, record_id, version_id, actor = _uuid(org_id, "org_id"), _uuid(rights_record_id, "rights_record_id"), _uuid(version_id, "version_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if action not in TERMINAL_ACTIONS:
            raise RightsError("INVALID_RIGHTS_ACTION", "unsupported rights action")
        if type(expected_version) is not int or expected_version < 1:
            raise RightsError("VERSION_CONFLICT", "expected_version must be a positive integer")
        normalized_reason = _text(reason, "reason", 2048)
        _, target, event_type = TERMINAL_ACTIONS[action]
        digest = _hash({"operation": "transition_version", "rights_record_id": record_id, "version_id": version_id,
                        "action": action, "expected_version": expected_version, "reason": normalized_reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._connection.execute(
                    "SELECT * FROM rights_record_versions WHERE org_id = ? AND id = ? AND rights_record_id = ?",
                    (tenant, version_id, record_id),
                ).fetchone()
                if row is None:
                    raise RightsError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
                if row["version_no"] != expected_version:
                    raise RightsError("VERSION_CONFLICT", "rights version changed")
                if row["status"] != "verified":
                    raise RightsError("INVALID_RIGHTS_STATE", "only verified rights versions can transition")
                version = json.loads(row["payload"])
                version.update(status=target, verification_reason=normalized_reason)
                version = self._validate_version(version)
                self._connection.execute(
                    "UPDATE rights_record_versions SET status = ?, verification_reason = ?, payload = ? "
                    "WHERE org_id = ? AND id = ?",
                    (target, normalized_reason, json.dumps(version, ensure_ascii=False, sort_keys=True), tenant, version_id),
                )
                record_row = self._connection.execute(
                    "SELECT payload FROM rights_records WHERE org_id = ? AND id = ?", (tenant, record_id)
                ).fetchone()
                if record_row is None:
                    raise RightsError("RIGHTS_RECORD_NOT_FOUND", "rights record is missing")
                record = json.loads(record_row["payload"])
                if record["current_version_id"] == version_id:
                    record.update(current_version_id=None, status=target)
                record["updated_at"] = _utc(None, "updated_at")
                self._connection.execute(
                    "UPDATE rights_records SET current_version_id = ?, status = ?, updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ?",
                    (record["current_version_id"], record["status"], record["updated_at"],
                     json.dumps(record, ensure_ascii=False, sort_keys=True), tenant, record_id),
                )
                event = self._event(
                    tenant=tenant, aggregate_id=version_id, event_type=event_type, actor=actor, trace=trace,
                    key=key, version=expected_version,
                    payload={"aggregate_id": version_id, "aggregate_version": expected_version,
                             "from_state": "verified", "to_state": target, "command": action,
                             "snapshot_hash": version["snapshot_hash"], "reason": normalized_reason},
                )
                response = {"rights_record": record, "version": version, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    transition = transition_version

    def get_record(self, *, org_id: UUID | str, rights_record_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(rights_record_id, "rights_record_id")
        row = self._connection.execute(
            "SELECT payload FROM rights_records WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise RightsError("TENANT_SCOPE_VIOLATION", "rights record is not in this organization")
        return json.loads(row["payload"])

    get = get_record

    def get_version(self, *, org_id: UUID | str, rights_record_id: UUID | str, version_id: UUID | str) -> dict[str, Any]:
        tenant, record_id, identity = _uuid(org_id, "org_id"), _uuid(rights_record_id, "rights_record_id"), _uuid(version_id, "version_id")
        row = self._connection.execute(
            "SELECT payload FROM rights_record_versions WHERE org_id = ? AND id = ? AND rights_record_id = ?",
            (tenant, identity, record_id),
        ).fetchone()
        if row is None:
            raise RightsError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
        return json.loads(row["payload"])

    def list_versions(self, *, org_id: UUID | str, rights_record_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant, record_id = _uuid(org_id, "org_id"), _uuid(rights_record_id, "rights_record_id")
        rows = self._connection.execute(
            "SELECT payload FROM rights_record_versions WHERE org_id = ? AND rights_record_id = ? ORDER BY version_no",
            (tenant, record_id),
        ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def events(self, *, org_id: UUID | str, version_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        if version_id is None:
            rows = self._connection.execute(
                "SELECT envelope FROM rights_events WHERE org_id = ? ORDER BY aggregate_id, sequence", (tenant,)
            ).fetchall()
        else:
            identity = _uuid(version_id, "version_id")
            rows = self._connection.execute(
                "SELECT envelope FROM rights_events WHERE org_id = ? AND aggregate_id = ? ORDER BY sequence",
                (tenant, identity),
            ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


RightsRecordService = RightsService

__all__ = ["RightsError", "RightsService", "RightsRecordService"]
