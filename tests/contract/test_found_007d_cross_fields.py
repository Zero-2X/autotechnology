"""Explicit cross-field cases over synthetic complete records."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
ID = "00000000-0000-4000-8000-000000000001"


def sample(rule):
    # Populate unrelated required fields. Test cases explicitly set all fields
    # involved in the invariant, and validate the positive control first.
    if "const" in rule:
        return rule["const"]
    if "enum" in rule:
        return rule["enum"][0]
    if "anyOf" in rule:
        return sample(next((r for r in rule["anyOf"] if r.get("type") == "null"), rule["anyOf"][0]))
    kind = rule.get("type")
    if isinstance(kind, list):
        kind = "null" if "null" in kind else kind[0]
    if kind == "null":
        return None
    if kind == "object":
        return {key: sample(rule["properties"][key]) for key in rule.get("required", [])}
    if kind == "array":
        return [sample(rule["items"]) for _ in range(rule.get("minItems", 0))]
    if kind in ("integer", "number"):
        return max(rule.get("minimum", 0), 1)
    if kind == "boolean":
        return False
    if rule.get("format") == "uuid":
        return ID
    if rule.get("format") == "date-time":
        return "2026-09-16T00:00:00Z"
    if "64" in rule.get("pattern", ""):
        return "a" * 64
    if rule.get("pattern") == "^private://":
        return "private://synthetic/body"
    return "synthetic"


def record(name, **changes):
    directory = ROOT / "packages/contracts/jsonschema"
    schema = json.loads((directory / f"{name}.schema.json").read_text(encoding="utf-8"))
    registry = Registry()
    for path in directory.glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()), {**sample(schema), **changes}


@pytest.mark.parametrize("name,initial,final", [
    ("variant-version", "draft", "approved"), ("asset-version", "planned", "approved"),
    ("publication-intent", "planned", "ready"), ("publication-intent", "planned", "queued"),
])
def test_policy_snapshot_before_activation(name, initial, final):
    changes = {"status": initial, "policy_snapshot_id": None}
    if name == "publication-intent":
        changes["delivery_mode"] = "manual_export"
    validator, value = record(name, **changes)
    validator.validate(value)
    value["status"] = final
    assert not validator.is_valid(value)
    value["policy_snapshot_id"] = ID
    validator.validate(value)


def test_policy_global_and_tenant_scope_cannot_be_mixed():
    validator, value = record("policy-snapshot", org_id=None, subject_id=None)
    validator.validate(value)
    value["subject_id"] = ID
    assert not validator.is_valid(value)
    value["org_id"] = ID
    validator.validate(value)


def test_connected_requires_authorization_and_revoked_cannot_remain_connected():
    validator, value = record("account-connection", connection_status="connected", authorization_status="authorized")
    validator.validate(value)
    value["authorization_status"] = "revoked"
    assert not validator.is_valid(value)
    value["connection_status"] = "revoked"
    validator.validate(value)


@pytest.mark.parametrize("mode,connection", [("manual", None), ("fake", None), ("sandbox", ID), ("authorized", ID)])
def test_delivery_connection_depends_on_provider_mode(mode, connection):
    validator, value = record(
        "delivery-attempt", provider_mode=mode, account_connection_id=connection,
        adapter_ref="manual:export",
    )
    validator.validate(value)
    value["account_connection_id"] = ID if connection is None else None
    assert not validator.is_valid(value)
