"""Tenant-scoped Entity, Claim and Evidence use cases for KNOW-001.

The service is intentionally storage-port shaped and uses only the standard
library plus ``jsonschema``.  A composition root may pass the provenance
connection so source snapshots (and, when present, rights versions) are
checked in the same transaction.  No external platform or model is touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.knowledge_schema import initialize


ROOT = Path(__file__).resolve().parents[2]
ENTITY_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/entity.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
CLAIM_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/claim.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
EVIDENCE_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/evidence.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)

ENTITY_STATES = frozenset({"draft", "active", "retired"})
CLAIM_STATES = frozenset({"draft", "verified", "withdrawn"})
CLAIM_FRESHNESS = frozenset({"fresh", "review_due", "stale", "withdrawn"})
EVIDENCE_STATES = frozenset({"captured", "valid", "expired", "revoked"})
ENTITY_TRANSITIONS = {"activate": ("draft", "active", "entity.activated"),
                      "retire": ("active", "retired", "entity.retired")}
CLAIM_TRANSITIONS = {"verify": ("draft", "verified", "claim.verified"),
                     "withdraw": ("verified", "withdrawn", "claim.withdrawn")}
EVIDENCE_TRANSITIONS = {"validate": ("captured", "valid", "evidence.validated"),
                        "expire": ("valid", "expired", "evidence.invalidated"),
                        "revoke": ("valid", "revoked", "evidence.invalidated")}
SLUG = re.compile(r"^[a-z][a-z0-9_.-]*$")


class KnowledgeError(ValueError):
    """Stable, serializable error code for knowledge commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise KnowledgeError("INVALID_KNOWLEDGE_COMMAND", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise KnowledgeError("INVALID_KNOWLEDGE_COMMAND", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


def _optional_text(value: object, name: str, limit: int = 2048) -> str | None:
    if value is None:
        return None
    return _text(value, name, limit)


def _utc(value: str | datetime | None, name: str, *, default_now: bool = False) -> str | None:
    if value is None:
        return _now() if default_now else None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise KnowledgeError("INVALID_KNOWLEDGE_TIMESTAMP", f"{name} must be ISO-8601 UTC") from exc
    else:
        raise KnowledgeError("INVALID_KNOWLEDGE_TIMESTAMP", f"{name} must be ISO-8601 UTC")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise KnowledgeError("INVALID_KNOWLEDGE_TIMESTAMP", f"{name} must include UTC timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _list(value: Iterable[object] | None, name: str, *, limit: int = 256) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise KnowledgeError("INVALID_KNOWLEDGE_SCOPE", f"{name} must be an array")
    if len(value) > limit:
        raise KnowledgeError("INVALID_KNOWLEDGE_SCOPE", f"{name} has too many entries")
    result: list[str] = []
    for item in value:
        text = _text(item, name, 256)
        if text not in result:
            result.append(text)
    return result


def _uuid_list(value: Iterable[object] | None, name: str, *, required: bool = False) -> list[str]:
    if value is None:
        if required:
            raise KnowledgeError("INVALID_KNOWLEDGE_SCOPE", f"{name} must be a nonempty array")
        return []
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise KnowledgeError("INVALID_KNOWLEDGE_SCOPE", f"{name} must be an array")
    result: list[str] = []
    for item in value:
        identity = _uuid(item, name)
        if identity not in result:
            result.append(identity)
    if required and not result:
        raise KnowledgeError("INVALID_KNOWLEDGE_SCOPE", f"{name} must be a nonempty array")
    return result


def _slug(value: object, name: str) -> str:
    text = _text(value, name, 128).lower()
    if not SLUG.fullmatch(text):
        raise KnowledgeError("INVALID_FACT_TYPE", f"{name} must be a lowercase fact-type slug")
    return text


def _range(start: str | None, end: str | None, name: str = "validity") -> None:
    if start is not None and end is not None and start >= end:
        raise KnowledgeError("INVALID_KNOWLEDGE_TERM", f"{name} end must be after start")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class KnowledgeService:
    """Transactional Entity/Claim/Evidence command and query service."""

    def __init__(self, database: str | Path = ":memory:", *, connection: sqlite3.Connection | None = None) -> None:
        self._owns_connection = connection is None
        self._connection = connection or sqlite3.connect(str(database), timeout=30, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        initialize(self._connection)
        self._lock = RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        if self._owns_connection:
            self._connection.close()

    # ----- common command/event helpers ---------------------------------
    def _identity(self, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                  idempotency_key: str) -> tuple[str, str, str, str]:
        return (_uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"),
                _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200))

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM knowledge_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise KnowledgeError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str,
                      response: Mapping[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO knowledge_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, _json(response)),
        )

    def _event(self, *, tenant: str, aggregate_type: str, aggregate_id: str, event_type: str,
               actor: str, trace: str, key: str, version: int, payload: Mapping[str, Any]) -> dict[str, Any]:
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM knowledge_events "
            "WHERE org_id = ? AND aggregate_type = ? AND aggregate_id = ?",
            (tenant, aggregate_type, aggregate_id),
        ).fetchone()[0]
        event_payload = dict(payload)
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
            "aggregate_type": aggregate_type,
            "aggregate_id": aggregate_id,
            "aggregate_version": max(1, version),
            "actor_type": "user",
            "actor_id": actor,
            "idempotency_key": key,
            "payload": event_payload,
            "payload_hash": _hash(event_payload),
        }
        self._connection.execute(
            "INSERT INTO knowledge_events "
            "(event_id, org_id, aggregate_type, aggregate_id, event_type, sequence, envelope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, tenant, aggregate_type, aggregate_id, event_type, sequence, _json(envelope)),
        )
        return envelope

    @staticmethod
    def recompute_entity_hash(entity: Mapping[str, Any]) -> str:
        return _hash({
            "id": entity["id"], "org_id": entity["org_id"],
            "canonical_name": entity["canonical_name"], "aliases": entity["aliases"],
            "entity_type": entity["entity_type"], "created_by": entity["created_by"],
            "created_at": entity["created_at"],
        })

    @staticmethod
    def recompute_claim_hash(claim: Mapping[str, Any]) -> str:
        return _hash({
            "id": claim["id"], "org_id": claim["org_id"], "entity_ids": claim["entity_ids"],
            "statement": claim["statement"], "fact_type": claim["fact_type"],
            "applicable_versions": claim["applicable_versions"],
            "applicable_regions": claim["applicable_regions"],
            "applicable_locales": claim["applicable_locales"],
            "valid_from": claim["valid_from"], "valid_to": claim["valid_to"],
            "review_due_at": claim["review_due_at"], "supersedes_claim_id": claim["supersedes_claim_id"],
            "created_by": claim["created_by"], "created_at": claim["created_at"],
        })

    @staticmethod
    def recompute_evidence_hash(evidence: Mapping[str, Any]) -> str:
        return _hash({
            "id": evidence["id"], "org_id": evidence["org_id"],
            "source_snapshot_id": evidence["source_snapshot_id"],
            "rights_record_version_id": evidence["rights_record_version_id"],
            "evidence_type": evidence["evidence_type"], "quote": evidence["quote"],
            "locator": evidence["locator"], "applicable_versions": evidence["applicable_versions"],
            "applicable_regions": evidence["applicable_regions"],
            "applicable_locales": evidence["applicable_locales"],
            "valid_from": evidence["valid_from"], "valid_to": evidence["valid_to"],
            "review_due_at": evidence["review_due_at"], "captured_at": evidence["captured_at"],
            "created_by": evidence["created_by"], "created_at": evidence["created_at"],
        })

    @staticmethod
    def _validate(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> dict[str, Any]:
        result = dict(value)
        errors = sorted(validator.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            raise KnowledgeError(code, errors[0].message)
        return result

    def _fetch(self, table: str, tenant: str, identity: str, code: str) -> sqlite3.Row:
        row = self._connection.execute(
            f"SELECT * FROM {table} WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            # Do not reveal whether the id exists in another tenant.
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", f"{table[:-1]} is not in this organization")
        return row

    def _source_snapshot(self, tenant: str, snapshot_id: str) -> sqlite3.Row:
        try:
            row = self._connection.execute(
                "SELECT id, org_id, source_id, status, content_hash, captured_at, payload "
                "FROM source_snapshots WHERE org_id = ? AND id = ?", (tenant, snapshot_id)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise KnowledgeError("PROVENANCE_NOT_INITIALIZED", "source snapshot storage is unavailable") from exc
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "source snapshot is not in this organization")
        return row

    def _rights_version(self, tenant: str, version_id: str) -> sqlite3.Row:
        try:
            row = self._connection.execute(
                "SELECT id, org_id, status, permitted_use, permitted_regions, permitted_locales, "
                "permitted_media, valid_from, valid_to, payload FROM rights_record_versions "
                "WHERE org_id = ? AND id = ?", (tenant, version_id)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise KnowledgeError("RIGHTS_NOT_INITIALIZED", "rights version storage is unavailable") from exc
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
        return row

    # ----- Entity --------------------------------------------------------
    def create_entity(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                      idempotency_key: str, canonical_name: str | None = None,
                      aliases: Iterable[object] | None = None, entity_type: str = "concept",
                      name: str | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        canonical = _text(canonical_name if canonical_name is not None else name, "canonical_name", 512)
        alias_values = _list(aliases, "aliases")
        kind = _slug(entity_type, "entity_type")
        canonical_key = " ".join(canonical.casefold().split())
        digest = _hash({"operation": "create_entity", "canonical_name": canonical,
                        "aliases": alias_values, "entity_type": kind})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                duplicate = self._connection.execute(
                    "SELECT id FROM entities WHERE org_id = ? AND canonical_key = ?", (tenant, canonical_key)
                ).fetchone()
                if duplicate is not None:
                    raise KnowledgeError("ENTITY_ALREADY_EXISTS", "canonical entity already exists")
                entity_id, now = str(uuid4()), _now()
                entity = {
                    "id": entity_id, "org_id": tenant, "canonical_name": canonical,
                    "aliases": alias_values, "entity_type": kind, "status": "draft", "version": 0,
                    "created_by": actor, "created_at": now, "updated_at": now,
                }
                entity["content_hash"] = self.recompute_entity_hash(entity)
                self._validate(ENTITY_VALIDATOR, entity, "INVALID_ENTITY")
                self._connection.execute(
                    "INSERT INTO entities (id, org_id, canonical_key, canonical_name, aliases_json, entity_type, "
                    "status, version, content_hash, created_by, created_at, updated_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (entity_id, tenant, canonical_key, canonical, _json(alias_values), kind, "draft", 0,
                     entity["content_hash"], actor, now, now, _json(entity)),
                )
                event = self._event(
                    tenant=tenant, aggregate_type="Entity", aggregate_id=entity_id,
                    event_type="entity.created", actor=actor, trace=trace, key=key,
                    version=1, payload={"aggregate_id": entity_id, "aggregate_version": 1,
                                       "from_state": "none", "to_state": "draft",
                                       "snapshot_hash": entity["content_hash"], "command": "create"},
                )
                response = {"entity": entity, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except KnowledgeError:
                self._connection.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise KnowledgeError("ENTITY_ALREADY_EXISTS", "entity identity conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    create = create_entity

    def transition_entity(self, *, org_id: UUID | str, entity_id: UUID | str, actor_id: UUID | str,
                          trace_id: str, idempotency_key: str, action: str,
                          expected_version: int = 0, reason: str | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(entity_id, "entity_id")
        if action not in ENTITY_TRANSITIONS:
            raise KnowledgeError("INVALID_ENTITY_ACTION", "unsupported entity action")
        if type(expected_version) is not int or expected_version < 0:
            raise KnowledgeError("VERSION_CONFLICT", "expected_version must be nonnegative")
        normalized_reason = _optional_text(reason, "reason")
        if action == "retire" and normalized_reason is None:
            raise KnowledgeError("REASON_REQUIRED", "retiring an entity requires a reason")
        digest = _hash({"operation": "transition_entity", "entity_id": identity,
                        "action": action, "expected_version": expected_version,
                        "reason": normalized_reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._fetch("entities", tenant, identity, "TENANT_SCOPE_VIOLATION")
                if int(row["version"]) != expected_version:
                    raise KnowledgeError("VERSION_CONFLICT", "entity version changed")
                from_state, target, event_type = ENTITY_TRANSITIONS[action]
                if row["status"] != from_state:
                    raise KnowledgeError("INVALID_ENTITY_STATE", f"cannot {action} from {row['status']}")
                entity = json.loads(row["payload"])
                next_version = expected_version + 1
                entity.update(status=target, version=next_version, updated_at=_now())
                self._validate(ENTITY_VALIDATOR, entity, "INVALID_ENTITY")
                updated = self._connection.execute(
                    "UPDATE entities SET status = ?, version = ?, updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ? AND version = ?",
                    (target, next_version, entity["updated_at"], _json(entity), tenant, identity, expected_version),
                )
                if updated.rowcount != 1:
                    raise KnowledgeError("VERSION_CONFLICT", "entity changed while transitioning")
                event = self._event(
                    tenant=tenant, aggregate_type="Entity", aggregate_id=identity, event_type=event_type,
                    actor=actor, trace=trace, key=key, version=next_version,
                    payload={"aggregate_id": identity, "aggregate_version": next_version,
                             "from_state": from_state, "to_state": target, "command": action,
                             "reason": normalized_reason, "snapshot_hash": entity["content_hash"]},
                )
                response = {"entity": entity, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def activate_entity(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "activate"
        return self.transition_entity(**kwargs)

    def retire_entity(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "retire"
        return self.transition_entity(**kwargs)

    # ----- Claim ---------------------------------------------------------
    def _assert_entities(self, tenant: str, entity_ids: Sequence[str]) -> None:
        if not entity_ids:
            return
        placeholders = ",".join("?" for _ in entity_ids)
        rows = self._connection.execute(
            f"SELECT id, status FROM entities WHERE org_id = ? AND id IN ({placeholders})",
            (tenant, *entity_ids),
        ).fetchall()
        if len(rows) != len(entity_ids):
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "one or more entities are not in this organization")
        if any(row["status"] == "retired" for row in rows):
            raise KnowledgeError("ENTITY_RETIRED", "retired entities cannot back a new claim")

    def create_claim(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                     idempotency_key: str, entity_ids: Iterable[object] | None,
                     statement: str, fact_type: str = "fact",
                     applicable_versions: Iterable[object] | None = None,
                     applicable_regions: Iterable[object] | None = None,
                     applicable_locales: Iterable[object] | None = None,
                     valid_from: str | datetime | None = None, valid_to: str | datetime | None = None,
                     review_due_at: str | datetime | None = None,
                     supersedes_claim_id: UUID | str | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        entities = _uuid_list(entity_ids, "entity_ids")
        text = _text(statement, "statement", 8192)
        kind = _slug(fact_type, "fact_type")
        versions, regions, locales = (_list(applicable_versions, "applicable_versions"),
                                      _list(applicable_regions, "applicable_regions"),
                                      _list(applicable_locales, "applicable_locales"))
        start, end, review = (_utc(valid_from, "valid_from"), _utc(valid_to, "valid_to"),
                              _utc(review_due_at, "review_due_at"))
        _range(start, end)
        if review is not None and end is not None and review > end:
            raise KnowledgeError("INVALID_KNOWLEDGE_TERM", "review_due_at cannot be after valid_to")
        supersedes = None if supersedes_claim_id is None else _uuid(supersedes_claim_id, "supersedes_claim_id")
        digest = _hash({"operation": "create_claim", "entity_ids": entities, "statement": text,
                        "fact_type": kind, "applicable_versions": versions,
                        "applicable_regions": regions, "applicable_locales": locales,
                        "valid_from": start, "valid_to": end, "review_due_at": review,
                        "supersedes_claim_id": supersedes})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                self._assert_entities(tenant, entities)
                if supersedes is not None:
                    self._fetch("claims", tenant, supersedes, "TENANT_SCOPE_VIOLATION")
                claim_id, now = str(uuid4()), _now()
                claim = {
                    "id": claim_id, "org_id": tenant, "entity_ids": entities, "statement": text,
                    "fact_type": kind, "applicable_versions": versions, "applicable_regions": regions,
                    "applicable_locales": locales, "valid_from": start, "valid_to": end,
                    "review_due_at": review, "supersedes_claim_id": supersedes,
                    "freshness_status": "fresh", "status": "draft", "version": 0,
                    "created_by": actor, "created_at": now, "updated_at": now,
                }
                claim["content_hash"] = self.recompute_claim_hash(claim)
                self._validate(CLAIM_VALIDATOR, claim, "INVALID_CLAIM")
                self._connection.execute(
                    "INSERT INTO claims (id, org_id, statement, fact_type, entity_ids_json, "
                    "applicable_versions_json, applicable_regions_json, applicable_locales_json, valid_from, valid_to, "
                    "review_due_at, supersedes_claim_id, freshness_status, status, version, content_hash, created_by, "
                    "created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (claim_id, tenant, text, kind, _json(entities), _json(versions), _json(regions), _json(locales),
                     start, end, review, supersedes, "fresh", "draft", 0, claim["content_hash"], actor, now, now, _json(claim)),
                )
                for entity_id in entities:
                    self._connection.execute(
                        "INSERT INTO entity_claims (org_id, entity_id, claim_id, created_by, created_at, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (tenant, entity_id, claim_id, actor, now,
                         _json({"org_id": tenant, "entity_id": entity_id, "claim_id": claim_id,
                                "created_by": actor, "created_at": now})),
                    )
                event = self._event(
                    tenant=tenant, aggregate_type="Claim", aggregate_id=claim_id,
                    event_type="claim.created", actor=actor, trace=trace, key=key, version=1,
                    payload={"aggregate_id": claim_id, "aggregate_version": 1, "from_state": "none",
                             "to_state": "draft", "command": "create", "snapshot_hash": claim["content_hash"]},
                )
                response = {"claim": claim, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except KnowledgeError:
                self._connection.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise KnowledgeError("CLAIM_CONFLICT", "claim identity or relation conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    def transition_claim(self, *, org_id: UUID | str, claim_id: UUID | str, actor_id: UUID | str,
                         trace_id: str, idempotency_key: str, action: str,
                         expected_version: int = 0, reason: str | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(claim_id, "claim_id")
        if action not in CLAIM_TRANSITIONS:
            raise KnowledgeError("INVALID_CLAIM_ACTION", "unsupported claim action")
        if type(expected_version) is not int or expected_version < 0:
            raise KnowledgeError("VERSION_CONFLICT", "expected_version must be nonnegative")
        normalized_reason = _optional_text(reason, "reason")
        if action == "withdraw" and normalized_reason is None:
            raise KnowledgeError("REASON_REQUIRED", "withdrawing a claim requires a reason")
        digest = _hash({"operation": "transition_claim", "claim_id": identity,
                        "action": action, "expected_version": expected_version,
                        "reason": normalized_reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._fetch("claims", tenant, identity, "TENANT_SCOPE_VIOLATION")
                if int(row["version"]) != expected_version:
                    raise KnowledgeError("VERSION_CONFLICT", "claim version changed")
                from_state, target, event_type = CLAIM_TRANSITIONS[action]
                if row["status"] != from_state:
                    raise KnowledgeError("INVALID_CLAIM_STATE", f"cannot {action} from {row['status']}")
                if action == "verify":
                    evidence_count = self._connection.execute(
                        "SELECT COUNT(*) FROM claim_evidences ce JOIN evidences e "
                        "ON e.org_id = ce.org_id AND e.id = ce.evidence_id "
                        "WHERE ce.org_id = ? AND ce.claim_id = ? AND e.status = 'valid'",
                        (tenant, identity),
                    ).fetchone()[0]
                    if evidence_count < 1:
                        # Compatibility with an imported projection that only
                        # populated Evidence.claim_id; relation writes still
                        # remain the source of truth for new commands.
                        evidence_count = self._connection.execute(
                            "SELECT COUNT(*) FROM evidences WHERE org_id = ? AND claim_id = ? AND status = 'valid'",
                            (tenant, identity),
                        ).fetchone()[0]
                    if evidence_count < 1:
                        raise KnowledgeError("CLAIM_EVIDENCE_REQUIRED", "a claim needs at least one valid evidence")
                claim = json.loads(row["payload"])
                next_version = expected_version + 1
                claim.update(status=target, version=next_version, updated_at=_now())
                if target == "withdrawn":
                    claim["freshness_status"] = "withdrawn"
                self._validate(CLAIM_VALIDATOR, claim, "INVALID_CLAIM")
                updated = self._connection.execute(
                    "UPDATE claims SET status = ?, freshness_status = ?, version = ?, updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ? AND version = ?",
                    (target, claim["freshness_status"], next_version, claim["updated_at"], _json(claim),
                     tenant, identity, expected_version),
                )
                if updated.rowcount != 1:
                    raise KnowledgeError("VERSION_CONFLICT", "claim changed while transitioning")
                event = self._event(
                    tenant=tenant, aggregate_type="Claim", aggregate_id=identity, event_type=event_type,
                    actor=actor, trace=trace, key=key, version=next_version,
                    payload={"aggregate_id": identity, "aggregate_version": next_version,
                             "from_state": from_state, "to_state": target, "command": action,
                             "reason": normalized_reason, "snapshot_hash": claim["content_hash"]},
                )
                response = {"claim": claim, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def verify_claim(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "verify"
        return self.transition_claim(**kwargs)

    def withdraw_claim(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "withdraw"
        return self.transition_claim(**kwargs)

    def mark_claim_freshness(self, *, org_id: UUID | str, claim_id: UUID | str, actor_id: UUID | str,
                             trace_id: str, idempotency_key: str, freshness_status: str,
                             expected_version: int, reason: str | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(claim_id, "claim_id")
        if freshness_status not in {"fresh", "review_due", "stale"}:
            raise KnowledgeError("INVALID_CLAIM_FRESHNESS", "freshness_status is invalid")
        if type(expected_version) is not int or expected_version < 0:
            raise KnowledgeError("VERSION_CONFLICT", "expected_version must be nonnegative")
        normalized_reason = _optional_text(reason, "reason")
        digest = _hash({"operation": "mark_claim_freshness", "claim_id": identity,
                        "freshness_status": freshness_status, "expected_version": expected_version,
                        "reason": normalized_reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._fetch("claims", tenant, identity, "TENANT_SCOPE_VIOLATION")
                if row["status"] != "verified":
                    raise KnowledgeError("INVALID_CLAIM_STATE", "only verified claims can change freshness")
                if int(row["version"]) != expected_version:
                    raise KnowledgeError("VERSION_CONFLICT", "claim version changed")
                claim = json.loads(row["payload"])
                next_version = expected_version + 1
                claim.update(freshness_status=freshness_status, version=next_version, updated_at=_now())
                self._validate(CLAIM_VALIDATOR, claim, "INVALID_CLAIM")
                self._connection.execute(
                    "UPDATE claims SET freshness_status = ?, version = ?, updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ? AND version = ?",
                    (freshness_status, next_version, claim["updated_at"], _json(claim), tenant, identity, expected_version),
                )
                event = self._event(
                    tenant=tenant, aggregate_type="Claim", aggregate_id=identity,
                    event_type="claim.freshness.changed", actor=actor, trace=trace, key=key,
                    version=next_version,
                    payload={"aggregate_id": identity, "aggregate_version": next_version,
                             "from_state": row["freshness_status"], "to_state": freshness_status,
                             "command": "mark_freshness", "reason": normalized_reason,
                             "snapshot_hash": claim["content_hash"]},
                )
                response = {"claim": claim, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    # ----- Evidence ------------------------------------------------------
    def create_evidence(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                        idempotency_key: str, source_snapshot_id: UUID | str,
                        quote: str, locator: str | None = None, claim_id: UUID | str | None = None,
                        rights_record_version_id: UUID | str | None = None,
                        evidence_type: str = "quote",
                        applicable_versions: Iterable[object] | None = None,
                        applicable_regions: Iterable[object] | None = None,
                        applicable_locales: Iterable[object] | None = None,
                        valid_from: str | datetime | None = None, valid_to: str | datetime | None = None,
                        review_due_at: str | datetime | None = None,
                        captured_at: str | datetime | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        snapshot = _uuid(source_snapshot_id, "source_snapshot_id")
        claim = None if claim_id is None else _uuid(claim_id, "claim_id")
        rights = None if rights_record_version_id is None else _uuid(rights_record_version_id, "rights_record_version_id")
        kind = _slug(evidence_type, "evidence_type")
        quote_text = _text(quote, "quote", 16384)
        location = _optional_text(locator, "locator", 2048)
        versions, regions, locales = (_list(applicable_versions, "applicable_versions"),
                                      _list(applicable_regions, "applicable_regions"),
                                      _list(applicable_locales, "applicable_locales"))
        start, end, review = (_utc(valid_from, "valid_from"), _utc(valid_to, "valid_to"),
                              _utc(review_due_at, "review_due_at"))
        _range(start, end)
        if review is not None and end is not None and review > end:
            raise KnowledgeError("INVALID_KNOWLEDGE_TERM", "review_due_at cannot be after valid_to")
        captured = _utc(captured_at, "captured_at", default_now=True)
        digest = _hash({"operation": "create_evidence", "source_snapshot_id": snapshot,
                        "claim_id": claim, "rights_record_version_id": rights, "evidence_type": kind,
                        "quote": quote_text, "locator": location, "applicable_versions": versions,
                        "applicable_regions": regions, "applicable_locales": locales,
                        "valid_from": start, "valid_to": end, "review_due_at": review,
                        "captured_at": captured if captured_at is not None else None})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                source_row = self._source_snapshot(tenant, snapshot)
                if source_row["status"] in {"expired", "revoked", "blocked"}:
                    raise KnowledgeError("SOURCE_SNAPSHOT_NOT_USABLE", "terminal source snapshot cannot back evidence")
                if claim is not None:
                    claim_row = self._fetch("claims", tenant, claim, "TENANT_SCOPE_VIOLATION")
                    if claim_row["status"] == "withdrawn":
                        raise KnowledgeError("CLAIM_WITHDRAWN", "withdrawn claim cannot receive evidence")
                if rights is not None:
                    self._rights_version(tenant, rights)
                evidence_id, now = str(uuid4()), _now()
                evidence = {
                    "id": evidence_id, "org_id": tenant, "source_snapshot_id": snapshot,
                    "claim_id": claim, "rights_record_version_id": rights, "evidence_type": kind,
                    "quote": quote_text, "locator": location, "applicable_versions": versions,
                    "applicable_regions": regions, "applicable_locales": locales,
                    "valid_from": start, "valid_to": end, "review_due_at": review,
                    "captured_at": captured, "status": "captured", "version": 0,
                    "created_by": actor, "created_at": now,
                }
                evidence["content_hash"] = self.recompute_evidence_hash(evidence)
                self._validate(EVIDENCE_VALIDATOR, evidence, "INVALID_EVIDENCE")
                self._connection.execute(
                    "INSERT INTO evidences (id, org_id, source_snapshot_id, claim_id, rights_record_version_id, "
                    "evidence_type, quote, locator, applicable_versions_json, applicable_regions_json, applicable_locales_json, "
                    "valid_from, valid_to, review_due_at, captured_at, status, version, content_hash, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (evidence_id, tenant, snapshot, claim, rights, kind, quote_text, location, _json(versions), _json(regions),
                     _json(locales), start, end, review, captured, "captured", 0, evidence["content_hash"], actor, now, _json(evidence)),
                )
                if claim is not None:
                    self._connection.execute(
                        "INSERT INTO claim_evidences (org_id, claim_id, evidence_id, relation_type, created_by, created_at, payload) "
                        "VALUES (?, ?, ?, 'supports', ?, ?, ?)",
                        (tenant, claim, evidence_id, actor, now,
                         _json({"org_id": tenant, "claim_id": claim, "evidence_id": evidence_id,
                                "relation_type": "supports", "created_by": actor, "created_at": now})),
                    )
                event = self._event(
                    tenant=tenant, aggregate_type="Evidence", aggregate_id=evidence_id,
                    event_type="evidence.captured", actor=actor, trace=trace, key=key, version=1,
                    payload={"aggregate_id": evidence_id, "aggregate_version": 1, "from_state": "none",
                             "to_state": "captured", "command": "create", "snapshot_hash": evidence["content_hash"],
                             "source_snapshot_id": snapshot, "claim_id": claim},
                )
                response = {"evidence": evidence, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except KnowledgeError:
                self._connection.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise KnowledgeError("EVIDENCE_CONFLICT", "evidence relation conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    def link_evidence(self, *, org_id: UUID | str, claim_id: UUID | str, evidence_id: UUID | str,
                      actor_id: UUID | str, trace_id: str, idempotency_key: str,
                      relation_type: str = "supports") -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        claim = _uuid(claim_id, "claim_id")
        evidence = _uuid(evidence_id, "evidence_id")
        relation = _slug(relation_type, "relation_type")
        digest = _hash({"operation": "link_evidence", "claim_id": claim,
                        "evidence_id": evidence, "relation_type": relation})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                claim_row = self._fetch("claims", tenant, claim, "TENANT_SCOPE_VIOLATION")
                evidence_row = self._fetch("evidences", tenant, evidence, "TENANT_SCOPE_VIOLATION")
                if claim_row["status"] == "withdrawn":
                    raise KnowledgeError("CLAIM_WITHDRAWN", "withdrawn claim cannot receive evidence")
                relation_payload = {"org_id": tenant, "claim_id": claim, "evidence_id": evidence,
                                    "relation_type": relation, "created_by": actor, "created_at": _now()}
                self._connection.execute(
                    "INSERT OR IGNORE INTO claim_evidences "
                    "(org_id, claim_id, evidence_id, relation_type, created_by, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tenant, claim, evidence, relation, actor, relation_payload["created_at"], _json(relation_payload)),
                )
                # claim_id is explicitly a compatibility projection.  The
                # relation row above remains the write-side fact source.
                if evidence_row["claim_id"] is None:
                    payload = json.loads(evidence_row["payload"])
                    payload["claim_id"] = claim
                    self._connection.execute(
                        "UPDATE evidences SET claim_id = ?, payload = ? WHERE org_id = ? AND id = ?",
                        (claim, _json(payload), tenant, evidence),
                    )
                response = {"claim_id": claim, "evidence_id": evidence, "relation_type": relation}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def transition_evidence(self, *, org_id: UUID | str, evidence_id: UUID | str,
                            actor_id: UUID | str, trace_id: str, idempotency_key: str,
                            action: str, expected_version: int = 0,
                            reason: str | None = None) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(evidence_id, "evidence_id")
        if action not in EVIDENCE_TRANSITIONS:
            raise KnowledgeError("INVALID_EVIDENCE_ACTION", "unsupported evidence action")
        if type(expected_version) is not int or expected_version < 0:
            raise KnowledgeError("VERSION_CONFLICT", "expected_version must be nonnegative")
        normalized_reason = _optional_text(reason, "reason")
        if action in {"expire", "revoke"} and normalized_reason is None:
            raise KnowledgeError("REASON_REQUIRED", "invalidating evidence requires a reason")
        digest = _hash({"operation": "transition_evidence", "evidence_id": identity,
                        "action": action, "expected_version": expected_version,
                        "reason": normalized_reason})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                row = self._fetch("evidences", tenant, identity, "TENANT_SCOPE_VIOLATION")
                if int(row["version"]) != expected_version:
                    raise KnowledgeError("VERSION_CONFLICT", "evidence version changed")
                from_state, target, event_type = EVIDENCE_TRANSITIONS[action]
                if row["status"] != from_state:
                    raise KnowledgeError("INVALID_EVIDENCE_STATE", f"cannot {action} from {row['status']}")
                if action == "validate":
                    source = self._source_snapshot(tenant, row["source_snapshot_id"])
                    if source["status"] != "usable":
                        raise KnowledgeError("SOURCE_SNAPSHOT_NOT_USABLE", "evidence requires a usable source snapshot")
                    if not row["locator"]:
                        raise KnowledgeError("EVIDENCE_LOCATOR_REQUIRED", "valid evidence requires a locator")
                    if row["rights_record_version_id"]:
                        rights = self._rights_version(tenant, row["rights_record_version_id"])
                        if rights["status"] != "verified":
                            raise KnowledgeError("RIGHTS_NOT_USABLE", "evidence rights version is not verified")
                evidence = json.loads(row["payload"])
                next_version = expected_version + 1
                evidence.update(status=target, version=next_version)
                if target in {"expired", "revoked"}:
                    evidence["review_due_at"] = evidence.get("review_due_at")
                self._validate(EVIDENCE_VALIDATOR, evidence, "INVALID_EVIDENCE")
                updated = self._connection.execute(
                    "UPDATE evidences SET status = ?, version = ?, payload = ? "
                    "WHERE org_id = ? AND id = ? AND version = ?",
                    (target, next_version, _json(evidence), tenant, identity, expected_version),
                )
                if updated.rowcount != 1:
                    raise KnowledgeError("VERSION_CONFLICT", "evidence changed while transitioning")
                event = self._event(
                    tenant=tenant, aggregate_type="Evidence", aggregate_id=identity, event_type=event_type,
                    actor=actor, trace=trace, key=key, version=next_version,
                    payload={"aggregate_id": identity, "aggregate_version": next_version,
                             "from_state": from_state, "to_state": target, "command": action,
                             "reason": normalized_reason, "snapshot_hash": evidence["content_hash"],
                             "source_snapshot_id": evidence["source_snapshot_id"]},
                )
                response = {"evidence": evidence, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    def validate_evidence(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "validate"
        return self.transition_evidence(**kwargs)

    def expire_evidence(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "expire"
        return self.transition_evidence(**kwargs)

    def revoke_evidence(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["action"] = "revoke"
        return self.transition_evidence(**kwargs)

    # ----- queries -------------------------------------------------------
    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        return json.loads(row["payload"])

    def get_entity(self, *, org_id: UUID | str, entity_id: UUID | str) -> dict[str, Any]:
        return self._payload(self._fetch("entities", _uuid(org_id, "org_id"), _uuid(entity_id, "entity_id"), "TENANT_SCOPE_VIOLATION"))

    def list_entities(self, *, org_id: UUID | str, status: str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        if status is None:
            rows = self._connection.execute("SELECT payload FROM entities WHERE org_id = ? ORDER BY canonical_key", (tenant,)).fetchall()
        else:
            if status not in ENTITY_STATES:
                raise KnowledgeError("INVALID_ENTITY_STATE", "status is invalid")
            rows = self._connection.execute("SELECT payload FROM entities WHERE org_id = ? AND status = ? ORDER BY canonical_key", (tenant, status)).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def get_claim(self, *, org_id: UUID | str, claim_id: UUID | str) -> dict[str, Any]:
        return self._payload(self._fetch("claims", _uuid(org_id, "org_id"), _uuid(claim_id, "claim_id"), "TENANT_SCOPE_VIOLATION"))

    def list_claims(self, *, org_id: UUID | str, status: str | None = None,
                    entity_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        params: list[Any] = [tenant]
        query = "SELECT c.payload FROM claims c"
        if entity_id is not None:
            query += " JOIN entity_claims ec ON ec.org_id = c.org_id AND ec.claim_id = c.id AND ec.entity_id = ?"
            params.append(_uuid(entity_id, "entity_id"))
        query += " WHERE c.org_id = ?"
        if entity_id is not None:
            params = [params[-1], tenant]  # entity predicate precedes tenant in JOIN
        if status is not None:
            if status not in CLAIM_STATES:
                raise KnowledgeError("INVALID_CLAIM_STATE", "status is invalid")
            query += " AND c.status = ?"
            params.append(status)
        query += " ORDER BY c.created_at, c.id"
        rows = self._connection.execute(query, tuple(params)).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    def get_evidence(self, *, org_id: UUID | str, evidence_id: UUID | str) -> dict[str, Any]:
        return self._payload(self._fetch("evidences", _uuid(org_id, "org_id"), _uuid(evidence_id, "evidence_id"), "TENANT_SCOPE_VIOLATION"))

    def list_evidence(self, *, org_id: UUID | str, claim_id: UUID | str | None = None,
                      status: str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        params: list[Any] = [tenant]
        query = "SELECT DISTINCT e.payload FROM evidences e"
        if claim_id is not None:
            query += " JOIN claim_evidences ce ON ce.org_id = e.org_id AND ce.evidence_id = e.id AND ce.claim_id = ?"
            params.insert(0, _uuid(claim_id, "claim_id"))
        query += " WHERE e.org_id = ?"
        if status is not None:
            if status not in EVIDENCE_STATES:
                raise KnowledgeError("INVALID_EVIDENCE_STATE", "status is invalid")
            query += " AND e.status = ?"
            params.append(status)
        query += " ORDER BY e.captured_at, e.id"
        rows = self._connection.execute(query, tuple(params)).fetchall()
        return tuple(json.loads(row["payload"]) for row in rows)

    evidence_for_claim = list_evidence

    def events(self, *, org_id: UUID | str, aggregate_type: str | None = None,
               aggregate_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        query = "SELECT envelope FROM knowledge_events WHERE org_id = ?"
        params: list[Any] = [tenant]
        if aggregate_type is not None:
            query += " AND aggregate_type = ?"
            params.append(_text(aggregate_type, "aggregate_type", 64))
        if aggregate_id is not None:
            query += " AND aggregate_id = ?"
            params.append(_uuid(aggregate_id, "aggregate_id"))
        # Sequence is the aggregate's durable ordering key; UUID ordering is
        # intentionally unrelated to command order.
        query += " ORDER BY sequence, event_id"
        return tuple(json.loads(row["envelope"]) for row in self._connection.execute(query, tuple(params)).fetchall())


KnowledgeStore = KnowledgeService
EntityClaimEvidenceService = KnowledgeService

__all__ = ["KnowledgeError", "KnowledgeService", "KnowledgeStore", "EntityClaimEvidenceService"]
