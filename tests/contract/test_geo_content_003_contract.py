from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from modules.geo_content import GeoQueryFixtureService, GeoRunService


ROOT = Path(__file__).resolve().parents[2]


def _fixture_service(org_id):
    clock = lambda: datetime(2026, 9, 20, tzinfo=timezone.utc)
    service = GeoQueryFixtureService(clock=clock)
    fixture = service.create_fixture(
        org_id=org_id,
        idempotency_key="create",
        query="Where is Acme?",
        locale="en-US",
        region="US",
        expected_entities=["Acme"],
        expected_claim_ids=[],
    )
    fixture = service.activate_fixture(
        org_id=org_id,
        fixture_id=fixture["id"],
        idempotency_key="activate",
        expected_version=1,
    )
    return service, fixture, clock


def test_geo_run_schema_is_closed_complete_and_service_output_validates() -> None:
    schema = json.loads(
        (ROOT / "packages/contracts/jsonschema/geo-run.schema.json").read_text(encoding="utf-8")
    )
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    assert schema["x-source"] == "GEO_CONTENT-003"
    assert schema["x-append-only"] is True
    assert schema["properties"]["sample_count"]["minimum"] == 2
    assert schema["properties"]["sample_count"]["maximum"] == 100
    assert schema["properties"]["confidence"]["minimum"] == 0
    assert schema["properties"]["confidence"]["maximum"] == 1

    org_id = uuid4()
    fixtures, fixture, clock = _fixture_service(org_id)
    value = GeoRunService(fixture_service=fixtures, clock=clock).run(
        org_id=org_id,
        idempotency_key="run",
        page_version_id=uuid4(),
        query_fixture_id=fixture["id"],
        locale="en-US",
        region="US",
        sample_count=2,
        answers=[
            {"answer": "Acme", "correctness": "correct"},
            {"status": "unknown"},
        ],
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors(value)) == []
    assert set(value) == set(schema["properties"])
    assert value["data_quality"] == "estimated"
    assert value["fixture_hash"] == fixture["fixture_hash"]


def test_geo_content_003_migration_is_chained_to_geo_content_002() -> None:
    namespace = {}
    path = ROOT / "packages/db/migrations/versions/20260920_geo_content_003.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    assert namespace["revision"] == "20260920_geo_content_003"
    assert namespace["down_revision"] == "20260919_geo_content_002"


def test_fake_geo_implementation_contains_no_network_client_imports() -> None:
    source = (ROOT / "modules/geo_content/runs.py").read_text(encoding="utf-8")
    for forbidden in ("import requests", "import httpx", "urllib.request", "socket."):
        assert forbidden not in source
