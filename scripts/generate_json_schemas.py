"""Generate the checked-in JSON Schema baseline from section 4.6.

The plan's field catalogue is intentionally human-readable.  This script turns
that catalogue into deterministic object schemas so API and event work can use
machine validation before business code exists.  It does not create database
migrations or claim that a domain object is implemented.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md"
JSONSCHEMA_DIR = ROOT / "packages/contracts/jsonschema"
EVENT_DIR = ROOT / "packages/contracts/events"
EVENT_REGISTRY = ROOT / "docs/contracts/event-registry.yaml"

DRAFT = "https://json-schema.org/draft/2020-12/schema"
BASE_ID = "https://schemas.ai-content-workflow.local/"
# Accepted Foundation extensions are hand-maintained and must not be replaced
# by the shorthand catalogue generator.  Existing files are therefore kept by
# default; set FORCE_JSON_SCHEMA_REGEN=1 only when intentionally rebuilding a
# clean contract directory (the overlays above are applied in that mode).
PRESERVE_EXISTING = os.environ.get("FORCE_JSON_SCHEMA_REGEN") != "1"


def slug(name: str) -> str:
    value = re.sub(r"(?<!^)([A-Z])", r"-\1", name).lower()
    return value.replace("_", "-")


def ref_schema(name: str) -> dict[str, str]:
    return {"$ref": f"./{slug(name)}.schema.json"}


def scalar_schema(token: str) -> dict[str, Any]:
    token = token.strip()
    if token in {"uuid", "uuid-v4"}:
        return {"type": "string", "format": "uuid"}
    if token in {"datetime", "timestamp"}:
        return {"type": "string", "format": "date-time"}
    if token == "sha256":
        return {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"}
    if token == "private-object-ref":
        return {"type": "string", "minLength": 1, "pattern": "^private://"}
    if token in {"string", "string-ref", "locale-catalog-ref", "region-catalog-ref", "market-catalog-ref", "vault-ref"}:
        return {"type": "string", "minLength": 1}
    if token in {"number", "0.0"}:
        return {"type": "number"}
    if token in {"integer", "1", "0"}:
        return {"type": "integer"}
    if token in {"boolean", "true", "false"}:
        return {"type": "boolean"}
    if token in {"object", "{}"}:
        return {"type": "object"}
    if token == "null":
        return {"type": "null"}
    # Human catalogue values such as ``US`` or ``developer`` are examples,
    # rather than closed enums.  Keep them as non-empty strings.
    return {"type": "string", "minLength": 1}


def value_schema(value: Any) -> dict[str, Any]:
    # Numeric catalogue examples describe types, not literal constants.
    # bool must be checked first because it is an int subclass in Python.
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, dict):
        properties = {key: value_schema(item) for key, item in value.items()}
        # The section 4.6 catalogue describes complete persisted records.  A
        # field may be nullable, but it remains present in the record.
        return {
            "type": "object",
            "properties": properties,
            "required": list(value.keys()),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        return {"type": "array", "items": value_schema(value[0]) if value else {}}
    if not isinstance(value, str):
        return {}

    text = value.strip()
    if text.endswith("[]"):
        return {"type": "array", "items": value_schema(text[:-2])}
    # The catalogue uses ``type|null`` for optional values and ``a|b|c`` for
    # closed enums.  Use anyOf when null is present to retain the enum.
    tokens = [part.strip() for part in text.split("|")]
    if len(tokens) > 1:
        non_null = [part for part in tokens if part != "null"]
        if "null" in tokens:
            branches: list[dict[str, Any]] = [{"type": "null"}]
            if len(non_null) == 1:
                branches.insert(0, scalar_schema(non_null[0]))
            else:
                branches.insert(0, {"type": "string", "enum": non_null})
            return {"anyOf": branches}
        # If every token is a known primitive descriptor, retain its type;
        # otherwise the values are an enum.
        primitive = {"string", "number", "integer", "boolean", "object"}
        if all(token in primitive for token in tokens):
            return {"type": tokens[0]}
        return {"type": "string", "enum": tokens}
    return scalar_schema(text)


def extract_catalogue() -> dict[str, Any]:
    text = DOCUMENT.read_text(encoding="utf-8")
    match = re.search(r"### 4\.6 最小字段契约.*?```json\s*(.*?)\s*```", text, re.S)
    if not match:
        raise SystemExit("section 4.6 JSON field catalogue not found")
    try:
        result = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid section 4.6 JSON catalogue: {exc}") from exc
    if not isinstance(result, dict) or not result:
        raise SystemExit("section 4.6 catalogue must be a non-empty object")
    return result


def add_cross_field_rules(name: str, schema: dict[str, Any]) -> None:
    """Add constraints that cannot be represented by the shorthand catalogue."""
    def require(field: str) -> None:
        required = schema.setdefault("required", [])
        if field not in required:
            required.append(field)

    if name == "TaskJob":
        # The queue persists a private payload reference and its digest.  The
        # digest was added after the human field catalogue was frozen; keep it
        # here so a clean regeneration cannot silently drop the replay guard.
        schema["properties"]["payload_hash"] = {
            "type": "string", "pattern": "^[A-Fa-f0-9]{64}$"
        }
        require("payload_hash")
        schema["properties"]["aggregate_version"] = {"type": "integer", "minimum": 1}
        schema["properties"]["attempt_count"] = {"type": "integer", "minimum": 0}
        schema["properties"]["max_attempts"] = {"type": "integer", "minimum": 1}
    elif name == "OutboxEvent":
        # Event payloads are versioned per event and intentionally open here;
        # the envelope/event schemas provide the event-specific constraints.
        schema["properties"]["payload"]["additionalProperties"] = True
    elif name == "HumanTask":
        # Human review snapshots are opaque, redacted JSON projections.
        schema["properties"]["input_snapshot"]["additionalProperties"] = True
        schema["properties"]["result"]["additionalProperties"] = True
    elif name == "GeoQueryFixture":
        # GEO_CONTENT-002 owns a richer immutable fixture than the compact
        # section-4.6 catalogue entry.  Keep this overlay in the generator so
        # an explicit FORCE_JSON_SCHEMA_REGEN cannot erase its audit/version
        # fields or loosen the UUID claim references.
        schema["description"] = "Immutable, tenant-scoped prompt/query fixture used by offline GEO compliance sampling."
        schema["properties"] = {
            "id": {"type": "string", "format": "uuid"},
            "org_id": {"type": "string", "format": "uuid"},
            "query": {"type": "string", "minLength": 1, "maxLength": 4096},
            "prompt": {"type": "string", "minLength": 1, "maxLength": 4096},
            "locale": {"type": "string", "minLength": 1, "maxLength": 32},
            "region": {"type": "string", "minLength": 1, "maxLength": 128},
            "expected_entities": {
                "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 512},
                "uniqueItems": True,
            },
            "expected_claim_ids": {
                "type": "array", "items": {"type": "string", "format": "uuid"}, "uniqueItems": True,
            },
            "status": {"type": "string", "enum": ["created", "active", "retired"]},
            "version": {"type": "integer", "minimum": 1},
            "fixture_hash": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"},
            "prompt_hash": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"},
            "predecessor_refs": {
                "type": "array", "items": {"type": "string", "minLength": 1, "maxLength": 256},
                "uniqueItems": True,
            },
            "predecessor_hash": {"type": ["string", "null"], "pattern": "^[A-Fa-f0-9]{64}$"},
            "created_by": {"type": ["string", "null"], "format": "uuid"},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_by": {"type": ["string", "null"], "format": "uuid"},
            "updated_at": {"type": ["string", "null"], "format": "date-time"},
            "trace_id": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
            "policy_snapshot_hash": {"type": ["string", "null"], "pattern": "^[A-Fa-f0-9]{64}$"},
            "metadata": {"type": "object", "additionalProperties": True},
        }
        # Core catalogue schemas are closed snapshots: every declared field is
        # present, while nullable fields carry absence explicitly as null.
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
        schema["x-source"] = "GEO_CONTENT-002"
        schema["x-append-only"] = True
    elif name == "GeoRun":
        # GEO_CONTENT-003 fixes the compact catalogue shape into a closed,
        # terminal FakeGeo aggregation contract.  Preserve these constraints
        # when schemas are explicitly regenerated.
        schema["description"] = (
            "Immutable tenant-scoped result of deterministic multi-sample "
            "FakeGeo parsing and aggregation."
        )
        schema["properties"] = {
            "id": {"type": "string", "format": "uuid"},
            "org_id": {"type": "string", "format": "uuid"},
            "page_version_id": {"type": "string", "format": "uuid"},
            "query_fixture_id": {"type": "string", "format": "uuid"},
            "locale": {"type": "string", "minLength": 1, "maxLength": 32},
            "region": {"type": "string", "minLength": 1, "maxLength": 128},
            "sample_count": {"type": "integer", "minimum": 2, "maximum": 100},
            "parser_version": {"type": "string", "minLength": 1, "maxLength": 64},
            "mention_count": {"type": "integer", "minimum": 0},
            "citation_count": {"type": "integer", "minimum": 0},
            "position_values": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "uniqueItems": True,
            },
            "correctness_values": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["correct", "incorrect", "unknown"],
                },
                "minItems": 1,
                "maxItems": 3,
                "uniqueItems": True,
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "data_quality": {"type": "string", "enum": ["estimated", "validated"]},
            "fixture_hash": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"},
            "status": {
                "type": "string",
                "enum": ["planned", "running", "succeeded", "failed"],
            },
            "created_at": {"type": "string", "format": "date-time"},
        }
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
        schema["x-source"] = "GEO_CONTENT-003"
        schema["x-append-only"] = True
    elif name == "RegionProfile":
        schema["description"] = (
            "Tenant-scoped region/market identity with an atomic pointer to "
            "its active immutable version."
        )
        schema["properties"] = {
            "id": {"type": "string", "format": "uuid"},
            "org_id": {"type": "string", "format": "uuid"},
            "region_code": {
                "type": "string", "minLength": 2, "maxLength": 32,
                "pattern": "^[A-Z]{2,8}(?:-[A-Z0-9]{2,8})*$",
            },
            "current_version_id": {
                "anyOf": [
                    {"type": "string", "format": "uuid"},
                    {"type": "null"},
                ]
            },
            "status": {"type": "string", "enum": ["active", "retired"]},
            "created_at": {"type": "string", "format": "date-time"},
        }
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
        schema["x-source"] = "GEO_REGION-001"
    elif name == "RegionProfileVersion":
        rule_item = {
            "anyOf": [
                {"type": "string", "minLength": 1, "maxLength": 512},
                {"type": "object", "minProperties": 1, "additionalProperties": True},
            ]
        }
        schema["description"] = "Tenant-scoped versioned locale and market policy configuration."
        schema["properties"] = {
            "id": {"type": "string", "format": "uuid"},
            "org_id": {"type": "string", "format": "uuid"},
            "region_profile_id": {"type": "string", "format": "uuid"},
            "version_no": {"type": "integer", "minimum": 1},
            "region_code": {
                "type": "string", "minLength": 2, "maxLength": 32,
                "pattern": "^[A-Z]{2,8}(?:-[A-Z0-9]{2,8})*$",
            },
            "locales": {
                "type": "array", "minItems": 1, "uniqueItems": True,
                "items": {
                    "type": "string", "minLength": 2, "maxLength": 64,
                    "pattern": "^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
                },
            },
            "timezone": {"type": "string", "minLength": 1, "maxLength": 128},
            "date_number_format": {"type": "string", "minLength": 1, "maxLength": 256},
            "units": {"type": "string", "enum": ["metric", "imperial", "mixed"]},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "terminology_version": {"type": "string", "minLength": 1, "maxLength": 128},
            "disclosure_rules": {"type": "array", "items": rule_item, "uniqueItems": True},
            "restricted_topics": {"type": "array", "items": rule_item, "uniqueItems": True},
            "data_residency": {"type": "string", "minLength": 1, "maxLength": 128},
            "retention_days": {"type": "integer", "minimum": 0, "maximum": 36500},
            "deletion_sla_hours": {"type": "integer", "minimum": 0, "maximum": 87600},
            "platform_eligibility": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 128},
                "uniqueItems": True,
            },
            "policy_snapshot_id": {
                "anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]
            },
            "valid_from": {
                "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
            },
            "valid_to": {
                "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
            },
            "review_due_at": {
                "anyOf": [{"type": "string", "format": "date-time"}, {"type": "null"}]
            },
            "status": {"type": "string", "enum": ["draft", "active", "retired"]},
            "snapshot_hash": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"},
            "created_by": {"type": "string", "format": "uuid"},
            "created_at": {"type": "string", "format": "date-time"},
        }
        schema["required"] = list(schema["properties"])
        schema["additionalProperties"] = False
        schema["x-source"] = "GEO_REGION-001"
        schema["x-append-only"] = True
    elif name in {"VariantVersion", "AssetVersion"}:
        schema["properties"]["policy_snapshot_id"] = {
            "anyOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]
        }
        schema.setdefault("allOf", []).append({
            "if": {"properties": {"status": {"const": "approved"}}, "required": ["status"]},
            "then": {"properties": {"policy_snapshot_id": {"type": "string", "format": "uuid"}}},
        })
    if name in {"DistributionTargetVersion", "PublicationIntent"}:
        schema.setdefault("allOf", []).append({
            "if": {"properties": {"status": {"enum": [
                "active", "ready", "queued", "exported", "simulated", "dispatched"
            ]}}, "required": ["status"]},
            "then": {"properties": {"policy_snapshot_id": {"type": "string", "format": "uuid"}},
                     "required": ["policy_snapshot_id"]},
        })
    if name == "Observation":
        for field in ("metric_definition_version_no", "observation_version"):
            schema["properties"][field] = {"type": "integer", "minimum": 1}
        # json accepts any JSON type here; the referenced MetricDefinition's
        # value schema is additionally required by the analytics use case.
        schema["oneOf"] = [
            {"properties": {"metric_type": {"const": kind}, "metric_value": value}}
            for kind, value in (
                ("number", {"type": "number"}),
                ("boolean", {"type": "boolean"}),
                ("string", {"type": "string"}),
                ("enum", {"type": "string"}),
                ("json", {"type": ["object", "array", "string", "number", "boolean", "null"]}),
            )
        ]
        schema["properties"]["metric_value"] = {
            "type": ["object", "array", "string", "number", "boolean", "null"]
        }
    elif name == "MetricDefinition":
        schema["properties"]["version_no"] = {"type": "integer", "minimum": 1}
        schema["properties"]["quality_rules"] = {
            "type": "object", "properties": {"value_schema": {"type": "object", "minProperties": 1}},
            "required": [], "additionalProperties": False,
        }
        schema["allOf"] = [{
            "if": {"properties": {"metric_type": {"enum": ["json", "enum"]}}, "required": ["metric_type"]},
            "then": {"properties": {"quality_rules": {"required": ["value_schema"]}}},
        }]
    elif name == "DistributionTargetVersion":
        schema["properties"]["version_no"] = {"type": "integer", "minimum": 1}
        schema["properties"]["eligible_delivery_modes"] = {
            "type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"$ref": "./delivery-mode.schema.json"},
        }
        schema["oneOf"] = [
            {
                "title": "account-free manual target",
                "properties": {
                    "account_connection_id": {"type": "null"},
                    "eligible_delivery_modes": {"items": {"const": "manual_export"}},
                },
            },
            {
                "title": "synthetic simulation target",
                "properties": {
                    "account_connection_id": {"type": "null"},
                    "synthetic_target_id": {"type": "string", "minLength": 1},
                    "environment": {"enum": ["dev", "staging"]},
                    "eligible_delivery_modes": {
                        "items": {"enum": ["manual_export", "simulation"]},
                        "contains": {"const": "simulation"},
                    },
                },
            },
            {
                "title": "real or sandbox connection",
                "required": ["account_connection_id"],
                "properties": {
                    "account_connection_id": {"type": "string", "format": "uuid"},
                    "account_profile_id": {"type": "string", "format": "uuid"},
                    "synthetic_target_id": {"type": "null"},
                    "eligible_delivery_modes": {"items": {"enum": ["draft_only", "authorized_api"]}},
                },
            },
        ]
        schema.setdefault("allOf", []).append({
            "if": {
                "properties": {"synthetic_target_id": {"type": "string"}},
                "required": ["synthetic_target_id"],
            },
            "then": {
                "properties": {
                    "policy_snapshot_id": {"type": "string", "format": "uuid"},
                    "account_connection_id": {"type": "null"},
                },
                "required": ["policy_snapshot_id"],
            },
        })
    elif name == "DistributionTarget":
        statuses = schema["properties"].get("status", {}).get("enum", [])
        if "planned" not in statuses:
            schema["properties"]["status"]["enum"] = ["planned", *statuses]
    elif name == "PublicationIntent":
        schema["properties"]["delivery_mode"] = {"$ref": "./delivery-mode.schema.json"}
    elif name == "DeliveryAttempt":
        schema["properties"]["adapter_ref"] = {
            "type": "string",
            "pattern": "^(manual:export|fake:official@[A-Za-z0-9._-]+|platform:[A-Za-z0-9_-]+@[A-Za-z0-9._-]+)$",
        }
        schema["properties"]["attempt_no"] = {"type": "integer", "minimum": 1}
        schema["properties"]["max_attempts"] = {"type": "integer", "minimum": 1}
        schema["oneOf"] = [
            {
                "title": "manual or fake",
                "properties": {
                    "provider_mode": {"enum": ["manual", "fake"]},
                    "account_connection_id": {"type": "null"},
                },
            },
            {
                "title": "sandbox or authorized",
                "properties": {
                    "provider_mode": {"enum": ["sandbox", "authorized"]},
                    "account_connection_id": {"type": "string", "format": "uuid"},
                },
            },
        ]
    elif name == "KillSwitch":
        schema["properties"]["version"] = {"type": "integer", "minimum": 0}
        schema["properties"]["blocked_delivery_modes"] = {
            "type": "array", "uniqueItems": True,
            "items": {"$ref": "./delivery-mode.schema.json"},
        }
        require("version")
        require("blocked_delivery_modes")
        schema.setdefault("allOf", []).extend([
            {
                "if": {"properties": {"scope": {"const": "global"}}, "required": ["scope"]},
                "then": {"properties": {"org_id": {"type": "null"}, "scope_id": {"type": "null"}}},
            },
            {
                "if": {
                    "properties": {"scope": {"enum": ["platform", "account", "target", "content"]}},
                    "required": ["scope"],
                },
                "then": {
                    "properties": {
                        "org_id": {"type": "string", "format": "uuid"},
                        "scope_id": {"type": "string", "format": "uuid"},
                    }
                },
            },
        ])
    elif name == "AccountConnection":
        schema["allOf"] = [
            {
                "if": {"properties": {"connection_status": {"const": "connected"}}},
                "then": {"properties": {"authorization_status": {"const": "authorized"}}},
            },
            {
                "if": {"properties": {"authorization_status": {"enum": ["expired", "revoked"]}}},
                "then": {"properties": {"connection_status": {"enum": ["pending", "revoked"]}}},
            },
        ]
    elif name == "PolicySnapshot":
        schema["oneOf"] = [
            {
                "title": "global policy",
                "properties": {"org_id": {"type": "null"}, "subject_id": {"type": "null"}},
            },
            {
                "title": "tenant policy",
                "required": ["org_id", "subject_id"],
                "properties": {
                    "org_id": {"type": "string", "format": "uuid"},
                    "subject_id": {"type": "string", "format": "uuid"},
                },
            },
        ]
    elif name == "Entity":
        schema["properties"]["aliases"] = {
            "type": "array", "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        }
        schema["properties"]["version"] = {"type": "integer", "minimum": 0}
        schema["properties"]["canonical_name"]["minLength"] = 1
        schema["properties"]["entity_type"] = {
            "type": "string", "minLength": 1, "maxLength": 128,
            "pattern": "^[A-Za-z][A-Za-z0-9_.-]*$",
        }
    elif name == "Claim":
        for field in ("entity_ids",):
            schema["properties"][field] = {
                "type": "array", "items": {"type": "string", "format": "uuid"},
                "uniqueItems": True,
            }
        for field in ("applicable_versions", "applicable_regions", "applicable_locales"):
            schema["properties"][field] = {
                "type": "array", "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            }
        schema["properties"]["fact_type"] = {
            "type": "string", "minLength": 1, "maxLength": 128,
            "pattern": "^[a-z][a-z0-9_.-]*$",
        }
        schema["properties"]["version"] = {"type": "integer", "minimum": 0}
        schema.setdefault("allOf", []).append({
            "if": {
                "properties": {"valid_from": {"type": "string"}, "valid_to": {"type": "string"}},
                "required": ["valid_from", "valid_to"],
            },
            "then": {"description": "valid_to must be later than valid_from; enforced by the use case"},
        })
    elif name == "Evidence":
        for field in ("applicable_versions", "applicable_regions", "applicable_locales"):
            schema["properties"][field] = {
                "type": "array", "items": {"type": "string", "minLength": 1},
                "uniqueItems": True,
            }
        schema["properties"]["evidence_type"] = {
            "type": "string", "minLength": 1, "maxLength": 128,
            "pattern": "^[a-z][a-z0-9_.-]*$",
        }
        schema["properties"]["version"] = {"type": "integer", "minimum": 0}
        schema.setdefault("allOf", []).append({
            "if": {
                "properties": {"valid_from": {"type": "string"}, "valid_to": {"type": "string"}},
                "required": ["valid_from", "valid_to"],
            },
            "then": {"description": "valid_to must be later than valid_from; enforced by the use case"},
        })
    elif name == "Approval":
        schema["properties"]["quorum_reached"]["minimum"] = 0
        schema["properties"]["aggregate_version"]["minimum"] = 1
        schema["properties"]["decision_ids"] = {
            "type": "array", "items": {"type": "string", "format": "uuid"}, "uniqueItems": True,
        }
        schema["oneOf"] = [
            {
                "properties": {"quorum_required": {"const": count}},
                "if": {"properties": {"status": {"const": "approved"}}},
                "then": {"properties": {
                    "quorum_reached": {"minimum": count},
                    "decision_ids": {"minItems": count},
                    "decision": {"const": "approved"},
                    "reviewer_id": {"type": "string", "format": "uuid"},
                    "decided_at": {"type": "string", "format": "date-time"},
                }},
            }
            for count in (1, 2)
        ]


def object_schema(name: str, value: Any) -> dict[str, Any]:
    schema = value_schema(value)
    schema = {
        "$schema": DRAFT,
        "$id": f"{BASE_ID}{slug(name)}.schema.json",
        "title": name,
        **schema,
        "x-source": "section-4.6-field-catalogue",
    }
    add_cross_field_rules(name, schema)
    return schema


MODULE_OBJECTS = {
    "governance": ["PolicySnapshot", "PolicyDecision", "KillSwitch"],
    "foundation": ["TaskJob", "TaskFailure", "OutboxEvent", "Platform", "KillSwitch"],
    "iam": [],
    "distribution_account": ["AccountProfile", "AccountConnection", "AuthorizationEvidence"],
    "topic": ["TopicSignal", "TopicOpportunity", "TopicBrief", "TopicScoreSnapshot"],
    "provenance": ["Source", "SourceSnapshot", "RightsRecord", "RightsRecordVersion"],
    "knowledge": ["Entity", "Claim", "Evidence", "KnowledgeCore", "KnowledgeCoreVersion"],
    "canonical_content": ["CanonicalContent", "CanonicalContentVersion"],
    "production": ["ContentVariant", "VariantVersion"],
    "qa": [],
    "policy": ["PolicySnapshot", "PolicyDecision"],
    "approval": ["Approval", "ApprovalDecision"],
    "agent": [],
    "workflow": ["HumanTask", "TaskJob"],
    "model_gateway": [],
    "scheduler": [],
    "distribution_oauth": ["AuthorizationEvidence", "AccountConnection"],
    "evaluation": [],
    "audit": ["OutboxEvent", "DeletionRequest", "KillSwitch"],
    "knowledge_site": ["SitePageVersion"],
    "geo_content": ["GeoQueryFixture", "GeoRun"],
    "geo_region": ["RegionProfile", "RegionProfileVersion"],
    "media": ["Asset", "AssetVersion"],
    "distribution": ["DistributionTarget", "DistributionTargetVersion", "PublicationIntent", "ExportPackage", "DeliveryAttempt", "PublicationRecord"],
    "platform_adapter": ["Platform", "DistributionTargetVersion", "DeliveryAttempt", "PublicationRecord"],
    "analytics": ["Observation", "MetricDefinition"],
    "feedback": ["Observation", "FeedbackItem", "FeedbackAction"],
    "support": [],
    "operations": ["DeletionRequest", "KillSwitch"],
}

# Some implementation contracts are intentionally authored outside the
# section 4.6 field catalogue.  Keep them in the generated module union while
# preserving their hand-maintained, closed schema files.
MODULE_EXTRA_SCHEMA_REFS = {
    # These records are authored outside the 4.6 catalogue but are part of
    # the frozen foundation/governance unions.  Keep this list explicit so a
    # regeneration cannot silently shrink either union back to the initial
    # five-object scaffold.
    "foundation": [
        "./branch-protection.schema.json", "./runtime-entry.schema.json",
        "./database-config.schema.json", "./storage-config.schema.json",
        "./storage-object.schema.json", "./migration-baseline.schema.json",
        "./api-error.schema.json", "./correlation-context.schema.json",
        "./structured-log.schema.json", "./metrics-baseline.schema.json",
        "./tracing-cost-baseline.schema.json", "./cost-record.schema.json",
        "./api-contract-baseline.schema.json", "./event-compatibility-baseline.schema.json",
        "./synthetic-fixture.schema.json", "./architecture-guard.schema.json",
        "./redis-config.schema.json", "./supply-chain.schema.json",
    ],
    "governance": [
        "./data-processing-policy.schema.json", "./operational-targets.schema.json",
        "./real-account-dependency.schema.json", "./vendor-inventory.schema.json",
        "./vertical-scope.schema.json", "./risk-policy.schema.json",
        "./policy-card.schema.json", "./tech-stack-baseline.schema.json",
        "./release-levels.schema.json", "./raci-policy.schema.json",
    ],
    "geo_content": ["./geo-content-assessment.schema.json"],
}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if PRESERVE_EXISTING and path.exists():
        return
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def generate_events() -> int:
    registry = yaml.safe_load(EVENT_REGISTRY.read_text(encoding="utf-8")) or {}
    events = registry.get("events") or []
    envelope = {
        "$schema": DRAFT,
        "$id": f"{BASE_ID}event-envelope.schema.json",
        "title": "EventEnvelope",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "event_id", "event_type", "event_schema_version", "occurred_at", "org_id",
            "trace_id", "aggregate_type", "aggregate_id", "aggregate_version",
            "actor_type", "idempotency_key", "payload", "payload_hash",
        ],
        "properties": {
            "event_id": {"type": "string", "format": "uuid"},
            "event_type": {"type": "string", "pattern": "^[a-z0-9_.]+$"},
            "event_schema_version": {"type": "integer", "minimum": 1},
            "occurred_at": {"type": "string", "format": "date-time"},
            "org_id": {"type": "string", "format": "uuid"},
            "trace_id": {"type": "string", "minLength": 1},
            "correlation_id": {"type": ["string", "null"]},
            "causation_id": {"type": ["string", "null"]},
            "aggregate_type": {"type": "string", "minLength": 1},
            "aggregate_id": {"type": "string", "format": "uuid"},
            "aggregate_version": {"type": "integer", "minimum": 1},
            "actor_type": {"type": "string", "enum": ["user", "service", "system", "worker"]},
            "actor_id": {"type": ["string", "null"], "format": "uuid"},
            "idempotency_key": {"type": "string", "minLength": 1},
            "payload": {"type": "object", "additionalProperties": True},
            "payload_hash": {"type": "string", "pattern": "^[A-Fa-f0-9]{64}$"},
        },
    }
    write_json(EVENT_DIR / "event-envelope.schema.json", envelope)
    write_json(JSONSCHEMA_DIR / "event-envelope.schema.json", envelope)
    for event in events:
        name = event["event_type"]
        payload = {
            "type": "object",
            "required": ["aggregate_id", "aggregate_version"],
            "properties": {
                "aggregate_id": {"type": "string", "format": "uuid"},
                "aggregate_version": {"type": "integer", "minimum": 1},
                "from_state": {"type": ["string", "null"]},
                "to_state": {"type": ["string", "null"]},
                "command": {"type": ["string", "null"]},
                "snapshot_hash": {"type": ["string", "null"], "pattern": "^[A-Fa-f0-9]{64}$"},
                "reason": {"type": ["string", "null"]},
            },
            "additionalProperties": True,
        }
        schema = {
            "$schema": DRAFT,
            "$id": f"{BASE_ID}events/{name.replace('.', '-')}.schema.json",
            "title": name,
            "allOf": [
                {"$ref": "./event-envelope.schema.json"},
                {
                    "type": "object",
                    "properties": {
                        "event_type": {"const": name},
                        "event_schema_version": {"const": 1},
                        "payload": payload,
                    },
                },
            ],
            "x-event-kind": event.get("event_kind", "append_only"),
            "x-replay-policy": event.get("replay_policy", "idempotent_projection_replay"),
        }
        write_json(EVENT_DIR / f"{name.replace('.', '-')}.schema.json", schema)
    return len(events)


def main() -> None:
    catalogue = extract_catalogue()
    JSONSCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for name, value in catalogue.items():
        write_json(JSONSCHEMA_DIR / f"{slug(name)}.schema.json", object_schema(name, value))

    # Module-level aliases preserve the task registry's domain grouping while
    # each alias points to concrete object schemas.
    for module, objects in MODULE_OBJECTS.items():
        # A concrete object's file is authoritative. In particular Approval
        # must not be overwritten by a union referring back to itself.
        if module in {slug(name) for name in catalogue}:
            continue
        refs = [ref_schema(name) for name in objects if name in catalogue]
        refs.extend(
            {"$ref": ref}
            for ref in MODULE_EXTRA_SCHEMA_REFS.get(module, [])
            if (JSONSCHEMA_DIR / ref.removeprefix("./")).exists()
        )
        if refs:
            schema: dict[str, Any] = {
                "$schema": DRAFT,
                "$id": f"{BASE_ID}{module}.schema.json",
                "title": f"{module} contract union",
                "oneOf": refs,
                "x-module": module,
            }
        else:
            schema = {
                "$schema": DRAFT,
                "$id": f"{BASE_ID}{module}.schema.json",
                "title": f"{module} contract envelope",
                "type": "object",
                "required": ["contract_version", "payload"],
                "properties": {
                    "contract_version": {"type": "integer", "minimum": 1},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
                "x-module": module,
            }
        write_json(JSONSCHEMA_DIR / f"{module}.schema.json", schema)

    # Supplemental records referenced by tasks but intentionally absent from
    # the section 4.6 persisted-object catalogue.
    supplemental: dict[str, dict[str, Any]] = {
        "internal-iam": {
            "id": "uuid", "org_id": "uuid", "subject": "string", "display_name": "string",
            "roles": ["string"], "permissions": ["string"], "status": "active|disabled", "created_at": "datetime",
        },
        "topic-taxonomy": {
            "id": "uuid", "org_id": "uuid", "key": "string", "label": "string",
            "technical_versions": ["string"], "audiences": ["string"], "tags": ["string"],
            "status": "draft|active|retired", "created_at": "datetime",
        },
        "workflow-run": {
            "id": "uuid", "org_id": "uuid", "workflow_key": "string", "workflow_version": "integer",
            "status": "planned|running|paused|succeeded|failed|cancelled", "input_hash": "sha256", "created_at": "datetime",
        },
        "workflow-step": {
            "id": "uuid", "org_id": "uuid", "workflow_run_id": "uuid", "step_key": "string",
            "step_no": "integer", "status": "queued|running|waiting|succeeded|failed|cancelled", "input_hash": "sha256", "created_at": "datetime",
        },
        "model-gateway": {
            "id": "uuid", "org_id": "uuid", "provider": "string", "model": "string", "status": "active|disabled",
            "data_region": "string", "retention_policy": "string", "created_at": "datetime",
        },
        "qa-report": {"id": "uuid", "org_id": "uuid", "subject_type": "string", "subject_id": "uuid", "rule_version": "string", "status": "passed|failed|needs_review", "findings": [], "created_at": "datetime"},
        "audit-log": {
            "id": "uuid", "org_id": "uuid", "trace_id": "string", "actor_type": "user|service|system|worker",
            "actor_id": "uuid|null", "action": "string", "subject_type": "string", "subject_id": "uuid|null",
            "input_hash": "sha256|null", "result": "success|denied|failed", "reason": "string|null", "created_at": "datetime",
        },
        "oauth-authorization-session": {
            "id": "uuid", "org_id": "uuid", "provider": "string", "state_hash": "sha256", "pkce_challenge": "string",
            "redirect_uri": "string", "status": "created|callback_received|verified|expired|cancelled", "expires_at": "datetime", "created_at": "datetime",
        },
        "token-lease": {
            "id": "uuid", "org_id": "uuid", "account_connection_id": "uuid", "secret_reference": "vault-ref",
            "lease_version": "integer", "status": "active|expired|revoked", "expires_at": "datetime", "created_at": "datetime",
        },
        "publisher-capability": {
            "id": "uuid", "platform_id": "uuid", "version": "integer", "actions": ["string"],
            "limits": {}, "policy_version": "string", "status": "draft|active|retired", "created_at": "datetime",
        },
        "render-job": {
            "id": "uuid", "org_id": "uuid", "asset_version_id": "uuid", "status": "planned|running|succeeded|failed|dead_letter",
            "input_hash": "sha256", "attempt_count": "integer", "created_at": "datetime",
        },
        "pilot-run": {
            "id": "uuid", "org_id": "uuid", "name": "string", "account_ids": ["uuid"],
            "start_at": "datetime", "end_at": "datetime|null", "status": "planned|running|completed|stopped", "created_at": "datetime",
        },
        "refresh-recommendation": {
            "id": "uuid", "org_id": "uuid", "feedback_item_id": "uuid", "recommendation_type": "refresh|reprioritize|retire",
            "target_id": "uuid", "confidence": "number", "status": "proposed|approved|rejected|executed", "created_at": "datetime",
        },
        "sandbox-run": {
            "id": "uuid", "org_id": "uuid", "input_hash": "sha256", "workspace_ref": "private-object-ref",
            "image_digest": "sha256", "allowlisted_commands": ["string"], "network": "none",
            "secret_mounts": [], "cpu_ms": "integer", "memory_mb": "integer", "timeout_ms": "integer",
            "status": "queued|running|passed|failed|blocked|timed_out", "stdout_ref": "private-object-ref|null",
            "stderr_ref": "private-object-ref|null", "created_at": "datetime",
        },
        "eval-run": {"id": "uuid", "org_id": "uuid", "prompt_version": "string", "model_version": "string", "dataset_hash": "sha256", "status": "planned|running|completed|failed", "created_at": "datetime"},
        "agent-definition": {"id": "uuid", "org_id": "uuid", "key": "string", "version": "integer", "input_schema_ref": "string", "output_schema_ref": "string", "tool_allowlist": ["string"], "status": "draft|active|retired"},
        "agent-run": {"id": "uuid", "org_id": "uuid", "agent_definition_id": "uuid", "status": "queued|running|succeeded|failed|needs_review", "input_hash": "sha256", "output_hash": "sha256|null", "created_at": "datetime"},
        "model-call": {
            "id": "uuid", "org_id": "uuid", "model_config_id": "uuid", "provider": "string", "model": "string",
            "model_version": "string", "prompt_version": "string", "request_hash": "sha256", "input_hash": "sha256",
            "output_hash": "sha256|null", "status": "started|succeeded|failed|timed_out|budget_exceeded",
            "input_tokens": "integer|null", "output_tokens": "integer|null", "cost_cents": "integer|null",
            "latency_ms": "integer|null", "attempt_no": "integer", "error_code": "string|null",
            "response_ref": "private-object-ref|null", "created_at": "datetime",
        },
        "task-failure": {
            "id": "uuid", "org_id": "uuid", "job_id": "uuid", "attempt_count": "integer",
            "error_class": "deterministic|transient|unknown", "error_code": "string",
            "message_redacted": "string|null", "retryable": "boolean", "trace_id": "string", "occurred_at": "datetime",
        },
        "qa-report": {"id": "uuid", "org_id": "uuid", "subject_type": "string", "subject_id": "uuid", "rule_version": "string", "status": "passed|failed|needs_review", "findings": [], "created_at": "datetime"},
        "support-thread": {"id": "uuid", "org_id": "uuid", "platform_id": "uuid|null", "external_thread_id": "string|null", "status": "open|pending|resolved|escalated", "created_at": "datetime"},
        "lineage-query": {"org_id": "uuid", "subject_type": "string", "subject_id": "uuid", "nodes": [], "edges": []},
        "scheduler-job": {"id": "uuid", "org_id": "uuid", "job_type": "string", "schedule": "string", "status": "active|paused|retired", "created_at": "datetime"},
    }
    for name, value in supplemental.items():
        write_json(JSONSCHEMA_DIR / f"{name}.schema.json", object_schema(name, value))

    print(f"generated {len(catalogue)} object schemas, {generate_events()} event schemas")


if __name__ == "__main__":
    main()
