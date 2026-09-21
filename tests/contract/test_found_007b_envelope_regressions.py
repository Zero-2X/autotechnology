from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from scripts.check_event_compatibility import check_compatibility, ENVELOPE_BASELINE
from scripts.check_event_compatibility import _narrowed

ROOT = Path(__file__).resolve().parents[2]


def candidate(tmp_path):
    registry = yaml.safe_load((ROOT / "docs/contracts/event-registry.yaml").read_text(encoding="utf-8"))
    baseline = yaml.safe_load((ROOT / "docs/foundation/event-compatibility-baseline-v1.yaml").read_text(encoding="utf-8"))
    entry = registry["events"][0]
    old = next(e for e in baseline["events"] if e["event_type"] == entry["event_type"])
    path = tmp_path / "candidate.schema.json"
    schema = json.loads((ROOT / entry["schema_ref"]).read_text(encoding="utf-8"))
    path.write_text(json.dumps(schema), encoding="utf-8")
    entry["schema_ref"] = str(path)
    old["schema_ref"] = str(path)
    registry["events"] = [entry]
    baseline["events"] = [old]
    envelope = json.loads(ENVELOPE_BASELINE.read_text(encoding="utf-8"))
    (tmp_path / "event-envelope.schema.json").write_text(json.dumps(envelope), encoding="utf-8")
    assert check_compatibility(registry, baseline) == ([], [])
    return registry, baseline, path, schema, envelope


@pytest.mark.parametrize("field", ["org_id", "trace_id", "idempotency_key", "payload_hash"])
def test_envelope_required_fields_cannot_silently_disappear(tmp_path, field):
    registry, baseline, _, _, envelope = candidate(tmp_path)
    envelope["required"].remove(field)
    (tmp_path / "event-envelope.schema.json").write_text(json.dumps(envelope), encoding="utf-8")
    errors, _ = check_compatibility(registry, baseline)
    assert errors == [f"{registry['events'][0]['event_type']}: envelope differs from frozen v1 baseline"]


def test_envelope_constraints_are_frozen(tmp_path):
    registry, baseline, _, _, envelope = candidate(tmp_path)
    envelope["properties"]["org_id"] = {"type": "string"}
    (tmp_path / "event-envelope.schema.json").write_text(json.dumps(envelope), encoding="utf-8")
    errors, _ = check_compatibility(registry, baseline)
    assert any("frozen" in e for e in errors)


@pytest.mark.parametrize("replacement", [[], False, {"allOf": [True, {}]}, {"type": "not-a-type"}])
def test_malformed_event_schema_is_reported_not_crashed(tmp_path, replacement):
    registry, baseline, path, _, _ = candidate(tmp_path)
    path.write_text(json.dumps(replacement), encoding="utf-8")
    assert check_compatibility(registry, baseline)[0]


@pytest.mark.parametrize("registry,baseline", [(None, {}), ({}, None), ({"events": [None]}, {}), ({"events": {}}, {})])
def test_malformed_registry_input_is_reported(registry, baseline):
    assert check_compatibility(registry, baseline)[0]


def test_freezing_baseline_does_not_mutate_inputs(tmp_path):
    registry, baseline, _, _, _ = candidate(tmp_path)
    before = deepcopy((registry, baseline))
    assert check_compatibility(registry, baseline) == ([], [])
    assert (registry, baseline) == before


@pytest.mark.parametrize("old,new", [
    ({"type": "object", "properties": {"score": {"type": "integer"}}},
     {"type": "object", "properties": {"score": {"type": "integer", "minimum": 1}}}),
    ({"type": "object"}, {"type": "object", "required": ["score"]}),
    ({"items": {"type": "string"}}, {"items": {"type": "string", "minLength": 2}}),
    ({"minItems": 1}, {"minItems": 2}),
    ({}, {"uniqueItems": True}),
    ({"additionalProperties": {"type": "string"}}, {"additionalProperties": False}),
    ({}, {"oneOf": [{"type": "string"}, {"type": "integer"}]}),
    ({}, {"$ref": "./unreviewed.schema.json"}),
    ({"type": ["string", "null"]}, {"type": "string"}),
    ({"type": "number"}, {"type": "integer"}),
    (True, False),
])
def test_recursive_payload_narrowing_is_detected(old, new):
    assert _narrowed(old, new)


