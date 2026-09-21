from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

from scripts.check_event_compatibility import check_compatibility

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "docs/contracts/event-registry.yaml"
BASELINE = ROOT / "docs/foundation/event-compatibility-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/event-compatibility-baseline.schema.json"


def load(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_event_registry_and_schemas_pass_baseline() -> None:
    registry, baseline = load(REGISTRY), load(BASELINE)
    errors, warnings = check_compatibility(registry, baseline)
    assert errors == []
    assert all(item.startswith("new event type: ") for item in warnings)
    assert len(registry["events"]) == baseline["event_count"] + len(warnings)
    assert baseline["event_count"] == 162


def test_breaking_event_changes_are_rejected(tmp_path: Path) -> None:
    registry, baseline = load(REGISTRY), load(BASELINE)
    changed = copy.deepcopy(registry)
    entry = changed["events"][0]
    schema_path = ROOT / entry["schema_ref"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["allOf"][1]["properties"]["event_schema_version"]["const"] = 2
    candidate = tmp_path / "candidate.schema.json"
    candidate.write_text(json.dumps(schema), encoding="utf-8")
    entry["schema_ref"] = str(candidate)
    errors, _ = check_compatibility(changed, baseline)
    assert any("schema version changed" in item for item in errors)


def test_removed_event_and_required_payload_field_are_rejected(tmp_path: Path) -> None:
    registry, baseline = load(REGISTRY), load(BASELINE)
    removed = copy.deepcopy(registry)
    removed["events"] = removed["events"][1:]
    errors, _ = check_compatibility(removed, baseline)
    assert any("removed baseline event" in item for item in errors)

    changed = copy.deepcopy(registry)
    entry = changed["events"][0]
    schema_path = ROOT / entry["schema_ref"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = schema["allOf"][1]["properties"]["payload"]
    payload["required"].append("new_required_field")
    candidate = tmp_path / "candidate.schema.json"
    candidate.write_text(json.dumps(schema), encoding="utf-8")
    entry["schema_ref"] = str(candidate)
    errors, _ = check_compatibility(changed, baseline)
    assert any("new required payload field" in item for item in errors)


def test_baseline_schema_is_machine_readable() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("draft/2020-12/schema")
    assert schema["properties"]["baseline_key"]["const"] == "event-compatibility"
