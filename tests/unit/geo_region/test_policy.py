from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.geo_region import (
    InMemoryRegionService,
    RegionDeletionService,
    RegionEligibilityService,
    RegionPolicyError,
)


# ``tests/unit/geo_region`` is three levels below the repository root.
ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _region(*, service: InMemoryRegionService, org_id, **overrides):
    profile = service.create_profile(org_id=org_id, region_code=overrides.pop("region_code", "US"), idempotency_key="profile-policy")
    values = {
        "locales": ["en-US", "fr-FR", "de-DE"],
        "timezone": "UTC",
        "date_number_format": "YYYY-MM-DD",
        "units": "imperial",
        "currency": "USD",
        "terminology_version": "terms-v1",
        "disclosure_rules": [{"id": "ad-disclosure", "required": True}],
        "restricted_topics": [{"topic": "gambling", "markets": ["US"]}],
        "data_residency": "US",
        "retention_days": 30,
        "deletion_sla_hours": 24,
        "platform_eligibility": ["web"],
        "policy_snapshot_id": uuid4(),
        "valid_from": NOW - timedelta(days=1),
        "valid_to": NOW + timedelta(days=1),
    }
    values.update(overrides)
    draft = service.create_draft(
        org_id=org_id, profile_id=profile.id, expected_current_version_id=None,
        idempotency_key="version-policy", **values,
    )
    return service.activate_version(
        org_id=org_id, version_id=draft.id, expected_version=draft.version_no,
        idempotency_key="activate-policy",
    )


def _page(org_id, version_id, **overrides):
    value = {
        "id": str(uuid4()), "org_id": str(org_id), "page_key": "guides/one",
        "locale": "en-US", "market": "US", "platform": "web", "status": "published",
        "region_profile_version_id": str(version_id), "disclosures": ["ad-disclosure"],
        "topics": ["science"], "canonical_url": "https://example.com/guides/one",
    }
    value.update(overrides)
    return value


def test_page_check_uses_exact_version_and_is_schema_valid() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org)
    checker = RegionEligibilityService(region_service=service, clock=lambda: NOW)
    result = checker.check_page(
        _page(org, version.id), org_id=org, region_profile_version_id=version.id,
        evaluated_at=NOW, idempotency_key="check-policy",
    )
    value = result.as_contract()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/region-check-decision.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    assert value["decision"] == "eligible"
    assert value["status"] == "eligible"
    assert value["input_snapshot_hash"] == value["request_hash"]
    assert all("answer" not in json.dumps(item).lower() for item in value["checks"])


def test_page_check_denies_restriction_and_missing_disclosure() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org)
    checker = RegionEligibilityService(region_service=service, clock=lambda: NOW)
    result = checker.check_page(
        _page(org, version.id, topics=["gambling"], disclosures=[]), org_id=org,
        region_profile_version_id=version.id, evaluated_at=NOW, idempotency_key="blocked-policy",
    )
    assert result["decision"] == "deny"
    assert {item["code"] for item in result["reasons"]} >= {"REGION_CONTENT_BLOCKED", "DISCLOSURE_REQUIRED"}


def test_page_check_tenant_and_version_guards() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org, other = uuid4(), uuid4(); version = _region(service=service, org_id=org)
    checker = RegionEligibilityService(region_service=service, clock=lambda: NOW)
    with pytest.raises(RegionPolicyError) as error:
        checker.check_page(_page(other, version.id), org_id=org, region_profile_version_id=version.id, idempotency_key="foreign-page")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(RegionPolicyError) as error:
        checker.check_page(_page(org, version.id), org_id=org, region_profile_version_id=uuid4(), idempotency_key="missing-version")
    assert error.value.code == "REGION_VERSION_NOT_FOUND"


