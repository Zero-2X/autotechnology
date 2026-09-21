import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from infra.foundation.control_plane import DeliveryMode
from scripts.check_migrations import analyze_migrations


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages/contracts/jsonschema"


def validator(name):
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    registry = Registry()
    for path in CONTRACTS.glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def test_delivery_mode_has_one_machine_enum_shared_by_runtime():
    schema = json.loads((CONTRACTS / "delivery-mode.schema.json").read_text(encoding="utf-8"))
    expected = ["manual_export", "simulation", "draft_only", "authorized_api"]
    assert schema["enum"] == expected
    assert [mode.value for mode in DeliveryMode] == expected
    target = json.loads((CONTRACTS / "distribution-target-version.schema.json").read_text(encoding="utf-8"))
    assert target["properties"]["eligible_delivery_modes"]["items"] == {"$ref": "./delivery-mode.schema.json"}


def test_feature_flag_and_global_kill_switch_contracts_are_closed():
    feature = {
        "org_id": "00000000-0000-4000-8000-000000000001", "flag_key": "delivery_mode.simulation",
        "enabled": True, "version": 1, "reason": "synthetic test",
        "changed_by": "00000000-0000-4000-8000-000000000002", "changed_at": "2026-09-18T00:00:00Z",
    }
    validator("feature-flag.schema.json").validate(feature)
    assert not validator("feature-flag.schema.json").is_valid({**feature, "unknown": True})
    kill_switch = {
        "id": "00000000-0000-4000-8000-000000000008", "org_id": None, "scope": "global",
        "scope_id": None, "status": "paused", "version": 1, "reason": "synthetic incident",
        "changed_by": "00000000-0000-4000-8000-000000000002", "changed_at": "2026-09-18T00:00:00Z",
        "blocked_delivery_modes": ["authorized_api", "draft_only"],
    }
    validator("kill-switch.schema.json").validate(kill_switch)
    assert not validator("kill-switch.schema.json").is_valid({**kill_switch, "org_id": feature["org_id"]})
    scoped = {**kill_switch, "scope": "account", "org_id": feature["org_id"], "scope_id": feature["changed_by"]}
    validator("kill-switch.schema.json").validate(scoped)
    assert not validator("kill-switch.schema.json").is_valid({**scoped, "scope_id": None})


def test_found_008_migration_remains_in_the_valid_single_head_chain():
    result = analyze_migrations()
    assert result["errors"] == []
    assert len(result["heads"]) == 1
    migration = (ROOT / "packages/db/migrations/versions/20260918_found_008_control_plane.py").read_text(
        encoding="utf-8"
    )
    assert 'revision = "20260918_found_008"' in migration
