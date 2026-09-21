from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.geo_region import InMemoryRegionService, RegionError


NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "locales": ["zh-cn", "en-us"], "timezone": "Asia/Shanghai",
        "date_number_format": "YYYY-MM-DD | #,##0.00", "units": "metric", "currency": "CNY",
        "terminology_version": "terms-v1", "disclosure_rules": ["disclose-sponsorship"],
        "restricted_topics": [{"name": "regulated-products"}], "data_residency": "CN",
        "retention_days": 30, "deletion_sla_hours": 24, "platform_eligibility": ["web", "mobile"],
        "policy_snapshot_id": uuid4(), "valid_from": NOW, "valid_to": NOW + timedelta(days=30),
        "review_due_at": NOW + timedelta(days=14),
    }
    value.update(overrides)
    return value


def draft(service: InMemoryRegionService, org_id, profile_id, **overrides):
    return service.create_draft(
        org_id=org_id, profile_id=profile_id,
        idempotency_key=overrides.pop("idempotency_key", "draft-1"),
        expected_current_version_id=overrides.pop("expected_current_version_id", None),
        **payload(**overrides),
    )


def test_profile_identity_is_deterministic_and_idempotent_across_request_metadata() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org_id, actor = uuid4(), uuid4()
    first = service.create_profile(org_id=org_id, region_code="cn", idempotency_key="profile-1", actor_id=actor, trace_id="trace-a")
    replay = service.create_profile(org_id=org_id, region_code="CN", idempotency_key="profile-1", actor_id=uuid4(), trace_id="trace-b")
    assert replay == first and first.region_code == "CN"
    assert len(service.events) == 1 and service.audit[-1]["trace_id"] == "trace-a"
    with pytest.raises(RegionError) as error:
        service.create_profile(org_id=org_id, region_code="US", idempotency_key="profile-1")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_draft_normalizes_contract_fields_and_hash_excludes_runtime_metadata() -> None:
    service = InMemoryRegionService(clock=lambda: NOW)
    org_id = uuid4(); profile = service.create_profile(org_id=org_id, region_code="CN")
    version = draft(service, org_id, profile.id)
    assert version.locales == ("zh-CN", "en-US") and len(version.snapshot_hash) == 64
    activated = service.activate_version(org_id=org_id, version_id=version.id, expected_version=1, idempotency_key="activate-1", actor_id=uuid4(), trace_id="another-trace")
    assert activated.snapshot_hash == version.snapshot_hash
    projection = activated.as_compatibility_projection()
    assert projection["profile_id"] == str(profile.id) and projection["content_hash"] == activated.snapshot_hash


@pytest.mark.parametrize("field,value", [
    ("locales", ["en-US", "en-us"]), ("timezone", "Mars/Nope"), ("currency", "usd"),
    ("units", "standard"), ("retention_days", True), ("retention_days", -1),
    ("disclosure_rules", [{"not_a_name": True}]), ("platform_eligibility", ["web", "web"]),
    ("valid_to", NOW - timedelta(seconds=1)), ("review_due_at", NOW - timedelta(seconds=1)),
])
def test_invalid_configuration_is_rejected_before_storage(field: str, value: object) -> None:
    service = InMemoryRegionService(clock=lambda: NOW); org_id = uuid4()
    profile = service.create_profile(org_id=org_id, region_code="CN")
    with pytest.raises(RegionError) as error:
        draft(service, org_id, profile.id, **{field: value})
    assert error.value.code == "REGION_PROFILE_INVALID" and not service.versions


def test_activation_requires_policy_and_validity_and_if_match() -> None:
    service = InMemoryRegionService(clock=lambda: NOW); org_id = uuid4()
    profile = service.create_profile(org_id=org_id, region_code="CN")
    version = draft(service, org_id, profile.id, policy_snapshot_id=None, valid_from=None, valid_to=None, deletion_sla_hours=0)
    with pytest.raises(RegionError) as error:
        service.activate_version(org_id=org_id, version_id=version.id, idempotency_key="a", expected_version=1)
    assert error.value.code == "ACTIVATION_REQUIREMENTS_MISSING"
    with pytest.raises(RegionError) as error:
        service.activate_version(org_id=org_id, version_id=version.id, idempotency_key="a2", expected_version=1, if_match=2)
    assert error.value.code == "VERSION_CONFLICT"


def test_activation_retires_previous_version_and_retirement_clears_pointer() -> None:
    service = InMemoryRegionService(clock=lambda: NOW); org_id = uuid4()
    profile = service.create_profile(org_id=org_id, region_code="CN")
    first = draft(service, org_id, profile.id)
    active_first = service.activate_version(org_id=org_id, version_id=first.id, expected_version=1, idempotency_key="activate-1")
    second = draft(service, org_id, profile.id, idempotency_key="draft-2", expected_current_version_id=active_first.id)
    active_second = service.activate_version(org_id=org_id, version_id=second.id, expected_version=2, idempotency_key="activate-2")
    assert service.get_version(org_id=org_id, version_id=first.id).status == "retired"
    assert service.get_profile(org_id=org_id, profile_id=profile.id).current_version_id == active_second.id
    retired = service.retire_version(org_id=org_id, version_id=active_second.id, expected_version=2, idempotency_key="retire-2", reason="market closed")
    assert retired.status == "retired" and service.get_profile(org_id=org_id, profile_id=profile.id).current_version_id is None
    assert [item.version_no for item in service.list_versions(org_id=org_id, profile_id=profile.id)] == [1, 2]
    profile_retired = service.retire_profile(org_id=org_id, profile_id=profile.id, idempotency_key="retire-profile", reason="region removed")
    assert profile_retired.status == "retired"


def test_tenant_scope_and_predecessor_guards_fail_closed_and_audit_rejections() -> None:
    service = InMemoryRegionService(clock=lambda: NOW); org_id, other_org = uuid4(), uuid4()
    profile = service.create_profile(org_id=org_id, region_code="CN")
    with pytest.raises(RegionError) as error:
        service.get_profile(org_id=other_org, profile_id=profile.id)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(RegionError) as error:
        service.create_profile(org_id=org_id, region_code="US", idempotency_key="bad-predecessor", predecessor_artifacts={"source": {"status": "pending", "org_id": str(org_id)}})
    assert error.value.code == "PREDECESSOR_NOT_READY"
    with pytest.raises(RegionError) as error:
        service.create_profile(org_id=org_id, region_code="US", idempotency_key="bad-tenant", predecessor_artifacts={"source": {"status": "ready", "org_id": str(other_org)}})
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    assert all(item["status"] == "rejected" for item in service.audit[-2:])


def test_namespace_keys_are_independent_but_stale_pointer_is_rejected() -> None:
    service = InMemoryRegionService(clock=lambda: NOW); org_id = uuid4()
    profile = service.create_profile(org_id=org_id, region_code="CN", idempotency_key="same-key")
    version = draft(service, org_id, profile.id, idempotency_key="same-key")
    service.activate_version(org_id=org_id, version_id=version.id, expected_version=1, idempotency_key="same-key")
    with pytest.raises(RegionError) as error:
        service.create_draft(org_id=org_id, profile_id=profile.id, idempotency_key="stale", expected_current_version_id=None, **payload())
    assert error.value.code == "VERSION_CONFLICT"
