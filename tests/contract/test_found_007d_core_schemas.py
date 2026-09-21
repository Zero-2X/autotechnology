"""Incremental FOUND-007D regression tests; not full task acceptance yet."""
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from scripts.generate_json_schemas import value_schema, object_schema, extract_catalogue, slug
from scripts.check_json_schemas import check


ROOT = Path(__file__).resolve().parents[2]


def test_all_object_contracts_pass_offline_integrity_gate():
    assert check(ROOT / "packages/contracts/jsonschema") == []


def test_core_catalogue_files_are_registered_and_closed():
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(t for t in registry["tasks"] if t["id"] == "FOUND-007D")
    for name in extract_catalogue():
        ref = f"packages/contracts/jsonschema/{slug(name)}.schema.json"
        assert ref in task["contract_refs"], name
        schema = json.loads((ROOT / ref).read_text(encoding="utf-8"))
        assert schema["type"] == "object", name
        assert schema["additionalProperties"] is False, name
        assert set(schema["required"]) == set(schema["properties"]), name


def test_integrity_gate_rejects_unresolved_ref_and_self_union(tmp_path):
    path = tmp_path / "broken.schema.json"
    path.write_text(json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "https://schemas.example/broken.schema.json", "oneOf": [{"$ref": "./broken.schema.json"}, {"$ref": "./missing.schema.json"}]}), encoding="utf-8")
    errors = check(tmp_path)
    assert any("self-referencing" in error for error in errors)
    assert any("unresolved" in error for error in errors)


def target_schema():
    directory = ROOT / "packages/contracts/jsonschema"
    schema = json.loads((directory / "distribution-target-version.schema.json").read_text())
    delivery_mode = json.loads((directory / "delivery-mode.schema.json").read_text())
    registry = Registry().with_resource(delivery_mode["$id"], Resource.from_contents(delivery_mode))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def target(**overrides):
    base = {
        "id": "00000000-0000-4000-8000-000000000001", "org_id": "00000000-0000-4000-8000-000000000001", "distribution_target_id": "00000000-0000-4000-8000-000000000001", "version_no": 1, "platform_id": "00000000-0000-4000-8000-000000000001", "market": "US", "locale": "en-US", "channel": "article", "environment": "dev", "region_profile_version_id": "00000000-0000-4000-8000-000000000001", "account_profile_id": None, "account_profile_snapshot": {}, "account_connection_id": None, "account_connection_snapshot": {}, "synthetic_target_id": "fake", "capability_snapshot": {}, "policy_snapshot_id": None, "eligible_delivery_modes": ["simulation"], "status": "draft", "snapshot_hash": "a" * 64, "etag": "v1", "created_by": "00000000-0000-4000-8000-000000000001", "created_at": "2026-09-16T00:00:00Z", "retired_at": None,
    }
    return {**base, **overrides}


def observation():
    return {
        "id": "00000000-0000-4000-8000-000000000001",
        "org_id": "00000000-0000-4000-8000-000000000001",
        "source": "fake", "subject_type": "topic",
        "subject_id": "00000000-0000-4000-8000-000000000001",
        "metric_definition_id": "00000000-0000-4000-8000-000000000001",
        "metric_definition_version_no": 1, "metric_name": "synthetic",
        "metric_type": "number", "metric_value": 0,
        "observed_at": "2026-09-16T00:00:00Z", "locale": None,
        "region": None, "data_quality": "estimated", "dedupe_key": "fixture",
        "source_snapshot_ref": None, "observation_version": 1,
    }


def validator():
    schema = json.loads((ROOT / "packages/contracts/jsonschema/observation.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.mark.parametrize("kind,value", [("number", 1.5), ("boolean", True), ("string", "ok"), ("enum", "ok"), ("json", {"synthetic": [1, None]})])
def test_metric_type_valid_values(kind, value):
    item = {**observation(), "metric_type": kind, "metric_value": value}
    validator().validate(item)


@pytest.mark.parametrize("kind,value", [("number", True), ("number", "1"), ("boolean", 1), ("string", {}), ("enum", []), ("unknown", 1)])
def test_metric_type_invalid_values(kind, value):
    assert not validator().is_valid({**observation(), "metric_type": kind, "metric_value": value})


@pytest.mark.parametrize("field,value", [("org_id", None), ("org_id", "not-a-uuid"), ("observation_version", "1"), ("metric_definition_version_no", 0), ("unknown", True)])
def test_tenant_version_and_unknown_fields(field, value):
    assert not validator().is_valid({**observation(), field: value})


def test_numeric_catalogue_examples_do_not_generate_empty_schemas():
    assert value_schema(1) == {"type": "integer"}
    assert value_schema(0.5) == {"type": "number"}
    assert value_schema(True) == {"type": "boolean"}
    schema = object_schema("Observation", extract_catalogue()["Observation"])
    Draft202012Validator.check_schema(schema)
    assert len(schema["oneOf"]) == 5
    assert not Draft202012Validator(schema).is_valid({**observation(), "metric_value": "bad"})


def test_target_delivery_and_policy_cross_fields():
    assert target_schema().is_valid(target(policy_snapshot_id="00000000-0000-4000-8000-000000000001"))
    assert target_schema().is_valid(target(environment="staging", policy_snapshot_id="00000000-0000-4000-8000-000000000001"))
    assert not target_schema().is_valid(target(environment="prod"))
    assert not target_schema().is_valid(target(eligible_delivery_modes=["simulation"], synthetic_target_id=None, account_connection_id="00000000-0000-4000-8000-000000000001"))
    assert not target_schema().is_valid(target(status="active", policy_snapshot_id=None))
    assert target_schema().is_valid(target(status="active", policy_snapshot_id="00000000-0000-4000-8000-000000000001"))
    assert not target_schema().is_valid(target(eligible_delivery_modes=["authorized_api"], account_profile_id=None, account_connection_id="00000000-0000-4000-8000-000000000001", synthetic_target_id=None))


def test_all_numeric_catalogue_fields_have_matching_machine_types():
    def check(example, schema, location):
        if isinstance(example, (bool, int, float)):
            expected = "boolean" if isinstance(example, bool) else "integer" if isinstance(example, int) else "number"
            assert schema.get("type") == expected, location
        elif isinstance(example, dict):
            for key, value in example.items():
                check(value, schema["properties"][key], f"{location}.{key}")
        elif isinstance(example, list) and example:
            check(example[0], schema["items"], f"{location}[]")
    for name, example in extract_catalogue().items():
        schema = json.loads((ROOT / f"packages/contracts/jsonschema/{slug(name)}.schema.json").read_text(encoding="utf-8"))
        # Observation.metric_value is deliberately typed by the discriminator,
        # not by its numeric placeholder in the human-readable catalogue.
        if name == "Observation":
            example = {k: v for k, v in example.items() if k != "metric_value"}
        check(example, schema, name)