@pytest.mark.parametrize("old,new", [
    ({"type": "string"}, {"type": ["string", "null"]}),
    ({"type": "integer"}, {"type": "number"}),
    ({"type": ["string", "null"]}, {"type": ["null", "string"]}),
    ({"items": {"minLength": 2}}, {"items": {"minLength": 1}}),
    ({"additionalProperties": False}, {"additionalProperties": True}),
    ({"properties": {"score": {"minimum": 2}}}, {"properties": {"score": {"minimum": 1}}}),
    (False, True),
])
def test_recursive_payload_widening_is_compatible(old, new):
    assert _narrowed(old, new) == []


def test_checker_rejects_nested_array_constraint_change(tmp_path):
    registry, baseline, path, schema, _ = candidate(tmp_path)
    old = {"type": "array", "items": {"type": "object", "properties": {"score": {"type": "integer"}}}}
    baseline["events"][0]["payload"]["properties"]["scores"] = deepcopy(old)
    schema["allOf"][1]["properties"]["payload"]["properties"]["scores"] = old
    path.write_text(json.dumps(schema), encoding="utf-8")
    assert check_compatibility(registry, baseline) == ([], [])
    old["items"]["properties"]["score"]["minimum"] = 1
    path.write_text(json.dumps(schema), encoding="utf-8")
    errors, _ = check_compatibility(registry, baseline)
    assert any("scores constraint narrowed: items.properties.score.minimum" in error for error in errors)


@pytest.mark.parametrize("field", ["ordering_key", "consumer_dedupe_key"])
def test_registry_delivery_keys_cannot_change(tmp_path, field):
    registry, baseline, _, _, _ = candidate(tmp_path)
    registry["events"][0][field] = "trace_id"
    errors, _ = check_compatibility(registry, baseline)
    assert any(f"registry field changed: {field}" in error for error in errors)


@pytest.mark.parametrize("rule", [
    {"not": {}}, {"const": None}, {"enum": [{}]},
    {"dependentRequired": {"aggregate_id": ["secret_field"]}},
    {"propertyNames": {"maxLength": 1}}, {"$ref": "./changed.schema.json"},
])
def test_root_payload_constraints_cannot_bypass_snapshot(tmp_path, rule):
    registry, baseline, path, schema, _ = candidate(tmp_path)
    schema["allOf"][1]["properties"]["payload"].update(rule)
    path.write_text(json.dumps(schema), encoding="utf-8")
    assert check_compatibility(registry, baseline)[0]


@pytest.mark.parametrize("location", ["root", "envelope", "specific", "identity"])
def test_constraints_outside_payload_are_not_ignored(tmp_path, location):
    registry, baseline, path, schema, _ = candidate(tmp_path)
    node = {"root": schema, "envelope": schema["allOf"][0], "specific": schema["allOf"][1],
            "identity": schema["allOf"][1]["properties"]["event_type"]}[location]
    node["not"] = {}
    path.write_text(json.dumps(schema), encoding="utf-8")
    assert check_compatibility(registry, baseline)[0]


def test_unchanged_ref_is_not_proof_of_unchanged_dependency():
    assert _narrowed({"$ref": "./mutable.schema.json"}, {"$ref": "./mutable.schema.json"})


def test_new_null_const_is_narrowing():
    assert _narrowed({}, {"const": None}) == ["const"]


def test_new_optional_reference_requires_frozen_dependencies(tmp_path):
    registry, baseline, path, schema, _ = candidate(tmp_path)
    schema["allOf"][1]["properties"]["payload"]["properties"]["optional"] = {"$ref": "./mutable.json"}
    path.write_text(json.dumps(schema), encoding="utf-8")
    assert any("frozen dependency" in error for error in check_compatibility(registry, baseline)[0])


def test_reference_like_instance_data_is_not_a_schema_reference(tmp_path):
    registry, baseline, path, schema, _ = candidate(tmp_path)
    schema["allOf"][1]["properties"]["payload"]["properties"]["optional"] = {"const": {"$ref": "a literal value"}}
    path.write_text(json.dumps(schema), encoding="utf-8")
    assert check_compatibility(registry, baseline) == ([], [])
