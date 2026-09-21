from uuid import uuid4

import pytest

from modules.distribution.account import AccountError, InMemoryAccountService


def test_planned_profile_allows_manual_export_only_and_versions_are_monotonic() -> None:
    service = InMemoryAccountService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, platform_id=uuid4(), profile_kind="planned", display_name="Planned")
    target = service.create_target(org_id=org_id, account_profile_id=profile.id, channel="article")
    first = service.create_version(org_id=org_id, target_id=target.id, delivery_mode="manual_export", policy_snapshot_ref="policy/v1", config_json={"x": 1}, created_by=uuid4())
    assert first.version_no == 1
    assert service.create_version(org_id=org_id, target_id=target.id, delivery_mode="manual_export", policy_snapshot_ref="policy/v1", config_json={"x": 2}, created_by=uuid4()).version_no == 2
    with pytest.raises(AccountError) as error:
        service.create_version(org_id=org_id, target_id=target.id, delivery_mode="authorized_api", policy_snapshot_ref="policy/v1", config_json={}, created_by=uuid4())
    assert error.value.code == "ACCOUNT_CONNECTION_REQUIRED"


def test_synthetic_profile_allows_simulation_but_keeps_connection_null() -> None:
    service = InMemoryAccountService()
    org_id = uuid4()
    profile = service.create_profile(org_id=org_id, platform_id=uuid4(), profile_kind="synthetic", display_name="Synthetic")
    target = service.create_target(org_id=org_id, account_profile_id=profile.id, channel="short_post")
    version = service.create_version(org_id=org_id, target_id=target.id, delivery_mode="simulation", policy_snapshot_ref="policy/v1", config_json={"fixture": True}, created_by=uuid4())
    assert version.account_connection_id is None


def test_account_objects_are_tenant_scoped() -> None:
    service = InMemoryAccountService()
    profile = service.create_profile(org_id=uuid4(), platform_id=uuid4(), profile_kind="planned", display_name="P")
    with pytest.raises(AccountError) as error:
        service.create_target(org_id=uuid4(), account_profile_id=profile.id, channel="article")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
