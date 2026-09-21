from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from modules.geo_content import GeoQueryFixtureService


ROOT = Path(__file__).resolve().parents[2]


def test_geo_query_fixture_schema_is_closed_and_service_output_validates() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/geo-query-fixture.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    service = GeoQueryFixtureService(clock=lambda: datetime(2026, 9, 19, tzinfo=timezone.utc))
    value = service.create_fixture(
        org_id=uuid4(),
        actor_id=uuid4(),
        trace_id="contract",
        idempotency_key="contract-create",
        query="What is Acme?",
        locale="en-US",
        region="US",
        expected_entities=["Acme"],
        expected_claim_ids=[str(uuid4())],
    )
    assert list(validator.iter_errors(value)) == []


def test_geo_content_002_migration_revision_is_chained_to_geo_content_001() -> None:
    namespace = {}
    path = ROOT / "packages/db/migrations/versions/20260919_geo_content_002.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    assert namespace["revision"] == "20260919_geo_content_002"
    assert namespace["down_revision"] == "20260919_geo_content_001"
