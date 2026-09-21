from __future__ import annotations

import pytest

from modules.distribution import DistributionError, DistributionService


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
REGION = "00000000-0000-4000-8000-000000000004"
POLICY = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"


def _service() -> tuple[DistributionService, dict, dict]:
    service = DistributionService()
    target = service.create_target(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target",
        platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev", created_at=STAMP,
    )
    version = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="version-1",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
        environment="dev", region_profile_version_id=REGION, policy_snapshot_id=POLICY,
        synthetic_target_id="fake", eligible_delivery_modes=["manual_export", "simulation"], created_at=STAMP,
    )
    return service, target, version


def test_target_snapshot_fields_are_immutable_and_reads_are_copies() -> None:
    service, target, version = _service()
    read = service.view_target_version(org_id=ORG, target_version_id=version["id"])
    read["market"] = "DE"
    assert service.view_target_version(org_id=ORG, target_version_id=version["id"])["market"] == "US"
    with pytest.raises(DistributionError, match="immutable"):
        service.update_target(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="update",
                              target_id=target["id"], market="DE")
    with pytest.raises(DistributionError) as error:
        service.create_target_version(
            org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="mismatch",
            distribution_target_id=target["id"], platform_id=PLATFORM, market="DE", locale="en-US", channel="article",
            environment="dev", region_profile_version_id=REGION, policy_snapshot_id=POLICY,
            synthetic_target_id="fake", eligible_delivery_modes=["simulation"], created_at=STAMP,
        )
    assert error.value.code == "TARGET_SNAPSHOT_MISMATCH"


def test_target_version_activation_and_replacement_retirement_preserve_snapshot_hash() -> None:
    service, target, first = _service()
    active = service.activate_target_version(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="activate",
                                             target_version_id=first["id"], expected_etag=first["etag"], activated_at=STAMP)
    assert active["status"] == "active"
    with pytest.raises(DistributionError, match="etag"):
        service.activate_target_version(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="activate-bad",
                                        target_version_id=first["id"], expected_etag=first["etag"], activated_at=STAMP)
    replacement = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="version-2",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
        environment="dev", region_profile_version_id=REGION, policy_snapshot_id=POLICY,
        synthetic_target_id="fake", eligible_delivery_modes=["simulation"], created_at="2026-09-19T00:01:00Z",
    )
    retired = service.retire_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="retire-version",
        target_version_id=active["id"], expected_etag=active["etag"], replacement_version_id=replacement["id"],
        retired_at=STAMP, reason="new capability snapshot",
    )
    assert retired["status"] == "retired"
    assert retired["snapshot_hash"] == first["snapshot_hash"]
    assert service.events[-1]["event_type"] == "distribution.target_version.retired"


def test_target_retirement_blocks_new_versions_and_is_tenant_scoped() -> None:
    service, target, _version = _service()
    with pytest.raises(DistributionError, match="does not belong"):
        service.view_target(org_id=OTHER_ORG, target_id=target["id"])
    retired = service.retire_target(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="retire-target",
                                    target_id=target["id"], reason="account retired", expected_status="planned", retired_at=STAMP)
    assert retired["status"] == "retired"
    with pytest.raises(DistributionError, match="retired target"):
        service.create_target_version(
            org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="after-retire",
            distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
            environment="dev", region_profile_version_id=REGION, policy_snapshot_id=POLICY,
            synthetic_target_id="fake", eligible_delivery_modes=["simulation"], created_at=STAMP,
        )
