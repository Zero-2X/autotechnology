import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from packages.testkit import create_synthetic_fixture


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "packages/contracts/jsonschema"


def validator() -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / "synthetic-fixture.schema.json").read_text(encoding="utf-8"))
    storage = json.loads((SCHEMA_DIR / "storage-object.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource(storage["$id"], Resource.from_contents(storage))
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def snapshot() -> dict:
    fixture = create_synthetic_fixture(
        "schema-case", started_at=datetime(2026, 9, 18, 11, 0, tzinfo=timezone.utc)
    )
    fixture.put_object("input.json", b"{}", content_type="application/json")
    return fixture.as_contract()


def test_fixture_snapshot_validates_offline_and_is_in_foundation_union() -> None:
    validator().validate(snapshot())
    foundation = json.loads((SCHEMA_DIR / "foundation.schema.json").read_text(encoding="utf-8"))
    assert {"$ref": "./synthetic-fixture.schema.json"} in foundation["oneOf"]


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(extra=True),
        lambda value: value.update(seed_hash="raw-seed"),
        lambda value: value["context"].update(org_id="other-org"),
        lambda value: value.update(network_access=True),
        lambda value: value["audit_events"][0].update(subject_ref="https://public.example/item"),
        lambda value: value["audit_events"][0].update(sequence=0),
    ],
)
def test_fixture_contract_rejects_unknown_tenant_side_effect_and_audit_variants(change) -> None:
    value = copy.deepcopy(snapshot())
    change(value)
    assert not validator().is_valid(value)
