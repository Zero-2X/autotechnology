"""Tenant-scoped ContentVariant roots and immutable VariantVersion facts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .infrastructure.variant_schema import initialize
from .region_rules import RegionRuleService
from .service import CanonicalVersionPort, ProductionError, _hash, _sections, _text, _uuid


_CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema"
_VALIDATORS = {
    name: Draft202012Validator(json.loads((_CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8")),
                                format_checker=FormatChecker())
    for name in ("variant-draft", "content-variant", "variant-version")
}
_DRAFT_HASH_FIELDS = (
    "org_id", "canonical_content_id", "canonical_content_version_id", "source_content_hash",
    "locale", "market", "audience", "tone", "title", "abstract", "blocks", "transform_mode",
)


class RegionVersionPort(Protocol):
    def get_version(self, *, org_id: UUID | str, version_id: UUID | str) -> Mapping[str, Any]: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate(name: str, value: Mapping[str, Any]) -> None:
    errors = list(_VALIDATORS[name].iter_errors(value))
    if errors:
        raise ProductionError("INVALID_VARIANT_CONTRACT", errors[0].message)


class VariantStore:
    """Persist a draft after verifying its Canonical and Region dependencies."""

    def __init__(self, *, connection: sqlite3.Connection, canonical_versions: CanonicalVersionPort,
                 region_versions: RegionVersionPort, region_rules: RegionRuleService | None = None) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        initialize(self.connection)
        self.canonical_versions = canonical_versions
        self.region_versions = region_versions
        self.region_rules = region_rules
        self._lock = RLock()

    def save_draft(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                   idempotency_key: str, draft: Mapping[str, Any],
                   region_profile_version_id: UUID | str, expected_version_no: int | None = None,
                   disclosure: str | None = None, term_memory_version: str = "pending") -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        region_id = _uuid(region_profile_version_id, "region_profile_version_id")
        term_memory = _text(term_memory_version, "term_memory_version", 128)
        if disclosure is not None and not isinstance(disclosure, str):
            raise ProductionError("INVALID_VARIANT_REQUEST", "disclosure must be text or null")
        if expected_version_no is not None and (type(expected_version_no) is not int or expected_version_no < 0):
            raise ProductionError("INVALID_VARIANT_REQUEST", "expected_version_no must be nonnegative")
        if not isinstance(draft, Mapping):
            raise ProductionError("INVALID_VARIANT_DRAFT", "draft must be an object")
        draft = deepcopy(dict(draft))
        _validate("variant-draft", draft)
        if draft["org_id"] != tenant:
            raise ProductionError("TENANT_SCOPE_VIOLATION", "draft is outside this organization")
        material = {name: draft[name] for name in _DRAFT_HASH_FIELDS}
        if _hash(material) != draft["draft_hash"]:
            raise ProductionError("INVALID_VARIANT_DRAFT", "draft hash does not match content")
        request_hash = _hash({"draft_hash": draft["draft_hash"], "region_profile_version_id": region_id,
                              "expected_version_no": expected_version_no, "disclosure": disclosure,
                              "term_memory_version": term_memory})
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                prior = self.connection.execute(
                    "SELECT request_hash, response FROM variant_commands WHERE org_id = ? AND idempotency_key = ?",
                    (tenant, key),
                ).fetchone()
                if prior is not None:
                    if prior["request_hash"] != request_hash:
                        raise ProductionError("IDEMPOTENCY_KEY_REUSED", "variant command differs from prior request")
                    self.connection.commit()
                    return json.loads(prior["response"])
                source = self.canonical_versions.get_version(
                    org_id=tenant, version_id=draft["canonical_content_version_id"]
                )
                if (not isinstance(source, Mapping) or source.get("org_id") != tenant or
                    source.get("id") != draft["canonical_content_version_id"] or
                    source.get("canonical_content_id") != draft["canonical_content_id"]):
                    raise ProductionError("TENANT_SCOPE_VIOLATION", "canonical source is outside this organization")
                if source.get("status") == "withdrawn" or source.get("freshness_status") == "withdrawn":
                    raise ProductionError("CANONICAL_VERSION_WITHDRAWN", "withdrawn canonical version cannot be used")
                if source.get("content_hash") != draft["source_content_hash"]:
                    raise ProductionError("CANONICAL_SOURCE_CHANGED", "draft does not match source version")
                sections = _sections(source)
                if len(sections) != len(draft["blocks"]):
                    raise ProductionError("INVALID_VARIANT_DRAFT", "draft block count differs from source")
                for section, block in zip(sections, draft["blocks"], strict=True):
                    if (block["source_key"] != section["key"] or
                        block["block_id"] != (section.get("block_id") or section["key"]) or
                        block["source_text_hash"] != _hash(section["content"]) or
                        block["claim_id"] != section.get("claim_id")):
                        raise ProductionError("INVALID_VARIANT_DRAFT", "draft source mapping differs")
                    if draft["transform_mode"] == "rule_copy" and block["localized_text"] != section["content"]:
                        raise ProductionError("INVALID_VARIANT_DRAFT", "rule copy changed source text")
                region = self.region_versions.get_version(org_id=tenant, version_id=region_id)
                if (not isinstance(region, Mapping) or region.get("org_id") != tenant or
                    region.get("id") != region_id):
                    raise ProductionError("TENANT_SCOPE_VIOLATION", "region version is outside this organization")
                locales = region.get("locales")
                if (region.get("status") != "active" or region.get("region_code") != draft["market"] or
                    not isinstance(locales, (list, tuple)) or draft["locale"] not in locales):
                    raise ProductionError("REGION_PROFILE_MISMATCH", "region version does not allow the locale and market")
                region_decision = None
                if self.region_rules is not None:
                    region_decision = self.region_rules.evaluate(
                        org_id=tenant, actor_id=actor, trace_id=trace, idempotency_key=key + ":region",
                        region_profile_version=region, variant=draft,
                        context={"disclosure": disclosure},
                    )
                    if region_decision["status"] == "blocked":
                        raise ProductionError("REGION_RULE_BLOCKED", "Region preflight blocked this Variant draft")
                row = self.connection.execute(
                    "SELECT * FROM content_variants WHERE org_id = ? AND canonical_content_id = ? "
                    "AND locale = ? AND market = ? AND audience = ?",
                    (tenant, draft["canonical_content_id"], draft["locale"], draft["market"], draft["audience"]),
                ).fetchone()
                now = _now()
                if row is None:
                    if expected_version_no not in (None, 0):
                        raise ProductionError("VERSION_CONFLICT", "new Variant has no prior version")
                    root = {
                        "id": str(uuid4()), "org_id": tenant,
                        "canonical_content_id": draft["canonical_content_id"],
                        "locale": draft["locale"], "market": draft["market"],
                        "audience": draft["audience"], "current_version_id": None,
                        "status": "draft",
                    }
                    _validate("content-variant", root)
                    self.connection.execute(
                        "INSERT INTO content_variants (id, org_id, canonical_content_id, locale, market, audience, "
                        "current_version_id, status, created_by, created_at, updated_at, payload) "
                        "VALUES (?, ?, ?, ?, ?, ?, NULL, 'draft', ?, ?, ?, ?)",
                        (root["id"], tenant, root["canonical_content_id"], root["locale"], root["market"],
                         root["audience"], actor, now, now, json.dumps(root, sort_keys=True)),
                    )
                    version_no = 1
                else:
                    root = json.loads(row["payload"])
                    current = self.connection.execute(
                        "SELECT version_no FROM variant_versions WHERE org_id = ? AND id = ?",
                        (tenant, root["current_version_id"]),
                    ).fetchone()
                    current_no = int(current["version_no"]) if current is not None else 0
                    if expected_version_no != current_no:
                        raise ProductionError("VERSION_CONFLICT", "Variant current version changed")
                    version_no = current_no + 1
                body = {"blocks": [
                    {"block_id": block["block_id"], "localized_text": block["localized_text"],
                     "term_refs": [], "disclosure": block["disclosure"]}
                    for block in draft["blocks"]
                ]}
                source_map = [
                    {"block_id": block["block_id"], "source_key": block["source_key"],
                     "source_text_hash": block["source_text_hash"], "claim_id": block["claim_id"]}
                    for block in draft["blocks"]
                ]
                version = {
                    "id": str(uuid4()), "org_id": tenant, "content_variant_id": root["id"],
                    "canonical_content_version_id": draft["canonical_content_version_id"],
                    "version_no": version_no, "locale": draft["locale"], "market": draft["market"],
                    "audience": draft["audience"], "tone": draft["tone"],
                    "region_profile_version_id": region_id,
                    "source_variant_version_id": root["current_version_id"],
                    "body": body, "term_memory_version": term_memory,
                    "disclosure": disclosure, "policy_snapshot_id": None, "status": "draft",
                    "snapshot_hash": _hash({"draft_hash": draft["draft_hash"], "region_profile_version_id": region_id,
                                            "disclosure": disclosure, "term_memory_version": term_memory}),
                    "created_by": actor, "created_at": now,
                }
                _validate("variant-version", version)
                self.connection.execute(
                    "INSERT INTO variant_versions (id, org_id, content_variant_id, canonical_content_version_id, "
                    "region_profile_version_id, version_no, status, snapshot_hash, source_map_json, "
                    "created_by, created_at, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (version["id"], tenant, root["id"], version["canonical_content_version_id"], region_id,
                     version_no, "draft", version["snapshot_hash"], json.dumps(source_map, sort_keys=True),
                     actor, now, json.dumps(version, sort_keys=True)),
                )
                root["current_version_id"] = version["id"]
                self.connection.execute(
                    "UPDATE content_variants SET current_version_id = ?, updated_at = ?, payload = ? "
                    "WHERE org_id = ? AND id = ?",
                    (version["id"], now, json.dumps(root, sort_keys=True), tenant, root["id"]),
                )
                response = {"content_variant": root, "version": version, "source_map": source_map}
                if region_decision is not None:
                    response["region_decision"] = region_decision
                self.connection.execute(
                    "INSERT INTO variant_commands (org_id, idempotency_key, request_hash, actor_id, trace_id, response) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (tenant, key, request_hash, actor, trace, json.dumps(response, sort_keys=True)),
                )
                event_id = str(uuid4())
                event_payload = {
                    "aggregate_id": version["id"], "aggregate_version": version_no,
                    "from_state": None, "to_state": "draft", "command": "save_draft",
                    "snapshot_hash": version["snapshot_hash"],
                }
                event = {
                    "event_id": event_id, "event_type": "variant.draft_created", "event_schema_version": 1,
                    "occurred_at": now, "org_id": tenant, "trace_id": trace,
                    "aggregate_type": "VariantVersion", "aggregate_id": version["id"],
                    "aggregate_version": version_no, "actor_type": "user", "actor_id": actor,
                    "idempotency_key": key, "payload": event_payload, "payload_hash": _hash(event_payload),
                }
                self.connection.execute(
                    "INSERT INTO variant_events (event_id, org_id, aggregate_id, event_type, created_at, payload) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (event_id, tenant, version["id"], event["event_type"], now, json.dumps(event, sort_keys=True)),
                )
                self.connection.commit()
                return response
            except Exception:
                self.connection.rollback()
                raise

    def get(self, *, org_id: UUID | str, content_variant_id: UUID | str) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(content_variant_id, "content_variant_id")
        row = self.connection.execute(
            "SELECT payload FROM content_variants WHERE org_id = ? AND id = ?", (tenant, identity)
        ).fetchone()
        if row is None:
            raise ProductionError("TENANT_SCOPE_VIOLATION", "Variant is outside this organization")
        return json.loads(row["payload"])

    def list_versions(self, *, org_id: UUID | str, content_variant_id: UUID | str) -> list[dict[str, Any]]:
        tenant = _uuid(org_id, "org_id")
        root = self.get(org_id=tenant, content_variant_id=content_variant_id)
        rows = self.connection.execute(
            "SELECT payload FROM variant_versions WHERE org_id = ? AND content_variant_id = ? "
            "ORDER BY version_no, id", (tenant, root["id"]),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def list_children(self, *, org_id: str, parent_ids: tuple[str, ...]) -> Sequence[Mapping[str, Any]]:
        """Read-only CANON-006 lineage Port for Canonical version parents."""
        tenant = _uuid(org_id, "org_id")
        if not parent_ids:
            return ()
        ids = tuple(_uuid(parent_id, "parent_id") for parent_id in parent_ids)
        placeholders = ",".join("?" for _ in ids)
        rows = self.connection.execute(
            "SELECT id, org_id, canonical_content_version_id, version_no, status, created_at "
            f"FROM variant_versions WHERE org_id = ? AND canonical_content_version_id IN ({placeholders}) "
            "ORDER BY version_no, id", (tenant, *ids),
        ).fetchall()
        return tuple({
            "id": row["id"], "org_id": row["org_id"],
            "parent_id": row["canonical_content_version_id"], "status": row["status"],
            "version": row["version_no"], "metadata_ref": None,
            "created_at": row["created_at"],
        } for row in rows)


__all__ = ["RegionVersionPort", "VariantStore"]
