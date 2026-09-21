"""KnowledgeCore aggregate and immutable version use cases for KNOW-002."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.knowledge_schema import initialize
from .service import (
    KnowledgeError,
    _hash,
    _json,
    _list,
    _now,
    _optional_text,
    _text,
    _utc,
    _uuid,
    _uuid_list,
)


ROOT = Path(__file__).resolve().parents[2]
CORE_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/knowledge-core.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
VERSION_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "packages/contracts/jsonschema/knowledge-core-version.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class KnowledgeCoreService:
    """Persist a tenant-scoped, versioned set of verified knowledge facts."""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
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

    @staticmethod
    def _validate(validator: Draft202012Validator, value: Mapping[str, Any], code: str) -> None:
        errors = sorted(validator.iter_errors(dict(value)), key=lambda error: list(error.path))
        if errors:
            raise KnowledgeError(code, errors[0].message)

    def _identity(self, org_id: UUID | str, actor_id: UUID | str, trace_id: str, key: str) -> tuple[str, str, str, str]:
        return _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _text(trace_id, "trace_id", 256), _text(key, "idempotency_key", 200)

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT payload_hash, response FROM knowledge_core_commands WHERE org_id = ? AND idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if row is None:
            return None
        if row["payload_hash"] != digest:
            raise KnowledgeError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
        return json.loads(row["response"])

    def _save_command(self, tenant: str, key: str, digest: str, actor: str, trace: str, response: Mapping[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO knowledge_core_commands (org_id, idempotency_key, payload_hash, actor_id, trace_id, response) VALUES (?, ?, ?, ?, ?, ?)",
            (tenant, key, digest, actor, trace, _json(response)),
        )

    def _event(
        self,
        *,
        tenant: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        actor: str,
        trace: str,
        key: str,
        version: int,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        sequence = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM knowledge_events WHERE org_id = ? AND aggregate_type = ? AND aggregate_id = ?",
            (tenant, aggregate_type, aggregate_id),
        ).fetchone()[0]
        event_id = str(uuid4())
        event_payload = dict(payload)
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
            "INSERT INTO knowledge_events (event_id, org_id, aggregate_type, aggregate_id, event_type, sequence, envelope) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, tenant, aggregate_type, aggregate_id, event_type, sequence, _json(envelope)),
        )
        return envelope

    def _fetch_core(self, tenant: str, core_id: str) -> sqlite3.Row:
        row = self._connection.execute("SELECT * FROM knowledge_cores WHERE org_id = ? AND id = ?", (tenant, core_id)).fetchone()
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "knowledge core is not in this organization")
        return row

    def _fetch_version(self, tenant: str, version_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM knowledge_core_versions WHERE org_id = ? AND id = ?", (tenant, version_id)
        ).fetchone()
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "knowledge core version is not in this organization")
        return row

    def _payload(self, row: sqlite3.Row) -> dict[str, Any]:
        return json.loads(row["payload"])

    def _claim(self, tenant: str, claim_id: str) -> dict[str, Any]:
        row = self._connection.execute("SELECT payload FROM claims WHERE org_id = ? AND id = ?", (tenant, claim_id)).fetchone()
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "claim is not in this organization")
        return json.loads(row["payload"])

    def _evidence(self, tenant: str, evidence_id: str) -> dict[str, Any]:
        row = self._connection.execute("SELECT payload FROM evidences WHERE org_id = ? AND id = ?", (tenant, evidence_id)).fetchone()
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "evidence is not in this organization")
        return json.loads(row["payload"])

    def _source_status(self, tenant: str, snapshot_id: str) -> str:
        try:
            row = self._connection.execute(
                "SELECT status FROM source_snapshots WHERE org_id = ? AND id = ?", (tenant, snapshot_id)
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise KnowledgeError("PROVENANCE_NOT_INITIALIZED", "source snapshot storage is unavailable") from exc
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "source snapshot is not in this organization")
        return str(row["status"])

    def _rights(self, tenant: str, rights_id: str) -> sqlite3.Row:
        try:
            row = self._connection.execute(
                "SELECT status, permitted_use, valid_from, valid_to FROM rights_record_versions WHERE org_id = ? AND id = ?",
                (tenant, rights_id),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise KnowledgeError("RIGHTS_NOT_INITIALIZED", "rights version storage is unavailable") from exc
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "rights version is not in this organization")
        return row

    def _topic_brief_check(self, tenant: str, topic_brief_id: str | None) -> None:
        if topic_brief_id is None:
            return
        exists = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'topic_briefs'"
        ).fetchone()
        if not exists:
            return
        row = self._connection.execute("SELECT 1 FROM topic_briefs WHERE org_id = ? AND id = ?", (tenant, topic_brief_id)).fetchone()
        if row is None:
            raise KnowledgeError("TENANT_SCOPE_VIOLATION", "topic brief is not in this organization")

    def _relation_evidence(self, tenant: str, claim_id: str) -> list[str]:
        rows = self._connection.execute(
            "SELECT evidence_id FROM claim_evidences WHERE org_id = ? AND claim_id = ? ORDER BY evidence_id",
            (tenant, claim_id),
        ).fetchall()
        values = [str(row["evidence_id"]) for row in rows]
        if values:
            return values
        rows = self._connection.execute(
            "SELECT id FROM evidences WHERE org_id = ? AND claim_id = ? ORDER BY id", (tenant, claim_id)
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def _scope(
        self,
        tenant: str,
        entity_ids: Iterable[object] | None,
        claim_ids: Iterable[object],
        evidence_ids: Iterable[object] | None,
    ) -> tuple[list[str], list[str], list[str], list[dict[str, Any]]]:
        claims = _uuid_list(claim_ids, "claim_ids", required=True)
        supplied_entities = _uuid_list(entity_ids, "entity_ids")
        supplied_evidence = _uuid_list(evidence_ids, "evidence_ids")
        claim_payloads = [self._claim(tenant, claim_id) for claim_id in claims]
        inferred_entities: list[str] = []
        for claim in claim_payloads:
            for entity_id in claim.get("entity_ids", []):
                if entity_id not in inferred_entities:
                    inferred_entities.append(entity_id)
        entities = supplied_entities or inferred_entities
        if set(inferred_entities) - set(entities):
            raise KnowledgeError("KNOWLEDGE_SCOPE_MISMATCH", "core entity_ids must contain every claim entity")
        evidence = supplied_evidence[:]
        if not evidence:
            for claim_id in claims:
                for evidence_id in self._relation_evidence(tenant, claim_id):
                    if evidence_id not in evidence:
                        evidence.append(evidence_id)
        for evidence_id in evidence:
            self._evidence(tenant, evidence_id)
        return entities, claims, evidence, claim_payloads

    @staticmethod
    def _conflict_groups(claims: Sequence[Mapping[str, Any]], explicit: Iterable[Iterable[object]] | None = None) -> list[tuple[str, list[str], str]]:
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for claim in claims:
            key = f"{claim.get('fact_type', 'fact')}|{','.join(sorted(claim.get('entity_ids', [])))}"
            groups.setdefault(key, []).append(claim)
        result: list[tuple[str, list[str], str]] = []
        for key, values in groups.items():
            statements = {str(value.get("statement", "")).strip() for value in values}
            if len(values) > 1 and len(statements) > 1:
                result.append((key, [str(value["id"]) for value in values], "claims with the same fact scope disagree"))
        for index, group in enumerate(explicit or []):
            ids = [str(value) for value in group]
            if len(ids) > 1:
                result.append((f"explicit:{index}:{','.join(sorted(ids))}", ids, "explicit conflict declaration"))
        return result

    def _create_conflict_sets(self, tenant: str, actor: str, claims: Sequence[Mapping[str, Any]], explicit: Iterable[Iterable[object]] | None) -> list[str]:
        ids: list[str] = []
        for key, claim_ids, reason in self._conflict_groups(claims, explicit):
            existing = self._connection.execute(
                "SELECT id FROM knowledge_conflict_sets WHERE org_id = ? AND conflict_key = ?", (tenant, key)
            ).fetchone()
            if existing is not None:
                ids.append(str(existing["id"]))
                continue
            conflict_id = str(uuid4())
            now = _now()
            payload = {
                "id": conflict_id, "org_id": tenant, "conflict_key": key,
                "claim_ids": claim_ids, "reason": reason, "status": "needs_review",
                "created_by": actor, "created_at": now,
            }
            self._connection.execute(
                "INSERT INTO knowledge_conflict_sets (id, org_id, conflict_key, claim_ids_json, reason, status, created_by, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (conflict_id, tenant, key, _json(claim_ids), reason, "needs_review", actor, now, _json(payload)),
            )
            ids.append(conflict_id)
        return ids

    def _snapshot_hash(self, tenant: str, entity_ids: Sequence[str], claim_ids: Sequence[str], evidence_ids: Sequence[str]) -> str:
        claims = [self._claim(tenant, claim_id) for claim_id in claim_ids]
        evidences = [self._evidence(tenant, evidence_id) for evidence_id in evidence_ids]
        return _hash({
            "entity_ids": list(entity_ids), "claim_ids": list(claim_ids), "evidence_ids": list(evidence_ids),
            "claim_hashes": [claim.get("content_hash") for claim in claims],
            "evidence_hashes": [evidence.get("content_hash") for evidence in evidences],
        })

    def _insert_version(
        self,
        *,
        tenant: str,
        actor: str,
        core_id: str,
        topic_brief_id: str | None,
        version_no: int,
        entity_ids: list[str],
        claim_ids: list[str],
        evidence_ids: list[str],
        conflict_set_ids: list[str],
        status: str,
        supersedes_version_id: str | None,
        freshness_checked_at: str | None,
    ) -> dict[str, Any]:
        version_id = str(uuid4())
        now = _now()
        snapshot_hash = self._snapshot_hash(tenant, entity_ids, claim_ids, evidence_ids)
        version = {
            "id": version_id, "org_id": tenant, "knowledge_core_id": core_id, "topic_brief_id": topic_brief_id,
            "version_no": version_no, "entity_ids": entity_ids, "claim_ids": claim_ids, "evidence_ids": evidence_ids,
            "conflict_set_ids": conflict_set_ids, "freshness_checked_at": freshness_checked_at,
            "snapshot_hash": snapshot_hash,
            "content_hash": _hash({"snapshot_hash": snapshot_hash, "status": status, "version_no": version_no}),
            "status": status, "supersedes_version_id": supersedes_version_id, "created_by": actor, "created_at": now,
        }
        self._validate(VERSION_VALIDATOR, version, "INVALID_KNOWLEDGE_CORE_VERSION")
        self._connection.execute(
            "INSERT INTO knowledge_core_versions (id, org_id, knowledge_core_id, topic_brief_id, version_no, entity_ids_json, claim_ids_json, evidence_ids_json, conflict_set_ids_json, freshness_checked_at, snapshot_hash, content_hash, status, supersedes_version_id, created_by, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version_id, tenant, core_id, topic_brief_id, version_no, _json(entity_ids), _json(claim_ids), _json(evidence_ids), _json(conflict_set_ids), freshness_checked_at, snapshot_hash, version["content_hash"], status, supersedes_version_id, actor, now, _json(version)),
        )
        return version

    def _insert_core(
        self, *, tenant: str, actor: str, core_id: str, topic_brief_id: str | None,
        version_id: str | None, status: str, needs_review: bool, created_at: str,
    ) -> dict[str, Any]:
        core = {
            "id": core_id, "org_id": tenant, "topic_brief_id": topic_brief_id,
            "current_version_id": version_id, "status": status, "needs_review": needs_review,
            "created_by": actor, "created_at": created_at, "updated_at": created_at,
        }
        self._validate(CORE_VALIDATOR, core, "INVALID_KNOWLEDGE_CORE")
        self._connection.execute(
            "INSERT INTO knowledge_cores (id, org_id, topic_brief_id, current_version_id, status, needs_review, created_by, created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (core_id, tenant, topic_brief_id, version_id, status, int(needs_review), actor, created_at, created_at, _json(core)),
        )
        return core

    def create_core(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        topic_brief_id: UUID | str | None = None,
        entity_ids: Iterable[object] | None = None,
        claim_ids: Iterable[object],
        evidence_ids: Iterable[object] | None = None,
        conflict_claim_groups: Iterable[Iterable[object]] | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        topic = None if topic_brief_id is None else _uuid(topic_brief_id, "topic_brief_id")
        entities, claims, evidence, claim_payloads = self._scope(tenant, entity_ids, claim_ids, evidence_ids)
        self._topic_brief_check(tenant, topic)
        explicit = [[_uuid(value, "conflict_claim_id") for value in group] for group in (conflict_claim_groups or [])]
        digest = _hash({"operation": "create_core", "topic_brief_id": topic, "entity_ids": entities, "claim_ids": claims, "evidence_ids": evidence, "conflict_claim_groups": explicit})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                core_id = str(uuid4())
                now = _now()
                conflict_ids = self._create_conflict_sets(tenant, actor, claim_payloads, explicit)
                core = self._insert_core(
                    tenant=tenant, actor=actor, core_id=core_id, topic_brief_id=topic, version_id=None,
                    status="draft", needs_review=bool(conflict_ids), created_at=now,
                )
                version = self._insert_version(
                    tenant=tenant, actor=actor, core_id=core_id, topic_brief_id=topic, version_no=1,
                    entity_ids=entities, claim_ids=claims, evidence_ids=evidence, conflict_set_ids=conflict_ids,
                    status="needs_review" if conflict_ids else "draft", supersedes_version_id=None, freshness_checked_at=None,
                )
                core.update(current_version_id=version["id"])
                self._validate(CORE_VALIDATOR, core, "INVALID_KNOWLEDGE_CORE")
                self._connection.execute(
                    "UPDATE knowledge_cores SET current_version_id = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (version["id"], _json(core), tenant, core_id),
                )
                event = self._event(
                    tenant=tenant, aggregate_type="KnowledgeCoreVersion", aggregate_id=version["id"],
                    event_type="knowledge.core_version.changed", actor=actor, trace=trace, key=key, version=1,
                    payload={"aggregate_id": version["id"], "aggregate_version": 1, "from_state": "none", "to_state": version["status"], "command": "create", "snapshot_hash": version["snapshot_hash"], "knowledge_core_id": core_id},
                )
                response = {"core": core, "version": version, "conflict_set_ids": conflict_ids, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except KnowledgeError:
                self._connection.rollback()
                raise
            except sqlite3.IntegrityError as exc:
                self._connection.rollback()
                raise KnowledgeError("KNOWLEDGE_CORE_CONFLICT", "knowledge core identity conflicts with an existing record") from exc
            except Exception:
                self._connection.rollback()
                raise

    create = create_core

    def _validate_contents(self, tenant: str, version: Mapping[str, Any]) -> None:
        conflict_ids = version.get("conflict_set_ids") or []
        if conflict_ids:
            raise KnowledgeError("KNOWLEDGE_CONFLICT_REVIEW", "conflicting claims require review")
        claims = [self._claim(tenant, claim_id) for claim_id in version["claim_ids"]]
        evidence_ids = set(version["evidence_ids"])
        for claim in claims:
            if claim.get("status") != "verified" or claim.get("freshness_status") != "fresh":
                raise KnowledgeError("KNOWLEDGE_EVIDENCE_INSUFFICIENT", "all claims must be verified and fresh")
            related = set(self._relation_evidence(tenant, claim["id"])) & evidence_ids
            valid = False
            for evidence_id in related:
                evidence = self._evidence(tenant, evidence_id)
                if evidence.get("status") != "valid" or not evidence.get("rights_record_version_id"):
                    continue
                if self._source_status(tenant, evidence["source_snapshot_id"]) != "usable":
                    continue
                rights = self._rights(tenant, evidence["rights_record_version_id"])
                if rights["status"] != "verified" or rights["permitted_use"] not in {"research", "derivative", "commercial"}:
                    continue
                if rights["valid_to"]:
                    expiry = datetime.fromisoformat(str(rights["valid_to"]).replace("Z", "+00:00"))
                    if expiry.astimezone(timezone.utc) <= datetime.now(timezone.utc):
                        continue
                valid = True
                break
            if not valid:
                raise KnowledgeError("KNOWLEDGE_EVIDENCE_INSUFFICIENT", "each claim needs valid evidence with verified rights")

    def validate_core(
        self,
        *,
        org_id: UUID | str,
        core_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(core_id, "knowledge_core_id")
        digest = _hash({"operation": "validate_core", "knowledge_core_id": identity, "expected_version": expected_version})
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                core_row = self._fetch_core(tenant, identity)
                current_id = core_row["current_version_id"]
                if not current_id:
                    raise KnowledgeError("KNOWLEDGE_EVIDENCE_INSUFFICIENT", "knowledge core has no version")
                current_row = self._fetch_version(tenant, str(current_id))
                current = self._payload(current_row)
                expected = current["version_no"] if expected_version is None else expected_version
                if type(expected) is not int or expected != current["version_no"]:
                    raise KnowledgeError("VERSION_CONFLICT", "knowledge core version changed")
                self._validate_contents(tenant, current)
                next_version = self._insert_version(
                    tenant=tenant, actor=actor, core_id=identity, topic_brief_id=current["topic_brief_id"],
                    version_no=current["version_no"] + 1, entity_ids=list(current["entity_ids"]),
                    claim_ids=list(current["claim_ids"]), evidence_ids=list(current["evidence_ids"]),
                    conflict_set_ids=[], status="verified", supersedes_version_id=current["id"],
                    freshness_checked_at=_now(),
                )
                core = self._payload(core_row)
                core.update(current_version_id=next_version["id"], status="validated", needs_review=False, updated_at=_now())
                self._validate(CORE_VALIDATOR, core, "INVALID_KNOWLEDGE_CORE")
                self._connection.execute(
                    "UPDATE knowledge_cores SET current_version_id = ?, status = ?, needs_review = ?, updated_at = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (next_version["id"], "validated", 0, core["updated_at"], _json(core), tenant, identity),
                )
                event = self._event(
                    tenant=tenant, aggregate_type="KnowledgeCoreVersion", aggregate_id=next_version["id"],
                    event_type="knowledge.core_version.verified", actor=actor, trace=trace, key=key,
                    version=next_version["version_no"], payload={"aggregate_id": next_version["id"], "aggregate_version": next_version["version_no"], "from_state": current["status"], "to_state": "verified", "command": "verify", "snapshot_hash": next_version["snapshot_hash"], "knowledge_core_id": identity},
                )
                response = {"core": core, "version": next_version, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    validate = validate_core

    def refresh_core(
        self,
        *,
        org_id: UUID | str,
        core_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        expected_version: int | None = None,
        entity_ids: Iterable[object] | None = None,
        claim_ids: Iterable[object] | None = None,
        evidence_ids: Iterable[object] | None = None,
        conflict_claim_groups: Iterable[Iterable[object]] | None = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._identity(org_id, actor_id, trace_id, idempotency_key)
        identity = _uuid(core_id, "knowledge_core_id")
        # Resolve the current snapshot before calculating the command hash.
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                core_row = self._fetch_core(tenant, identity)
                if not core_row["current_version_id"]:
                    raise KnowledgeError("KNOWLEDGE_EVIDENCE_INSUFFICIENT", "knowledge core has no version")
                current = self._payload(self._fetch_version(tenant, str(core_row["current_version_id"])))
                expected = current["version_no"] if expected_version is None else expected_version
                claims_input = current["claim_ids"] if claim_ids is None else claim_ids
                entities, claims, evidence, claim_payloads = self._scope(tenant, entity_ids, claims_input, evidence_ids)
                topic = current["topic_brief_id"]
                explicit = [[_uuid(value, "conflict_claim_id") for value in group] for group in (conflict_claim_groups or [])]
                digest = _hash({"operation": "refresh_core", "knowledge_core_id": identity, "expected_version": expected, "entity_ids": entities, "claim_ids": claims, "evidence_ids": evidence, "conflict_claim_groups": explicit})
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    self._connection.commit()
                    return prior
                if type(expected) is not int or expected != current["version_no"]:
                    raise KnowledgeError("VERSION_CONFLICT", "knowledge core version changed")
                conflict_ids = self._create_conflict_sets(tenant, actor, claim_payloads, explicit)
                version = self._insert_version(
                    tenant=tenant, actor=actor, core_id=identity, topic_brief_id=topic,
                    version_no=current["version_no"] + 1, entity_ids=entities, claim_ids=claims, evidence_ids=evidence,
                    conflict_set_ids=conflict_ids, status="needs_review" if conflict_ids else "draft",
                    supersedes_version_id=current["id"], freshness_checked_at=None,
                )
                core = self._payload(core_row)
                core.update(current_version_id=version["id"], status="stale", needs_review=bool(conflict_ids), updated_at=_now())
                self._validate(CORE_VALIDATOR, core, "INVALID_KNOWLEDGE_CORE")
                self._connection.execute(
                    "UPDATE knowledge_cores SET current_version_id = ?, status = ?, needs_review = ?, updated_at = ?, payload = ? WHERE org_id = ? AND id = ?",
                    (version["id"], "stale", int(bool(conflict_ids)), core["updated_at"], _json(core), tenant, identity),
                )
                event = self._event(
                    tenant=tenant, aggregate_type="KnowledgeCoreVersion", aggregate_id=version["id"], event_type="knowledge.core_version.changed", actor=actor, trace=trace, key=key, version=version["version_no"],
                    payload={"aggregate_id": version["id"], "aggregate_version": version["version_no"], "from_state": current["status"], "to_state": version["status"], "command": "refresh", "snapshot_hash": version["snapshot_hash"], "knowledge_core_id": identity},
                )
                response = {"core": core, "version": version, "conflict_set_ids": conflict_ids, "event": event}
                self._save_command(tenant, key, digest, actor, trace, response)
                self._connection.commit()
                return response
            except Exception:
                self._connection.rollback()
                raise

    refresh = refresh_core

    def get_core(self, *, org_id: UUID | str, core_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        return self._payload(self._fetch_core(tenant, _uuid(core_id, "knowledge_core_id")))

    def get_version(self, *, org_id: UUID | str, version_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        return self._payload(self._fetch_version(tenant, _uuid(version_id, "knowledge_core_version_id")))

    def list_cores(self, *, org_id: UUID | str, status: str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        query = "SELECT payload FROM knowledge_cores WHERE org_id = ?"
        params: list[Any] = [tenant]
        if status is not None:
            if status not in {"draft", "validated", "stale", "archived"}:
                raise KnowledgeError("INVALID_KNOWLEDGE_CORE_STATE", "status is invalid")
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at, id"
        return tuple(json.loads(row["payload"]) for row in self._connection.execute(query, tuple(params)).fetchall())

    def events(self, *, org_id: UUID | str, aggregate_id: UUID | str | None = None) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        query = "SELECT envelope FROM knowledge_events WHERE org_id = ? AND aggregate_type IN ('KnowledgeCore', 'KnowledgeCoreVersion')"
        params: list[Any] = [tenant]
        if aggregate_id is not None:
            query += " AND aggregate_id = ?"
            params.append(_uuid(aggregate_id, "aggregate_id"))
        query += " ORDER BY sequence, event_id"
        return tuple(json.loads(row["envelope"]) for row in self._connection.execute(query, tuple(params)).fetchall())


KnowledgeCoreStore = KnowledgeCoreService

__all__ = ["KnowledgeCoreService", "KnowledgeCoreStore"]
