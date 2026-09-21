"""Tenant-scoped CanonicalContent roots and immutable editorial versions.

CANON-001 deliberately keeps the write model small.  A root may move through
editorial states and point at its current version; a version's content is an
append-only fact.  TopicBrief, provenance and KnowledgeCore records are checked
through their public storage contracts when those stores are available, while
the module remains usable in an isolated SQLite test database.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.canonical_schema import initialize


ROOT = Path(__file__).resolve().parents[2]
CONTENT_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/canonical-content.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
VERSION_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/canonical-content-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
LOCKED_BRIEF_STATES = frozenset({"locked", "approved"})


class CanonicalContentError(ValueError):
    """Stable error code for canonical content commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_time(value: object, name: str, *, required: bool = False) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _uuid(value: UUID | str | None, name: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise CanonicalContentError("INVALID_CANONICAL_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 4096, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        qualifier = "nonempty " if required else ""
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} must be {qualifier}text of at most {limit} characters")
    return value.strip()


def _hash_value(value: object, name: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value.strip()):
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} must be a SHA-256 hex digest")
    return value.strip().lower()


def _sequence(value: object, name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} must be an array")
    if len(value) > 512:
        raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} has too many entries")
    return list(value)


def _uuid_list(value: object, name: str) -> list[str]:
    values = _sequence(value, name)
    result: list[str] = []
    for item in values:
        identity = _uuid(item, name)
        assert identity is not None
        if identity not in result:
            result.append(identity)
    return result


def _stable_items(value: object, name: str) -> list[dict[str, Any]]:
    """Normalize an editorial array to stable keys and deterministic positions."""
    values = _sequence(value, name)
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    positions: set[int] = set()
    for index, raw in enumerate(values, start=1):
        if isinstance(raw, Mapping):
            item = deepcopy(dict(raw))
            key_value = item.get("key", item.get("block_id", item.get("claim_key", item.get("id"))))
            position_value = item.get("position", item.get("order", index))
        else:
            item = {"value": raw}
            key_value = raw
            position_value = index
        key = _text(key_value, f"{name}.key", 256)
        if type(position_value) is not int or position_value < 1:
            raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name}.position must be a positive integer")
        if key in keys:
            raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} keys must be unique")
        if position_value in positions:
            raise CanonicalContentError("INVALID_CANONICAL_CONTENT", f"{name} positions must be unique")
        keys.add(key)
        positions.add(position_value)
        item["key"] = key
        item["position"] = position_value
        # Keep compatibility aliases in the normalized payload for consumers
        # of the original contract vocabulary.
        if "block_id" not in item:
            item["block_id"] = key
        result.append(item)
    return sorted(result, key=lambda item: (item["position"], item["key"]))


