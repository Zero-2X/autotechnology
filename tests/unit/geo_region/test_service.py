from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from modules.geo_region import InMemoryRegionService, RegionError


def values() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    return {"locales": ["zh-CN", "en-US"], "timezone": "Asia/Shanghai", "date_format": "YYYY-MM-DD", "number_format": "#,##0.00", "units": "metric", "currency": "CNY", "retention_days": 30, "deletion_sla_hours": 24, "policy_snapshot_ref": "policy/v1", "valid_from": now, "valid_to": now + timedelta(days=30)}


def test_version_is_immutable_and_current_pointer_moves_atomically() -> None:
    service = InMemoryRegionService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, region_code="CN")
    first = service.publish_version(org_id=org_id, profile_id=profile.id, expected_current_version_id=None, **values())
    assert first.version_no == 1
    second = service.publish_version(org_id=org_id, profile_id=profile.id, expected_current_version_id=first.id, **values())
    assert second.version_no == 2
    assert service.profiles[profile.id].current_version_id == second.id
    with pytest.raises(RegionError) as error:
        service.publish_version(org_id=org_id, profile_id=profile.id, expected_current_version_id=first.id, **values())
    assert error.value.code == "VERSION_CONFLICT"


def test_invalid_timezone_locale_currency_and_cross_tenant_are_rejected() -> None:
    service = InMemoryRegionService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, region_code="US")
    bad = values() | {"timezone": "Mars/Nope"}
    with pytest.raises(RegionError) as error:
        service.publish_version(org_id=org_id, profile_id=profile.id, expected_current_version_id=None, **bad)
    assert error.value.code == "REGION_PROFILE_INVALID"
    with pytest.raises(RegionError) as error:
        service.publish_version(org_id=uuid4(), profile_id=profile.id, expected_current_version_id=None, **values())
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
