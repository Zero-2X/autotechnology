from __future__ import annotations

import json
from pathlib import Path
import re
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from modules.geo_region import InMemoryRegionService


ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict:
    return json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))


def test_geo_region_schemas_are_closed_and_union_resolves_both_entities() -> None:
    profile_schema = _schema("region-profile.schema.json")
    version_schema = _schema("region-profile-version.schema.json")
    union = _schema("geo_region.schema.json")
    assert profile_schema["additionalProperties"] is False
    assert version_schema["additionalProperties"] is False
    assert version_schema["x-append-only"] is True
    assert {item["$ref"] for item in union["oneOf"]} == {"./region-profile.schema.json", "./region-profile-version.schema.json"}
    service = InMemoryRegionService(clock=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    org_id = uuid4(); profile = service.create_profile(org_id=org_id, region_code="JP")
    registry = Registry().with_resources([
        (profile_schema["$id"], Resource.from_contents(profile_schema)),
        (version_schema["$id"], Resource.from_contents(version_schema)),
    ])
    validator = Draft202012Validator(union, registry=registry, format_checker=FormatChecker())
    validator.validate(profile.as_contract())


def test_geo_region_migration_declares_tables_constraints_triggers_and_reversible_downgrade() -> None:
    migration = (ROOT / "packages/db/migrations/versions/20260920_geo_region_001.py").read_text(encoding="utf-8")
    assert "revision = \"20260920_geo_region_001\"" in migration
    assert "region_profiles" in migration and "region_profile_versions" in migration
    for marker in ("PROFILE_CURRENT_FK", "VERSION_PROFILE_FK", "SITE_VERSION_REGION_FK", "_sqlite_triggers", "_postgres_triggers"):
        assert marker in migration
    for marker in ("is immutable", "is append-only", "no_replace", "status", "current_version_id"):
        assert marker in migration
    assert re.search(r"def upgrade\(\).*?def downgrade\(\)", migration, re.DOTALL)


def test_region_event_contracts_are_registered_and_have_expected_discriminators() -> None:
    expected = {
        "region-profile-created.schema.json": "region.profile.created",
        "region-profile_version-created.schema.json": "region.profile_version.created",
        "region-profile_version-activated.schema.json": "region.profile_version.activated",
        "region-profile_version-retired.schema.json": "region.profile_version.retired",
    }
    for filename, event_type in expected.items():
        path = ROOT / "packages/contracts/events" / filename
        assert path.exists(), filename
        schema = json.loads(path.read_text(encoding="utf-8"))
        event_properties = schema["allOf"][1]["properties"]
        assert event_properties["event_type"]["const"] == event_type
        assert schema["x-replay-policy"] == "idempotent_projection_replay"