def test_hreflang_filters_blocked_rows_deduplicates_and_picks_sorted_default() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org)
    checker = RegionEligibilityService(region_service=service, clock=lambda: NOW)
    rows = [
        _page(org, version.id, locale="fr-fr", canonical_url="https://example.com/fr/one", disclosures=["ad-disclosure"]),
        _page(org, version.id, locale="en-us", canonical_url="https://example.com/one", disclosures=["ad-disclosure"]),
        _page(org, version.id, locale="fr-FR", canonical_url="https://example.com/fr/other", disclosures=["ad-disclosure"]),
        _page(org, version.id, locale="de-DE", canonical_url="https://example.com/de/one", disclosures=["ad-disclosure"]),
        _page(org, version.id, locale="es-ES", canonical_url="https://example.com/es/one", topics=["gambling"], disclosures=[]),
    ]
    links = checker.filter_hreflang(rows, org_id=org, page_key="guides/one", default_locale="es-ES")
    assert [item["locale"] for item in links] == ["de-DE", "en-US", "fr-FR", "x-default"]
    assert links[-1]["url"] == "https://example.com/de/one"


def test_deletion_plan_is_deterministic_and_legal_hold_is_manual() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org, retention_days=7, deletion_sla_hours=12)
    planner = RegionDeletionService(region_service=service, clock=lambda: NOW)
    subject = uuid4()
    first = planner.plan(
        org_id=org, region_profile_version_id=version.id, subject_type="asset", subject_id=subject,
        anchor_at=NOW, idempotency_key="delete-policy",
    )
    replay = planner.plan(
        org_id=org, region_profile_version_id=version.id, subject_type="asset", subject_id=subject,
        anchor_at=NOW, idempotency_key="delete-policy",
    )
    assert replay.as_contract() == first.as_contract()
    assert first["status"] == "planned"
    assert first["deletion_action"] == "delete"
    assert first["due_at"] == "2026-09-28T00:00:00.000000Z"
    hold = planner.plan(
        org_id=org, region_profile_version_id=version.id, subject_type="asset", subject_id=uuid4(),
        anchor_at=NOW, legal_hold=True, idempotency_key="hold-policy",
    )
    assert hold["status"] == "manual_review" and hold["request_id"] is None


def test_deletion_plan_rejects_idempotency_payload_reuse() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org)
    planner = RegionDeletionService(region_service=service, clock=lambda: NOW)
    planner.plan(org_id=org, region_profile_version_id=version.id, subject_type="asset", subject_id=uuid4(), anchor_at=NOW, idempotency_key="same-delete")
    with pytest.raises(RegionPolicyError) as error:
        planner.plan(org_id=org, region_profile_version_id=version.id, subject_type="asset", subject_id=uuid4(), anchor_at=NOW, idempotency_key="same-delete")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize("missing", ["retention_days", "deletion_sla_hours", "data_residency"])
def test_deletion_plan_missing_policy_enters_manual_review(missing: str) -> None:
    """A legacy/incomplete immutable snapshot never becomes an auto-delete."""
    org = uuid4()
    version_id = uuid4()
    version = {
        "id": str(version_id),
        "org_id": str(org),
        "region_profile_id": str(uuid4()),
        "version_no": 1,
        "region_code": "US",
        "status": "active",
        "locales": ["en-US"],
        "retention_days": 30,
        "deletion_sla_hours": 24,
        "data_residency": "US",
    }
    version.pop(missing)
    planner = RegionDeletionService(clock=lambda: NOW)
    plan = planner.plan(
        org_id=org,
        region_profile_version_id=version_id,
        region_version=version,
        subject_type="asset",
        subject_id=uuid4(),
        anchor_at=NOW,
        idempotency_key=f"missing-{missing}",
    )
    assert plan["status"] == "manual_review"
    assert plan["request_id"] is None
    assert plan["deletion_action"] == "manual_review"


