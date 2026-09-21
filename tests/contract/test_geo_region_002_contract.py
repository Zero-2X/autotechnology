from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker
import yaml

from modules.geo_region import InMemoryRegionService, RegionDeletionService, RegionEligibilityService


ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _version(service: InMemoryRegionService, org):
    profile = service.create_profile(org_id=org, region_code="US", idempotency_key="contract-profile")
    draft = service.create_draft(
        org_id=org, profile_id=profile.id, expected_current_version_id=None,
        idempotency_key="contract-version", locales=["en-US", "fr-FR"], timezone="UTC",
        date_number_format="YYYY-MM-DD", units="imperial", currency="USD",
        terminology_version="v1", disclosure_rules=[{"id": "ad", "required": True}],
        restricted_topics=[], data_residency="US", retention_days=30,
        deletion_sla_hours=24, platform_eligibility=["web"], policy_snapshot_id=uuid4(),
        valid_from=NOW - timedelta(days=1), valid_to=NOW + timedelta(days=1),
    )
    return service.activate_version(org_id=org, version_id=draft.id, expected_version=1, idempotency_key="contract-activate")


def test_geo_region_002_schemas_are_closed_and_task_refs_exist() -> None:
    for name in ("region-check-decision.schema.json", "region-deletion-policy.schema.json"):
        schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["x-source"] == "GEO_REGION-002"
        assert schema["x-append-only"] is True
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "GEO_REGION-002")
    assert task["status"] == "done"
    assert "packages/contracts/jsonschema/region-check-decision.schema.json" in task["contract_refs"]
    assert "packages/contracts/jsonschema/region-deletion-policy.schema.json" in task["contract_refs"]
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_geo_region_002.py"]


def test_geo_region_002_service_outputs_validate() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _version(service, org)
    page = {
        "id": str(uuid4()), "org_id": str(org), "page_key": "guide", "locale": "en-US",
        "market": "US", "platform": "web", "status": "published",
        "region_profile_version_id": str(version.id), "disclosures": ["ad"],
    }
    decision = RegionEligibilityService(region_service=service, clock=lambda: NOW).check_page(
        page, org_id=org, region_profile_version_id=version.id, evaluated_at=NOW,
        idempotency_key="contract-check",
    ).as_contract()
    check_schema = json.loads((ROOT / "packages/contracts/jsonschema/region-check-decision.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(check_schema, format_checker=FormatChecker()).validate(decision)
    plan = RegionDeletionService(region_service=service, clock=lambda: NOW).plan(
        org_id=org, region_profile_version_id=version.id, subject_type="asset", subject_id=uuid4(),
        anchor_at=NOW, idempotency_key="contract-delete",
    ).as_contract()
    deletion_schema = json.loads((ROOT / "packages/contracts/jsonschema/region-deletion-policy.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(deletion_schema, format_checker=FormatChecker()).validate(plan)
    assert plan["due_at"] == "2026-10-21T12:00:00.000000Z"


def test_geo_region_002_migration_is_reversible_and_append_only() -> None:
    source = (ROOT / "packages/db/migrations/versions/20260920_geo_region_002.py").read_text(encoding="utf-8")
    assert 'revision = "20260920_geo_region_002"' in source
    assert 'down_revision = "20260920_geo_region_001"' in source
    assert "region_policy_decisions" in source
    assert "is append-only" in source
    assert "raw body" in source
    assert "def upgrade()" in source and "def downgrade()" in source
