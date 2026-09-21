"""Validate event schemas and compare them with the FOUND-007B baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/contracts/event-registry.yaml"
BASELINE = ROOT / "docs/foundation/event-compatibility-baseline-v1.yaml"
ENVELOPE_BASELINE = ROOT / "docs/foundation/event-envelope-baseline-v1.schema.json"
ANNOTATIONS = {"title", "description", "$comment", "default", "examples", "deprecated", "readOnly", "writeOnly"}


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _schema_payload(schema: dict[str, Any]) -> dict[str, Any]:
    branches = schema.get("allOf") or []
    specific = branches[1] if len(branches) > 1 and isinstance(branches[1], dict) else {}
    payload = specific.get("properties", {}).get("payload") or {}
    return {"required": list(payload.get("required", [])), "properties": payload.get("properties") or {}, "constraints": {key: value for key, value in payload.items() if key not in {"type", "required", "properties"} | ANNOTATIONS}}


def _has_unfrozen_reference(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if "$ref" in schema or "$dynamicRef" in schema:
        return True
    children = []
    for key in ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas"):
        children.extend(schema.get(key, {}).values())
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        children.extend(schema.get(key, []))
    for key in ("items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems", "contains", "propertyNames", "if", "then", "else", "not", "contentSchema"):
        if key in schema:
            children.append(schema[key])
    return any(_has_unfrozen_reference(child) for child in children)


def _narrowed(old: dict[str, Any] | bool, new: dict[str, Any] | bool) -> list[str]:
    if new is True or old is False:
        return []
    if new is False:
        return ["false schema"] if old is not False else []
    if old is True:
        old = {}
    issues = []
    for key, direction in (("minLength", "up"), ("minimum", "up"), ("maxLength", "down"), ("maximum", "down"), ("minProperties", "up"), ("maxProperties", "down"), ("minItems", "up"), ("maxItems", "down"), ("exclusiveMinimum", "up"), ("exclusiveMaximum", "down")):
        if key in new and (key not in old or (direction == "up" and new[key] > old[key]) or (direction == "down" and new[key] < old[key])):
            issues.append(key)
    if "enum" in new and ("enum" not in old or any(value not in new["enum"] for value in old["enum"])):
        issues.append("enum")
    for key in ("pattern", "format", "const"):
        if key in new and (key not in old or new[key] != old[key]):
            issues.append(key)
    if "type" in new:
        old_types = old.get("type", [])
        new_types = new["type"]
        old_types = {old_types} if isinstance(old_types, str) else set(old_types)
        new_types = {new_types} if isinstance(new_types, str) else set(new_types)
        if not old_types or any(t not in new_types and not (t == "integer" and "number" in new_types) for t in old_types):
            issues.append("type")
    for field in sorted(set(old.get("required", [])) ^ set(new.get("required", []))):
        issues.append(f"required.{field}")
    old_props, new_props = old.get("properties", {}), new.get("properties", {})
    for field in sorted(set(old_props) | set(new_props)):
        if field not in new_props:
            issues.append(f"properties.{field} removed")
            continue
        previous = old_props.get(field, old.get("additionalProperties", True))
        issues.extend(f"properties.{field}.{issue}" for issue in _narrowed(previous, new_props[field]))
    for key in ("items", "additionalProperties"):
        issues.extend(f"{key}.{issue}" for issue in _narrowed(old.get(key, True), new.get(key, True)))
    if new.get("uniqueItems", False) and not old.get("uniqueItems", False):
        issues.append("uniqueItems")
    # These keywords need semantic/ref resolution to prove compatibility. Fail
    # closed on changes instead of silently accepting an unverified v1 change.
    for key in ("$ref", "$dynamicRef", "$defs", "allOf", "anyOf", "oneOf", "not", "if", "then", "else", "prefixItems", "contains", "minContains", "maxContains", "patternProperties", "propertyNames", "dependentRequired", "dependentSchemas", "unevaluatedProperties", "unevaluatedItems", "multipleOf"):
        if old.get(key) != new.get(key):
            issues.append(f"{key} changed; compatibility requires review")
    supported = ANNOTATIONS | {"type", "const", "enum", "pattern", "format", "minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minProperties", "maxProperties", "minItems", "maxItems", "uniqueItems", "required", "properties", "items", "additionalProperties"}
    # Ref/compound equality alone cannot prove compatibility: their referenced
    # contents or sibling constraints can change without changing this keyword.
    for key in sorted((set(old) | set(new)) - supported):
        if not any(issue.startswith(key + " changed") for issue in issues):
            issues.append(f"{key} requires a versioned schema review")
    return issues


def check_compatibility(registry: dict[str, Any], baseline: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(registry, dict) or not isinstance(baseline, dict):
        return ["registry and baseline must be objects"], warnings
    entries = registry.get("events") or []
    old_entries = baseline.get("events") or []
    for label, values in (("registry", entries), ("baseline", old_entries)):
        if not isinstance(values, list) or not values or any(not isinstance(e, dict) for e in values):
            return [f"{label}: events must be a nonempty list of objects"], warnings
        names = [entry.get("event_type") for entry in values]
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
            return [f"{label}: duplicate or invalid event_type"], warnings
    try:
        frozen_envelope = json.loads(ENVELOPE_BASELINE.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(frozen_envelope)
        if not isinstance(frozen_envelope, dict) or frozen_envelope.get("type") != "object":
            raise ValueError("frozen envelope must be an object schema")
    except (OSError, ValueError, SchemaError):
        return ["missing or invalid frozen envelope baseline"], warnings
    checked_envelopes = set()
    current: dict[str, dict[str, Any]] = {}
    for entry in entries:
        event_type = entry.get("event_type")
        if not isinstance(event_type, str) or event_type in current:
            errors.append(f"duplicate or invalid event_type: {event_type!r}")
            continue
        ref = entry.get("schema_ref")
        path = ROOT / str(ref)
        if not path.exists():
            errors.append(f"{event_type}: missing schema ref {ref}")
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
        except (OSError, ValueError, SchemaError) as exc:
            errors.append(f"{event_type}: invalid schema: {exc}")
            continue
        if not isinstance(schema, dict):
            errors.append(f"{event_type}: event schema must be an object")
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{event_type}: schema must use Draft 2020-12")
        if not schema.get("$id"):
            errors.append(f"{event_type}: missing schema $id")
        branches = schema.get("allOf")
        if not isinstance(branches, list) or len(branches) != 2 or not all(isinstance(b, dict) for b in branches):
            errors.append(f"{event_type}: expected envelope and event allOf branches")
            continue
        # v1's frozen layout has no other validating siblings. Do not let a new
        # root/branch constraint bypass the payload comparison below.
        for label, node, allowed in (
            ("event root", schema, {"$schema", "$id", "allOf", "x-event-kind", "x-replay-policy"}),
            ("envelope branch", branches[0], {"$ref"}),
            ("event branch", branches[1], {"type", "properties"}),
        ):
            for key in sorted(set(node) - allowed - ANNOTATIONS):
                errors.append(f"{event_type}: {label} keyword {key} requires a versioned schema review")
        if branches[1].get("type") != "object":
            errors.append(f"{event_type}: event branch must be an object")
        if branches[0].get("$ref") != "./event-envelope.schema.json" or not (path.parent / "event-envelope.schema.json").is_file():
            errors.append(f"{event_type}: missing envelope ref")
        envelope_path = path.parent / "event-envelope.schema.json"
        if envelope_path not in checked_envelopes:
            checked_envelopes.add(envelope_path)
            try:
                envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(envelope)
                if envelope != frozen_envelope:
                    errors.append(f"{event_type}: envelope differs from frozen v1 baseline")
            except (OSError, ValueError, SchemaError):
                errors.append(f"{event_type}: missing or invalid envelope schema")
        specific = schema.get("allOf", [{}, {}])[1] if len(schema.get("allOf", [])) > 1 else {}
        props = specific.get("properties", {})
        if set(props) != {"event_type", "event_schema_version", "payload"}:
            errors.append(f"{event_type}: event branch properties changed")
        type_schema = props.get("event_type", {})
        version_schema = props.get("event_schema_version", {})
        if not isinstance(type_schema, dict) or not isinstance(version_schema, dict):
            errors.append(f"{event_type}: event type and version need object schemas")
            continue
        for label, rule in (("event_type", type_schema), ("event_schema_version", version_schema)):
            if set(rule) - {"const"} - ANNOTATIONS:
                errors.append(f"{event_type}: {label} constraint changed")
        if type_schema.get("const") != event_type:
            errors.append(f"{event_type}: event_type const mismatch")
        version = version_schema.get("const")
        if type(version) is not int or version < 1:
            errors.append(f"{event_type}: event_schema_version must be a positive const")
        payload = props.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "object" or "aggregate_id" not in (payload.get("required") or []) or "aggregate_version" not in (payload.get("required") or []):
            errors.append(f"{event_type}: payload must require aggregate_id and aggregate_version")
            continue
        if _has_unfrozen_reference(payload):
            errors.append(f"{event_type}: payload reference has no frozen dependency bundle; use a versioned schema review")
        for metadata in ("event_kind", "replay_policy"):
            if schema.get(f"x-{metadata.replace('_', '-')}") != entry.get(metadata):
                errors.append(f"{event_type}: {metadata} metadata mismatch")
        current[event_type] = {"entry": entry, "version": version, "payload": _schema_payload(schema)}

    old_events = {event["event_type"]: event for event in (baseline.get("events") or [])}
    for event_type, old in old_events.items():
        if event_type not in current:
            errors.append(f"removed baseline event: {event_type}")
            continue
        new = current[event_type]
        for field in ("schema_ref", "producer", "aggregate_type", "event_kind", "side_effect_scope", "replay_policy"):
            if new["entry"].get(field) != old.get(field):
                errors.append(f"{event_type}: registry field changed: {field}")
        # These keys were not stored in the historical payload baseline. Their
        # values are fixed by the existing event registry contract.
        for field, expected in (("ordering_key", "aggregate_id"), ("consumer_dedupe_key", "event_id")):
            if new["entry"].get(field) != expected:
                errors.append(f"{event_type}: registry field changed: {field}")
        if old.get("event_schema_version") != new["version"]:
            errors.append(f"{event_type}: schema version changed")
        old_required = set((old.get("payload") or {}).get("required") or [])
        new_required = set((new["payload"] or {}).get("required") or [])
        for field in sorted(old_required - new_required):
            errors.append(f"{event_type}: required payload field removed: {field}")
        for field in sorted(new_required - old_required):
            errors.append(f"{event_type}: new required payload field: {field}")
        old_props = (old.get("payload") or {}).get("properties") or {}
        new_props = new["payload"].get("properties") or {}
        for issue in _narrowed(old.get("payload", {}).get("constraints", {}), new["payload"]["constraints"]):
            errors.append(f"{event_type}: payload constraint narrowed: {issue}")
        for field, old_prop in old_props.items():
            if field not in new_props:
                errors.append(f"{event_type}: payload property removed: {field}")
                continue
            for issue in _narrowed(old_prop, new_props[field]):
                errors.append(f"{event_type}: payload property {field} constraint narrowed: {issue}")
    for event_type in sorted(set(current) - set(old_events)):
        warnings.append(f"new event type: {event_type}")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    try:
        registry, baseline = _load(args.registry), _load(args.baseline)
        errors, warnings = check_compatibility(registry, baseline)
    except (OSError, yaml.YAMLError, TypeError) as exc:
        print(f"errors=1 warnings=0\nERROR: {exc}")
        return 1
    print(f"events={len(registry.get('events') or [])} baseline_events={len(baseline.get('events') or [])} errors={len(errors)} warnings={len(warnings)}")
    for item in warnings: print(f"WARNING: {item}")
    for item in errors: print(f"ERROR: {item}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