class CanonicalContentService:
    """Create roots, append immutable versions, and submit editorial review."""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        connection: sqlite3.Connection | None = None,
        topic_brief_service: Any | None = None,
    ) -> None:
        self._owns_connection = connection is None
        self._connection = connection or sqlite3.connect(str(database), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        initialize(self._connection)
        self.topic_brief_service = topic_brief_service
        self._lock = RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    @staticmethod
    def recompute_content_hash(payload: Mapping[str, Any]) -> str:
        """Return the canonical hash for immutable version inputs."""
        material = {
            "title": payload.get("title", ""),
            "abstract": payload.get("abstract", ""),
            "sections": payload.get("sections", []),
            "claims": payload.get("claims", []),
            "code_blocks": payload.get("code_blocks", []),
            "examples": payload.get("examples", []),
            "limitations": payload.get("limitations", []),
            "source_snapshot_refs": payload.get("source_snapshot_refs", payload.get("source_snapshot_ids", [])),
            "knowledge_core_version": payload.get("knowledge_core_version", payload.get("knowledge_core_version_id")),
            "rights_snapshot_ids": payload.get("rights_snapshot_ids", []),
        }
        return _hash(material)

    def _identity(self, org_id: UUID | str, actor_id: UUID | str, trace_id: str, key: str) -> tuple[str, str, str, str]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        assert tenant is not None and actor is not None
        trace = _text(trace_id, "trace_id", 256)
        idem = _text(key, "idempotency_key", 200)
        return tenant, actor, trace, idem

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM canonical_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise CanonicalContentError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str, response: Mapping[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO canonical_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, _json(response)),
        )

    def _topic_brief(self, tenant: str, brief_id: str) -> dict[str, Any]:
        candidate: Mapping[str, Any] | None = None
        if self.topic_brief_service is not None:
            try:
                candidate = self.topic_brief_service.get(org_id=tenant, brief_id=brief_id)
            except Exception:
                candidate = None
        if candidate is None:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'topic_briefs'"
            ).fetchone()
            if table is not None:
                try:
                    row = self._connection.execute(
                        "SELECT status, payload, input_snapshot_hash FROM topic_briefs WHERE org_id = ? AND id = ?",
                        (tenant, brief_id),
                    ).fetchone()
                except sqlite3.OperationalError:
                    try:
                        row = self._connection.execute(
                            "SELECT status, payload FROM topic_briefs WHERE org_id = ? AND id = ?",
                            (tenant, brief_id),
                        ).fetchone()
                    except sqlite3.OperationalError:
                        row = self._connection.execute(
                            "SELECT status FROM topic_briefs WHERE org_id = ? AND id = ?",
                            (tenant, brief_id),
                        ).fetchone()
                if row is not None:
                    try:
                        candidate = json.loads(row["payload"])
                    except (TypeError, json.JSONDecodeError):
                        candidate = {"status": row["status"], "input_snapshot_hash": row["input_snapshot_hash"] if "input_snapshot_hash" in row.keys() else None}
                    if isinstance(candidate, Mapping):
                        candidate = dict(candidate)
                        candidate.setdefault("status", row["status"])
                        if "input_snapshot_hash" in row.keys():
                            candidate.setdefault("input_snapshot_hash", row["input_snapshot_hash"])
        if candidate is None or str(candidate.get("org_id", tenant)) != tenant:
            raise CanonicalContentError("TOPIC_BRIEF_REQUIRED", "a tenant-scoped TopicBrief is required")
        if candidate.get("status") not in LOCKED_BRIEF_STATES:
            raise CanonicalContentError("TOPIC_BRIEF_REQUIRED", "TopicBrief must be locked or approved")
        return dict(candidate)

    def _check_external_refs(self, tenant: str, source_ids: Sequence[str], rights_ids: Sequence[str], knowledge_id: str | None) -> None:
        if source_ids:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_snapshots'"
            ).fetchone()
            if table is not None:
                placeholders = ",".join("?" for _ in source_ids)
                rows = self._connection.execute(
                    f"SELECT id FROM source_snapshots WHERE org_id = ? AND id IN ({placeholders})",
                    (tenant, *source_ids),
                ).fetchall()
                if len(rows) != len(source_ids):
                    raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "source snapshot is not in this organization")
        if rights_ids:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rights_record_versions'"
            ).fetchone()
            if table is not None:
                placeholders = ",".join("?" for _ in rights_ids)
                rows = self._connection.execute(
                    f"SELECT id FROM rights_record_versions WHERE org_id = ? AND id IN ({placeholders})",
                    (tenant, *rights_ids),
                ).fetchall()
                if len(rows) != len(rights_ids):
                    raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "rights snapshot is not in this organization")
        if knowledge_id is not None:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_core_versions'"
            ).fetchone()
            if table is not None:
                row = self._connection.execute(
                    "SELECT status FROM knowledge_core_versions WHERE org_id = ? AND id = ?",
                    (tenant, knowledge_id),
                ).fetchone()
                if row is None:
                    raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "KnowledgeCore version is not in this organization")
                if row["status"] != "verified":
                    raise CanonicalContentError("KNOWLEDGE_CORE_NOT_VERIFIED", "KnowledgeCore version must be verified")

    def _claim_binding_refs(self, tenant: str, item: dict[str, Any], top_level_evidence: Sequence[str],
                            top_level_rights: Sequence[str]) -> dict[str, Any]:
        """Validate high-priority Claim bindings without importing Knowledge/Provenance internals."""
        priority = str(item.get("priority", "normal")).strip().lower()
        if priority not in {"low", "normal", "high", "urgent"}:
            raise CanonicalContentError("INVALID_CANONICAL_CONTENT", "claim priority is invalid")
        item["priority"] = priority
        claim_value = item.get("claim_id")
        if claim_value is None:
            candidate = item.get("id")
            try:
                claim_value = _uuid(candidate, "claim_id") if candidate is not None else None
            except CanonicalContentError:
                claim_value = None
        else:
            claim_value = _uuid(claim_value, "claim_id")
        if claim_value is not None:
            item["claim_id"] = claim_value
        evidence_value = item.get("evidence_ids", item.get("evidence_refs", top_level_evidence))
        rights_value = item.get("rights_snapshot_ids", item.get("rights_record_version_ids", top_level_rights))
        evidence_ids = _uuid_list(evidence_value, "evidence_ids") if evidence_value is not None else []
        rights_ids = _uuid_list(rights_value, "rights_snapshot_ids") if rights_value is not None else []

        claims_table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'claims'"
        ).fetchone()
        evidence_table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'evidences'"
        ).fetchone()
        rights_table = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rights_record_versions'"
        ).fetchone()
        claim_row = None
        if claim_value is not None and claims_table is not None:
            claim_row = self._connection.execute(
                "SELECT status FROM claims WHERE org_id = ? AND id = ?", (tenant, claim_value)
            ).fetchone()
            if claim_row is None:
                raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "claim is not in this organization")
            if priority in {"high", "urgent"} and claim_row["status"] != "verified":
                raise CanonicalContentError("CANONICAL_EVIDENCE_REQUIRED", "high-priority claim must be verified")
        elif priority in {"high", "urgent"}:
            raise CanonicalContentError("CANONICAL_EVIDENCE_REQUIRED", "high-priority claim must reference a Claim")

        if claim_value is not None and not evidence_ids and evidence_table is not None:
            rows = self._connection.execute(
                "SELECT id FROM evidences WHERE org_id = ? AND claim_id = ? ORDER BY id", (tenant, claim_value)
            ).fetchall()
            evidence_ids = [str(row["id"]) for row in rows]
        valid_evidence_ids: list[str] = []
        for evidence_id in evidence_ids:
            if evidence_table is None:
                raise CanonicalContentError("CANONICAL_EVIDENCE_REQUIRED", "evidence storage is unavailable")
            row = self._connection.execute(
                "SELECT claim_id, rights_record_version_id, status FROM evidences WHERE org_id = ? AND id = ?",
                (tenant, evidence_id),
            ).fetchone()
            if row is None:
                raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "evidence is not in this organization")
            if claim_value is not None and row["claim_id"] not in {None, claim_value}:
                raise CanonicalContentError("CANONICAL_EVIDENCE_REQUIRED", "evidence is bound to another Claim")
            if row["status"] not in {"captured", "valid"}:
                continue
            valid_evidence_ids.append(evidence_id)
            if row["rights_record_version_id"] and row["rights_record_version_id"] not in rights_ids:
                rights_ids.append(str(row["rights_record_version_id"]))
        if priority in {"high", "urgent"} and not valid_evidence_ids:
            raise CanonicalContentError("CANONICAL_EVIDENCE_REQUIRED", "high-priority claim needs at least one valid Evidence")

        for rights_id in rights_ids:
            if rights_table is None:
                raise CanonicalContentError("CANONICAL_RIGHTS_REQUIRED", "rights version storage is unavailable")
            row = self._connection.execute(
                "SELECT status FROM rights_record_versions WHERE org_id = ? AND id = ?", (tenant, rights_id)
            ).fetchone()
            if row is None:
                raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
            if priority in {"high", "urgent"} and row["status"] != "verified":
                raise CanonicalContentError("CANONICAL_RIGHTS_REQUIRED", "high-priority claim needs a verified RightsRecordVersion")
        if priority in {"high", "urgent"} and not rights_ids:
            raise CanonicalContentError("CANONICAL_RIGHTS_REQUIRED", "high-priority claim needs a RightsRecordVersion")
        item["evidence_ids"] = valid_evidence_ids if evidence_ids else []
        item["rights_snapshot_ids"] = rights_ids
        return item

    def _normalize_version(self, *, tenant: str, brief: Mapping[str, Any], values: Mapping[str, Any], actor: str,
                           supersedes_version_id: str | None = None) -> dict[str, Any]:
        title = _text(values.get("title"), "title", 512)
        abstract = _text(values.get("abstract", ""), "abstract", 10000, required=False)
        sections = _stable_items(values.get("sections", []), "sections")
        raw_claims = values.get("claims")
        if raw_claims is None and values.get("claim_ids") is not None:
            raw_claims = [{"key": str(item), "claim_id": item} for item in _sequence(values.get("claim_ids"), "claim_ids")]
        claims = _stable_items(raw_claims or [], "claims")
        code_blocks = _stable_items(values.get("code_blocks", values.get("codeBlocks", [])), "code_blocks")
        examples = _stable_items(values.get("examples", []), "examples")
        limitations = _stable_items(values.get("limitations", []), "limitations")
        source_values = values.get("source_snapshot_refs", values.get("source_snapshot_ids", []))
        source_refs = _uuid_list(source_values, "source_snapshot_refs")
        rights_refs = _uuid_list(values.get("rights_snapshot_ids", []), "rights_snapshot_ids")
        evidence_refs = _uuid_list(values.get("evidence_ids", []), "evidence_ids")
        claims = [self._claim_binding_refs(tenant, item, evidence_refs, rights_refs) for item in claims]
        knowledge_value = values.get("knowledge_core_version", values.get("knowledge_core_version_id"))
        if isinstance(knowledge_value, Mapping):
            knowledge_value = knowledge_value.get("id")
        knowledge_id = _uuid(knowledge_value, "knowledge_core_version", required=False)
        input_hash = _hash_value(values.get("input_snapshot_hash"), "input_snapshot_hash")
        brief_hash = brief.get("input_snapshot_hash")
        if brief_hash and str(brief_hash).lower() != input_hash:
            raise CanonicalContentError("INPUT_SNAPSHOT_MISMATCH", "input_snapshot_hash does not match the locked TopicBrief")
        self._check_external_refs(tenant, source_refs, rights_refs, knowledge_id)
        conflict_values = values.get("conflict_set_ids", [])
        conflict_set_ids = _uuid_list(conflict_values, "conflict_set_ids")
        if not conflict_set_ids and knowledge_id is not None:
            table = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'knowledge_core_versions'"
            ).fetchone()
            if table is not None:
                row = self._connection.execute(
                    "SELECT conflict_set_ids_json, payload FROM knowledge_core_versions WHERE org_id = ? AND id = ?",
                    (tenant, knowledge_id),
                ).fetchone()
                if row is not None:
                    try:
                        conflict_set_ids = _uuid_list(json.loads(row["conflict_set_ids_json"] or "[]"), "conflict_set_ids")
                    except (KeyError, TypeError, json.JSONDecodeError):
                        conflict_set_ids = []
        created_at = _now()
        checked_at = _parse_time(values.get("freshness_checked_at"), "freshness_checked_at") or datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        expires_at = _parse_time(values.get("freshness_expires_at"), "freshness_expires_at")
        if expires_at is None:
            ttl_days = values.get("freshness_ttl_days", 30)
            if type(ttl_days) not in {int, float} or isinstance(ttl_days, bool) or ttl_days <= 0 or ttl_days > 3650:
                raise CanonicalContentError("INVALID_CANONICAL_CONTENT", "freshness_ttl_days must be between 0 and 3650")
            expires_at = checked_at + timedelta(days=float(ttl_days))
        freshness_status = str(values.get("freshness_status", "fresh")).strip().lower()
        if conflict_set_ids:
            freshness_status = "conflict"
        if freshness_status not in {"fresh", "review_due", "stale", "expired", "conflict", "withdrawn"}:
            raise CanonicalContentError("INVALID_CANONICAL_CONTENT", "freshness_status is invalid")
        normalized: dict[str, Any] = {
            "id": str(uuid4()),
            "org_id": tenant,
            "canonical_content_id": str(values.get("canonical_content_id")) if values.get("canonical_content_id") else None,
            "topic_brief_id": str(brief["id"]),
            "version_no": 0,
            "title": title,
            "abstract": abstract,
            "sections": sections,
            "claims": claims,
            "code_blocks": code_blocks,
            "examples": examples,
            "limitations": limitations,
            "source_snapshot_refs": source_refs,
            "source_snapshot_ids": source_refs,
            "topic_brief_status": str(brief.get("status", "")),
            "topic_brief_lock_hash": brief.get("lock_hash"),
            "knowledge_core_version": knowledge_id,
            "knowledge_core_version_id": knowledge_id,
            "input_snapshot_hash": input_hash,
            "rights_snapshot_ids": rights_refs,
            "supersedes_version_id": supersedes_version_id,
            "status": "draft",
            "created_by": actor,
            "created_at": created_at,
            "freshness_status": freshness_status,
            "freshness_checked_at": _stamp(checked_at),
            "freshness_expires_at": _stamp(expires_at) if expires_at is not None else None,
            "conflict_set_ids": conflict_set_ids,
            "refresh_required": freshness_status != "fresh",
        }
        computed = self.recompute_content_hash(normalized)
        supplied = values.get("content_hash")
        if supplied is not None:
            supplied_hash = _hash_value(supplied, "content_hash")
            if supplied_hash != computed:
                raise CanonicalContentError("CONTENT_HASH_MISMATCH", "content_hash does not match immutable content")
        normalized["content_hash"] = computed
        return normalized

    @staticmethod
    def _validate(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
        errors = sorted(validator.iter_errors(dict(value)), key=lambda error: list(error.path))
        if errors:
            raise CanonicalContentError(code, errors[0].message)

    def _event(self, *, tenant: str, aggregate_id: str, version: int, event_type: str, actor: str,
               trace: str, key: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM canonical_events WHERE org_id = ? AND aggregate_type = 'CanonicalContentVersion' AND aggregate_id = ?",
            (tenant, aggregate_id),
        ).fetchone()[0]
        body = dict(payload)
        body.setdefault("aggregate_id", aggregate_id)
        body.setdefault("aggregate_version", version)
        event_id = str(uuid4())
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "event_schema_version": 1,
            "occurred_at": _now(),
            "org_id": tenant,
            "trace_id": trace,
            "correlation_id": None,
            "causation_id": None,
            "aggregate_type": "CanonicalContentVersion",
            "aggregate_id": aggregate_id,
            "aggregate_version": version,
            "actor_type": "user",
            "actor_id": actor,
            "idempotency_key": key,
            "payload": body,
            "payload_hash": _hash(body),
        }
        self._connection.execute(
            "INSERT INTO canonical_events (event_id, org_id, aggregate_type, aggregate_id, event_type, sequence, envelope) VALUES (?, ?, 'CanonicalContentVersion', ?, ?, ?, ?)",
            (event_id, tenant, aggregate_id, event_type, sequence, _json(envelope)),
        )
        return envelope

    def _root_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return json.loads(row["payload"])

    def _version_payload(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload"])
        try:
            check = self._connection.execute(
                "SELECT freshness_status, checked_at, expires_at, conflict_set_ids_json "
                "FROM canonical_freshness_checks WHERE org_id = ? AND canonical_content_version_id = ? "
                "ORDER BY checked_at DESC, id DESC LIMIT 1",
                (row["org_id"], row["id"]),
            ).fetchone()
        except sqlite3.OperationalError:
            check = None
        if check is not None:
            payload["freshness_status"] = check["freshness_status"]
            payload["freshness_checked_at"] = check["checked_at"]
            payload["freshness_expires_at"] = check["expires_at"]
            payload["conflict_set_ids"] = json.loads(check["conflict_set_ids_json"] or "[]")
            payload["refresh_required"] = check["freshness_status"] != "fresh"
        return payload

    @staticmethod
    def _diff_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Select the immutable editorial surface used for a version diff."""
        fields = (
            "title", "abstract", "sections", "claims", "code_blocks", "examples", "limitations",
            "source_snapshot_refs", "knowledge_core_version", "input_snapshot_hash", "rights_snapshot_ids",
        )
        return {field: deepcopy(payload.get(field)) for field in fields}

    @staticmethod
    def _diff_operations(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        array_fields = {"sections", "claims", "code_blocks", "examples", "limitations"}
        for field in sorted(set(before) | set(after)):
            old, new = before.get(field), after.get(field)
            if old == new:
                continue
            if field in array_fields and isinstance(old, list) and isinstance(new, list):
                old_by_key = {str(item.get("key")): item for item in old if isinstance(item, Mapping) and item.get("key") is not None}
                new_by_key = {str(item.get("key")): item for item in new if isinstance(item, Mapping) and item.get("key") is not None}
                if len(old_by_key) == len(old) and len(new_by_key) == len(new):
                    for key in sorted(set(old_by_key) - set(new_by_key)):
                        operations.append({"op": "remove", "path": f"/{field}/{key}", "before": old_by_key[key]})
                    for key in sorted(set(new_by_key) - set(old_by_key)):
                        operations.append({"op": "add", "path": f"/{field}/{key}", "after": new_by_key[key]})
                    for key in sorted(set(old_by_key) & set(new_by_key)):
                        if old_by_key[key] != new_by_key[key]:
                            operations.append({"op": "replace", "path": f"/{field}/{key}", "before": old_by_key[key], "after": new_by_key[key]})
                    continue
            if field not in before:
                operations.append({"op": "add", "path": f"/{field}", "after": new})
            elif field not in after:
                operations.append({"op": "remove", "path": f"/{field}", "before": old})
            else:
                operations.append({"op": "replace", "path": f"/{field}", "before": old, "after": new})
        return operations

    def _resolve_version_for_root(
        self,
        tenant: str,
        content_id: str,
        *,
        version_id: UUID | str | None = None,
        version_no: int | None = None,
    ) -> sqlite3.Row:
        if version_id is not None and version_no is not None:
            raise CanonicalContentError("INVALID_CANONICAL_COMMAND", "provide version_id or version_no, not both")
        if version_id is not None:
            identity = _uuid(version_id, "version_id")
            assert identity is not None
            row = self._fetch_version(tenant, identity)
        elif version_no is not None:
            if type(version_no) is not int or version_no < 1:
                raise CanonicalContentError("INVALID_CANONICAL_COMMAND", "version_no must be a positive integer")
            row = self._connection.execute(
                "SELECT * FROM canonical_content_versions WHERE org_id = ? AND canonical_content_id = ? AND version_no = ?",
                (tenant, content_id, version_no),
            ).fetchone()
            if row is None:
                raise CanonicalContentError("VERSION_NOT_FOUND", "canonical content version does not exist")
        else:
            raise CanonicalContentError("INVALID_CANONICAL_COMMAND", "a version_id or version_no is required")
        if row["canonical_content_id"] != content_id:
            raise CanonicalContentError("VERSION_SCOPE_VIOLATION", "version does not belong to this canonical content")
        return row

    def diff_versions(
        self,
        *,
        org_id: UUID | str,
        canonical_content_id: UUID | str,
        from_version_id: UUID | str | None = None,
        to_version_id: UUID | str | None = None,
        from_version_no: int | None = None,
        to_version_no: int | None = None,
        actor_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        """Compare two immutable versions using stable item keys.

        The result is deterministic and is cached in the append-only diff table;
        caching never changes either version and is safe to repeat.
        """
        tenant = _uuid(org_id, "org_id")
        content_id = _uuid(canonical_content_id, "canonical_content_id")
        assert tenant is not None and content_id is not None
        self._fetch_root(tenant, content_id)
        before_row = self._resolve_version_for_root(
            tenant, content_id, version_id=from_version_id, version_no=from_version_no
        )
        after_row = self._resolve_version_for_root(
            tenant, content_id, version_id=to_version_id, version_no=to_version_no
        )
        before = self._diff_fields(self._version_payload(before_row))
        after = self._diff_fields(self._version_payload(after_row))
        operations = self._diff_operations(before, after)
        changed = sorted({operation["path"].split("/", 2)[1] for operation in operations})
        diff_hash = _hash({"from_version_id": before_row["id"], "to_version_id": after_row["id"], "operations": operations})
        cached = self._connection.execute(
            "SELECT payload FROM canonical_content_version_diffs WHERE org_id = ? AND canonical_content_id = ? AND from_version_id = ? AND to_version_id = ?",
            (tenant, content_id, before_row["id"], after_row["id"]),
        ).fetchone()
        if cached is not None:
            return json.loads(cached["payload"])
        result = {
            "id": str(uuid5(NAMESPACE_URL, f"canonical-diff:{tenant}:{content_id}:{before_row['id']}:{after_row['id']}")),
            "org_id": tenant,
            "canonical_content_id": content_id,
            "from_version_id": before_row["id"],
            "to_version_id": after_row["id"],
            "from_version_no": int(before_row["version_no"]),
            "to_version_no": int(after_row["version_no"]),
            "changed_fields": changed,
            "operations": operations,
            "empty": not operations,
            "diff_hash": diff_hash,
            "created_at": _now(),
        }
        creator = _uuid(actor_id, "actor_id", required=False) or "00000000-0000-0000-0000-000000000000"
        self._connection.execute(
            "INSERT OR IGNORE INTO canonical_content_version_diffs (id, org_id, canonical_content_id, from_version_id, to_version_id, diff_hash, created_by, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (result["id"], tenant, content_id, before_row["id"], after_row["id"], diff_hash, creator, result["created_at"], _json(result)),
        )
        self._connection.commit()
        return result

    compare_versions = diff_versions

    def list_versions(
        self,
        *,
        org_id: UUID | str,
        canonical_content_id: UUID | str,
        from_version_id: UUID | str | None = None,
        to_version_id: UUID | str | None = None,
        from_version_no: int | None = None,
        to_version_no: int | None = None,
    ) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        content_id = _uuid(canonical_content_id, "canonical_content_id")
        assert tenant is not None and content_id is not None
        self._fetch_root(tenant, content_id)
        rows = self._connection.execute(
            "SELECT payload FROM canonical_content_versions WHERE org_id = ? AND canonical_content_id = ? ORDER BY version_no, id",
            (tenant, content_id),
        ).fetchall()
        versions = [json.loads(row["payload"]) for row in rows]
        result: dict[str, Any] = {"canonical_content_id": content_id, "versions": versions}
        if any(value is not None for value in (from_version_id, to_version_id, from_version_no, to_version_no)):
            result["diff"] = self.diff_versions(
                org_id=tenant, canonical_content_id=content_id,
                from_version_id=from_version_id, to_version_id=to_version_id,
                from_version_no=from_version_no, to_version_no=to_version_no,
            )
        return result

    version_history = list_versions

    def update_version(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly reject an update-shaped command; versions are append-only."""
        raise CanonicalContentError("IMMUTABLE_VERSION", "CanonicalContentVersion is immutable; create a new version")

    def _fetch_root(self, tenant: str, content_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM canonical_contents WHERE org_id = ? AND id = ?", (tenant, content_id)
        ).fetchone()
        if row is None:
            raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "canonical content is not in this organization")
        return row

    def _fetch_version(self, tenant: str, version_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM canonical_content_versions WHERE org_id = ? AND id = ?", (tenant, version_id)
        ).fetchone()
        if row is None:
            raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "canonical content version is not in this organization")
        return row

    def _ensure_refresh_queue(
        self, *, tenant: str, content_id: str, version_id: str, reason: str, priority: int,
        actor: str, trace: str, now: str, available_at: str | None = None,
    ) -> dict[str, Any]:
        if reason not in {"review_due", "stale", "expired", "conflict", "manual"}:
            raise CanonicalContentError("INVALID_REFRESH_REQUEST", "refresh reason is invalid")
        if type(priority) is not int or not 0 <= priority <= 100:
            raise CanonicalContentError("INVALID_REFRESH_REQUEST", "priority must be between 0 and 100")
        existing = self._connection.execute(
            "SELECT payload FROM canonical_refresh_queue WHERE org_id = ? AND canonical_content_version_id = ? "
            "AND reason = ? AND status IN ('queued', 'claimed') ORDER BY created_at, id LIMIT 1",
            (tenant, version_id, reason),
        ).fetchone()
        if existing is not None:
            return json.loads(existing["payload"])
        queue_id = str(uuid4())
        available = available_at or now
        queue = {
            "id": queue_id, "org_id": tenant, "canonical_content_id": content_id,
            "canonical_content_version_id": version_id, "reason": reason, "priority": priority,
            "status": "queued", "attempts": 0, "available_at": available,
            "lease_owner": None, "lease_until": None, "created_by": actor,
            "created_at": now, "updated_at": now,
        }
        self._connection.execute(
            "INSERT INTO canonical_refresh_queue (id, org_id, canonical_content_id, canonical_content_version_id, reason, priority, status, attempts, available_at, lease_owner, lease_until, created_by, created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, NULL, NULL, ?, ?, ?, ?)",
            (queue_id, tenant, content_id, version_id, reason, priority, available, actor, now, now, _json(queue)),
        )
        return queue

    def _insert_version(self, *, tenant: str, actor: str, trace: str, key: str, root: sqlite3.Row,
                        brief: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
        current = self._connection.execute(
            "SELECT * FROM canonical_content_versions WHERE org_id = ? AND canonical_content_id = ? ORDER BY version_no DESC LIMIT 1",
            (tenant, root["id"]),
        ).fetchone()
        next_no = int(current["version_no"]) + 1 if current is not None else 1
        supersedes = str(current["id"]) if current is not None else None
        normalized = self._normalize_version(
            tenant=tenant, brief=brief, values={**dict(values), "canonical_content_id": root["id"]},
            actor=actor, supersedes_version_id=supersedes,
        )
        normalized["version_no"] = next_no
        normalized["canonical_content_id"] = str(root["id"])
        self._validate(VERSION_VALIDATOR, normalized, "INVALID_CANONICAL_VERSION")
        duplicate = self._connection.execute(
            "SELECT * FROM canonical_content_versions WHERE org_id = ? AND canonical_content_id = ? AND content_hash = ? LIMIT 1",
            (tenant, root["id"], normalized["content_hash"]),
        ).fetchone()
        if duplicate is not None:
            return self._version_payload(duplicate)
        self._connection.execute(
            "INSERT INTO canonical_content_versions (id, org_id, canonical_content_id, topic_brief_id, version_no, title, abstract, sections_json, claims_json, code_blocks_json, examples_json, limitations_json, source_snapshot_refs_json, knowledge_core_version_id, topic_brief_status, topic_brief_lock_hash, input_snapshot_hash, content_hash, rights_snapshot_ids_json, supersedes_version_id, freshness_status, freshness_checked_at, freshness_expires_at, conflict_set_ids_json, refresh_required, status, created_by, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                normalized["id"], tenant, root["id"], normalized["topic_brief_id"], next_no,
                normalized["title"], normalized["abstract"], _json(normalized["sections"]), _json(normalized["claims"]),
                _json(normalized["code_blocks"]), _json(normalized["examples"]), _json(normalized["limitations"]),
                _json(normalized["source_snapshot_refs"]), normalized["knowledge_core_version_id"],
                normalized["topic_brief_status"], normalized["topic_brief_lock_hash"],
                normalized["input_snapshot_hash"], normalized["content_hash"], _json(normalized["rights_snapshot_ids"]),
                supersedes, normalized["freshness_status"], normalized["freshness_checked_at"], normalized["freshness_expires_at"],
                _json(normalized["conflict_set_ids"]), int(normalized["refresh_required"]), "draft", actor, normalized["created_at"], _json(normalized),
            ),
        )
        for item in normalized["claims"]:
            self._connection.execute(
                "INSERT INTO canonical_claims (org_id, canonical_content_version_id, claim_key, claim_id, priority, evidence_ids_json, rights_snapshot_ids_json, position, claim_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (tenant, normalized["id"], item["key"], item.get("claim_id"), item.get("priority", "normal"),
                 _json(item.get("evidence_ids", [])), _json(item.get("rights_snapshot_ids", [])), item["position"],
                 _json(item), actor, normalized["created_at"]),
            )
        self._event(
            tenant=tenant, aggregate_id=normalized["id"], version=next_no,
            event_type="canonical.version.created", actor=actor, trace=trace, key=key,
            payload={"from_state": None, "to_state": "draft", "command": "create", "snapshot_hash": normalized["content_hash"]},
        )
        now = _now()
        root_payload = self._root_payload(root)
        root_payload.update(current_version_id=normalized["id"], updated_at=now)
        self._connection.execute(
            "UPDATE canonical_contents SET current_version_id = ?, updated_at = ?, payload = ? WHERE org_id = ? AND id = ?",
            (normalized["id"], now, _json(root_payload), tenant, root["id"]),
        )
        if normalized["refresh_required"]:
            self._ensure_refresh_queue(
                tenant=tenant, content_id=str(root["id"]), version_id=normalized["id"],
                reason=normalized["freshness_status"], priority=20 if normalized["freshness_status"] == "conflict" else 50,
                actor=actor, trace=trace, now=now,
            )
        return normalized

    def create(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        topic_brief_id: UUID | str,
        stable_key: str | None = None,
        version: Mapping[str, Any] | None = None,
        **version_fields: Any,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        brief_id = _uuid(topic_brief_id, "topic_brief_id")
        assert brief_id is not None
        stable = _text(stable_key or f"canonical-{brief_id[:8]}", "stable_key", 256)
        supplied_version = dict(version or {})
        supplied_version.update({k: v for k, v in version_fields.items() if v is not None})
        digest = _hash({"topic_brief_id": brief_id, "stable_key": stable, "version": supplied_version})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                brief = self._topic_brief(tenant, brief_id)
                if self._connection.execute(
                    "SELECT 1 FROM canonical_contents WHERE org_id = ? AND stable_key = ?", (tenant, stable)
                ).fetchone() is not None:
                    raise CanonicalContentError("CANONICAL_CONTENT_EXISTS", "stable_key already exists in this organization")
                now = _now()
                root = {
                    "id": str(uuid4()), "org_id": tenant, "topic_brief_id": brief_id,
                    "stable_key": stable, "current_version_id": None, "status": "draft",
                    "created_by": actor, "created_at": now, "updated_at": now,
                }
                self._validate(CONTENT_VALIDATOR, root, "INVALID_CANONICAL_CONTENT")
                self._connection.execute(
                    "INSERT INTO canonical_contents (id, org_id, topic_brief_id, stable_key, current_version_id, status, created_by, created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (root["id"], tenant, brief_id, stable, None, "draft", actor, now, now, _json(root)),
                )
                row = self._fetch_root(tenant, root["id"])
                created_version = None
                if supplied_version:
                    created_version = self._insert_version(
                        tenant=tenant, actor=actor, trace=trace, key=key, root=row, brief=brief, values=supplied_version
                    )
                    row = self._fetch_root(tenant, root["id"])
                    root = self._root_payload(row)
                response = {"content": root, "canonical_content": root, "version": created_version}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    create_content = create

    def create_version(
        self,
        *,
        org_id: UUID | str,
        canonical_content_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        content: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        content_id = _uuid(canonical_content_id, "canonical_content_id")
        assert content_id is not None
        values = dict(content or {})
        values.update({k: v for k, v in fields.items() if v is not None})
        digest = _hash({"canonical_content_id": content_id, "content": values})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                root_row = self._fetch_root(tenant, content_id)
                brief_id = _uuid(values.get("topic_brief_id", root_row["topic_brief_id"]), "topic_brief_id")
                assert brief_id is not None
                if brief_id != root_row["topic_brief_id"]:
                    raise CanonicalContentError("TOPIC_BRIEF_MISMATCH", "version TopicBrief differs from canonical root")
                brief = self._topic_brief(tenant, brief_id)
                if values.get("version_id") is not None:
                    raise CanonicalContentError("IMMUTABLE_VERSION", "existing versions cannot be modified")
                version = self._insert_version(
                    tenant=tenant, actor=actor, trace=trace, key=key, root=root_row, brief=brief, values=values
                )
                root = self._root_payload(self._fetch_root(tenant, content_id))
                response = {"content": root, "canonical_content": root, "version": version}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    append_version = create_version

    def submit_review(
        self,
        *,
        org_id: UUID | str,
        canonical_content_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        content_id = _uuid(canonical_content_id, "canonical_content_id")
        assert content_id is not None
        if expected_version is not None and (type(expected_version) is not int or expected_version < 1):
            raise CanonicalContentError("VERSION_CONFLICT", "expected_version must be a positive integer")
        digest = _hash({"canonical_content_id": content_id, "expected_version": expected_version})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                root_row = self._fetch_root(tenant, content_id)
                if root_row["current_version_id"] is None:
                    raise CanonicalContentError("VERSION_CONFLICT", "a version is required before review")
                version_row = self._fetch_version(tenant, root_row["current_version_id"])
                if expected_version is not None and int(version_row["version_no"]) != expected_version:
                    raise CanonicalContentError("VERSION_CONFLICT", "canonical version changed")
                if root_row["status"] in {"in_review", "approved"}:
                    response = {"content": self._root_payload(root_row), "canonical_content": self._root_payload(root_row), "version": self._version_payload(version_row)}
                    self._save_command(tenant, key, digest, actor, trace, response)
                    self._connection.commit()
                    return response
                root = self._root_payload(root_row)
                old_status = root["status"]
                root.update(status="in_review", updated_at=_now())
                self._connection.execute(
                    "UPDATE canonical_contents SET status = 'in_review', updated_at = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (root["updated_at"], _json(root), tenant, content_id),
                )
                self._event(
                    tenant=tenant, aggregate_id=version_row["id"], version=int(version_row["version_no"]),
                    event_type="canonical.evidence_requested", actor=actor, trace=trace, key=key,
                    payload={"from_state": old_status, "to_state": "evidence_pending", "command": "submit_review", "snapshot_hash": version_row["content_hash"]},
                )
                response = {"content": root, "canonical_content": root, "version": self._version_payload(version_row)}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    submit_for_review = submit_review

    def assess_freshness(
        self, *, org_id: UUID | str, canonical_content_id: UUID | str,
        actor_id: UUID | str, trace_id: str, idempotency_key: str,
        version_id: UUID | str | None = None, version_no: int | None = None,
        now: str | datetime | None = None, force_stale: bool = False,
        conflict_set_ids: Iterable[object] | None = None,
        review_window_seconds: int = 7 * 24 * 60 * 60,
    ) -> dict[str, Any]:
        """Append a deterministic freshness check and enqueue non-fresh content."""
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        content_id = _uuid(canonical_content_id, "canonical_content_id")
        assert content_id is not None
        if type(review_window_seconds) is not int or review_window_seconds < 0 or review_window_seconds > 3650 * 86400:
            raise CanonicalContentError("INVALID_REFRESH_REQUEST", "review_window_seconds is invalid")
        if isinstance(now, datetime):
            checked_at = now.astimezone(timezone.utc)
        else:
            checked_at = _parse_time(now, "now") or datetime.now(timezone.utc)
        checked = _stamp(checked_at)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._resolve_version_for_root(tenant, content_id, version_id=version_id, version_no=version_no)
                version = json.loads(row["payload"])
                conflict_ids = _uuid_list(
                    list(conflict_set_ids) if conflict_set_ids is not None else version.get("conflict_set_ids", []),
                    "conflict_set_ids",
                )
                expires_at = _parse_time(version.get("freshness_expires_at"), "freshness_expires_at")
                if force_stale:
                    freshness_status, reason = "stale", "stale"
                elif conflict_ids:
                    freshness_status, reason = "conflict", "conflict"
                elif expires_at is None or expires_at <= checked_at:
                    freshness_status, reason = "expired", "expired"
                elif (expires_at - checked_at).total_seconds() <= review_window_seconds:
                    freshness_status, reason = "review_due", "review_due"
                else:
                    freshness_status, reason = "fresh", "fresh"
                digest = _hash({
                    "operation": "assess_freshness", "canonical_content_id": content_id,
                    "version_id": row["id"], "version_no": row["version_no"], "checked_at": checked,
                    "force_stale": force_stale, "conflict_set_ids": conflict_ids,
                    "review_window_seconds": review_window_seconds,
                })
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                check_id = str(uuid4())
                check = {
                    "id": check_id, "org_id": tenant, "canonical_content_id": content_id,
                    "canonical_content_version_id": str(row["id"]), "freshness_status": freshness_status,
                    "checked_at": checked, "expires_at": _stamp(expires_at) if expires_at else None,
                    "conflict_set_ids": conflict_ids, "reason": reason, "created_by": actor,
                    "trace_id": trace, "created_at": _now(),
                }
                self._connection.execute(
                    "INSERT INTO canonical_freshness_checks (id, org_id, canonical_content_id, canonical_content_version_id, freshness_status, checked_at, expires_at, conflict_set_ids_json, reason, created_by, trace_id, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (check_id, tenant, content_id, row["id"], freshness_status, checked, check["expires_at"], _json(conflict_ids), reason, actor, trace, check["created_at"], _json(check)),
                )
                queue = None
                if freshness_status != "fresh":
                    queue = self._ensure_refresh_queue(
                        tenant=tenant, content_id=content_id, version_id=str(row["id"]), reason=reason,
                        priority=20 if freshness_status == "conflict" else 50, actor=actor, trace=trace, now=check["created_at"],
                    )
                event = self._event(
                    tenant=tenant, aggregate_id=str(row["id"]), version=int(row["version_no"]),
                    event_type="canonical.freshness.assessed", actor=actor, trace=trace, key=key,
                    payload={"from_state": version.get("freshness_status", "fresh"), "to_state": freshness_status,
                             "command": "assess_freshness", "check_id": check_id, "reason": reason,
                             "conflict_set_ids": conflict_ids},
                )
                response = {"version": self._version_payload(row), "check": check, "refresh_queue": queue, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    check_freshness = assess_freshness

    def mark_stale(
        self, *, org_id: UUID | str, canonical_content_id: UUID | str,
        actor_id: UUID | str, trace_id: str, idempotency_key: str,
        version_id: UUID | str | None = None, version_no: int | None = None,
        now: str | datetime | None = None,
    ) -> dict[str, Any]:
        return self.assess_freshness(
            org_id=org_id, canonical_content_id=canonical_content_id, actor_id=actor_id,
            trace_id=trace_id, idempotency_key=idempotency_key, version_id=version_id,
            version_no=version_no, now=now, force_stale=True,
        )

    def enqueue_refresh(
        self, *, org_id: UUID | str, canonical_content_id: UUID | str,
        actor_id: UUID | str, trace_id: str, idempotency_key: str,
        version_id: UUID | str | None = None, version_no: int | None = None,
        reason: str = "manual", priority: int = 50, available_at: str | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        content_id = _uuid(canonical_content_id, "canonical_content_id")
        assert content_id is not None
        available = _parse_time(available_at, "available_at") if available_at is not None else None
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._resolve_version_for_root(tenant, content_id, version_id=version_id, version_no=version_no)
                digest = _hash({"operation": "enqueue_refresh", "canonical_content_id": content_id, "version_id": row["id"], "reason": reason, "priority": priority, "available_at": _stamp(available) if available else None})
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                now_value = _now()
                queue = self._ensure_refresh_queue(
                    tenant=tenant, content_id=content_id, version_id=str(row["id"]), reason=reason,
                    priority=priority, actor=actor, trace=trace, now=now_value,
                    available_at=_stamp(available) if available else None,
                )
                event = self._event(
                    tenant=tenant, aggregate_id=str(row["id"]), version=int(row["version_no"]),
                    event_type="canonical.refresh.queued", actor=actor, trace=trace, key=key,
                    payload={"command": "enqueue_refresh", "queue_id": queue["id"], "reason": reason},
                )
                response = {"refresh_queue": queue, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    queue_refresh = enqueue_refresh

    def claim_refresh(
        self, *, org_id: UUID | str, queue_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, lease_seconds: int = 300,
        now: str | datetime | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(queue_id, "queue_id")
        assert identity is not None
        if type(lease_seconds) is not int or lease_seconds < 1 or lease_seconds > 86400:
            raise CanonicalContentError("INVALID_REFRESH_REQUEST", "lease_seconds is invalid")
        claimed_at = now.astimezone(timezone.utc) if isinstance(now, datetime) else (_parse_time(now, "now") or datetime.now(timezone.utc))
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute("SELECT * FROM canonical_refresh_queue WHERE org_id = ? AND id = ?", (tenant, identity)).fetchone()
                if row is None:
                    raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "refresh queue item is not in this organization")
                digest = _hash({"operation": "claim_refresh", "queue_id": identity, "lease_seconds": lease_seconds, "now": _stamp(claimed_at)})
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                active_lease = _parse_time(row["lease_until"], "lease_until") if row["lease_until"] else None
                if row["status"] == "completed" or row["status"] == "cancelled" or (row["status"] == "claimed" and active_lease and active_lease > claimed_at and row["lease_owner"] != actor):
                    raise CanonicalContentError("REFRESH_QUEUE_NOT_CLAIMABLE", "refresh queue item is not claimable")
                available = _parse_time(row["available_at"], "available_at")
                if available and available > claimed_at:
                    raise CanonicalContentError("REFRESH_QUEUE_NOT_CLAIMABLE", "refresh queue item is not available")
                lease_until = claimed_at + timedelta(seconds=lease_seconds)
                payload = json.loads(row["payload"])
                queue = dict(payload, status="claimed", attempts=int(row["attempts"]) + 1, lease_owner=actor, lease_until=_stamp(lease_until), updated_at=_stamp(claimed_at))
                self._connection.execute(
                    "UPDATE canonical_refresh_queue SET status = 'claimed', attempts = ?, lease_owner = ?, lease_until = ?, updated_at = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (queue["attempts"], actor, queue["lease_until"], queue["updated_at"], _json(queue), tenant, identity),
                )
                response = {"refresh_queue": queue}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def complete_refresh(
        self, *, org_id: UUID | str, queue_id: UUID | str, actor_id: UUID | str,
        trace_id: str, idempotency_key: str, expected_attempts: int | None = None,
        now: str | datetime | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(queue_id, "queue_id")
        assert identity is not None
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute("SELECT * FROM canonical_refresh_queue WHERE org_id = ? AND id = ?", (tenant, identity)).fetchone()
                if row is None:
                    raise CanonicalContentError("TENANT_SCOPE_VIOLATION", "refresh queue item is not in this organization")
                digest = _hash({"operation": "complete_refresh", "queue_id": identity, "expected_attempts": expected_attempts})
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                completed_at = now.astimezone(timezone.utc) if isinstance(now, datetime) else (_parse_time(now, "now") or datetime.now(timezone.utc))
                lease_until = _parse_time(row["lease_until"], "lease_until") if row["lease_until"] else None
                if row["status"] != "claimed" or row["lease_owner"] != actor or (lease_until is not None and lease_until <= completed_at):
                    raise CanonicalContentError("REFRESH_QUEUE_NOT_CLAIMABLE", "refresh queue item is not claimed by this worker")
                if expected_attempts is not None and row["attempts"] != expected_attempts:
                    raise CanonicalContentError("VERSION_CONFLICT", "refresh attempt changed")
                payload = json.loads(row["payload"])
                queue = dict(payload, status="completed", lease_owner=None, lease_until=None, updated_at=_stamp(completed_at))
                self._connection.execute(
                    "UPDATE canonical_refresh_queue SET status = 'completed', lease_owner = NULL, lease_until = NULL, updated_at = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (queue["updated_at"], _json(queue), tenant, identity),
                )
                response = {"refresh_queue": queue}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def list_refresh_queue(
        self, *, org_id: UUID | str, status: str | None = None,
        canonical_content_version_id: UUID | str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        params: list[Any] = [tenant]
        query = "SELECT payload FROM canonical_refresh_queue WHERE org_id = ?"
        if status is not None:
            if status not in {"queued", "claimed", "completed", "cancelled"}:
                raise CanonicalContentError("INVALID_REFRESH_REQUEST", "queue status is invalid")
            query += " AND status = ?"
            params.append(status)
        if canonical_content_version_id is not None:
            params.append(_uuid(canonical_content_version_id, "canonical_content_version_id"))
            query += " AND canonical_content_version_id = ?"
        query += " ORDER BY priority ASC, available_at ASC, created_at ASC, id ASC"
        return tuple(json.loads(row["payload"]) for row in self._connection.execute(query, tuple(params)).fetchall())

    refresh_queue = list_refresh_queue

    def get(self, *, org_id: UUID | str, canonical_content_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        identity = _uuid(canonical_content_id, "canonical_content_id")
        assert tenant is not None and identity is not None
        root = self._fetch_root(tenant, identity)
        payload = self._root_payload(root)
        if root["current_version_id"]:
            row = self._fetch_version(tenant, root["current_version_id"])
            payload["current_version"] = self._version_payload(row)
        return payload

    get_content = get

    def get_version(self, *, org_id: UUID | str, version_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        identity = _uuid(version_id, "version_id")
        assert tenant is not None and identity is not None
        return self._version_payload(self._fetch_version(tenant, identity))

    def list(self, *, org_id: UUID | str, status: str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        assert tenant is not None
        if status is None:
            rows = self._connection.execute(
                "SELECT payload FROM canonical_contents WHERE org_id = ? ORDER BY created_at, id", (tenant,)
            ).fetchall()
        else:
            if status not in {"draft", "in_review", "approved", "archived"}:
                raise CanonicalContentError("INVALID_CANONICAL_COMMAND", "status is invalid")
            rows = self._connection.execute(
                "SELECT payload FROM canonical_contents WHERE org_id = ? AND status = ? ORDER BY created_at, id", (tenant, status)
            ).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    list_contents = list

    def events(self, *, org_id: UUID | str, aggregate_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        assert tenant is not None
        if aggregate_id is None:
            rows = self._connection.execute(
                "SELECT envelope FROM canonical_events WHERE org_id = ? ORDER BY event_id", (tenant,)
            ).fetchall()
        else:
            identity = _uuid(aggregate_id, "aggregate_id")
            assert identity is not None
            rows = self._connection.execute(
                "SELECT envelope FROM canonical_events WHERE org_id = ? AND aggregate_id = ? ORDER BY sequence, event_id",
                (tenant, identity),
            ).fetchall()
        return tuple(json.loads(row["envelope"]) for row in rows)


CanonicalContentStore = CanonicalContentService


__all__ = ["CanonicalContentError", "CanonicalContentService", "CanonicalContentStore"]