def test_deletion_queue_error_is_redacted_and_manual_review() -> None:
    class FailingQueue:
        def request(self, **_: object) -> None:
            raise RuntimeError("provider token=super-secret authorization=Bearer-abc")

    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org)
    planner = RegionDeletionService(region_service=service, propagation_service=FailingQueue(), clock=lambda: NOW)
    plan = planner.plan(
        org_id=org,
        region_profile_version_id=version.id,
        subject_type="asset",
        subject_id=uuid4(),
        anchor_at=NOW,
        idempotency_key="queue-redact",
    )
    assert plan["status"] == "manual_review"
    assert plan["request_id"] is None
    assert "super-secret" not in json.dumps(planner.audit)
    assert "Bearer-abc" not in json.dumps(planner.audit)


def test_default_region_is_still_subject_to_page_blocklist() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org)
    checker = RegionEligibilityService(region_service=service, clock=lambda: NOW)
    result = checker.check_page(
        _page(org, version.id, market=None, blocked_regions=["US"]),
        org_id=org,
        region_profile_version_id=version.id,
        evaluated_at=NOW,
        idempotency_key="blocked-default-region",
    )
    assert result["decision"] == "deny"
    assert "REGION_CONTENT_BLOCKED" in {item["code"] for item in result["reasons"]}


def test_valid_to_is_exclusive_and_false_text_does_not_request_review() -> None:
    org = uuid4(); version_id = uuid4()
    version = {
        "id": str(version_id), "org_id": str(org), "region_profile_id": str(uuid4()),
        "version_no": 1, "region_code": "US", "status": "active", "locales": ["en-US"],
        "valid_from": (NOW - timedelta(days=1)).isoformat(), "valid_to": NOW.isoformat(),
        "data_residency": "US", "retention_days": 30, "deletion_sla_hours": 24,
        "platform_eligibility": ["web"], "disclosure_rules": [], "restricted_topics": [],
    }
    checker = RegionEligibilityService(clock=lambda: NOW)
    expired = checker.check_page(
        _page(org, version_id, disclosures=[]), org_id=org, region_profile_version_id=version_id,
        region_version=version, evaluated_at=NOW, idempotency_key="exclusive-valid-to",
    )
    assert expired["decision"] == "deny"
    assert "REGION_VERSION_EXPIRED" in {item["code"] for item in expired["reasons"]}

    version["valid_to"] = (NOW + timedelta(days=1)).isoformat()
    eligible = checker.check_page(
        _page(org, version_id, disclosures=[], manual_review="false"), org_id=org,
        region_profile_version_id=version_id, region_version=version, evaluated_at=NOW,
        idempotency_key="false-text-review",
    )
    assert eligible["decision"] == "eligible"


def test_deletion_policy_cannot_be_overridden_and_safe_noop_actions_do_not_queue() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org = uuid4(); version = _region(service=service, org_id=org, retention_days=7, deletion_sla_hours=12)
    planner = RegionDeletionService(region_service=service, clock=lambda: NOW)
    common = {
        "org_id": org, "region_profile_version_id": version.id,
        "subject_type": "asset", "anchor_at": NOW,
    }
    with pytest.raises(RegionPolicyError) as retention_error:
        planner.plan(**common, subject_id=uuid4(), retention_days=8, idempotency_key="override-retention")
    assert retention_error.value.code == "REGION_POLICY_INVALID"
    with pytest.raises(RegionPolicyError) as residency_error:
        planner.plan(**common, subject_id=uuid4(), data_residency="EU", idempotency_key="override-residency")
    assert residency_error.value.code == "REGION_CONTENT_BLOCKED"

    retained = planner.plan(
        **common, subject_id=uuid4(), requested_deletion=False, idempotency_key="retain-policy",
    )
    assert retained["status"] == "completed"
    assert retained["deletion_action"] == "retain"
    assert retained["request_id"] is None
    deleted = planner.plan(
        **common, subject_id=uuid4(), already_deleted=True, legal_hold=True,
        idempotency_key="already-deleted-policy",
    )
    assert deleted["status"] == "completed"
    assert deleted["deletion_action"] == "already_deleted"
