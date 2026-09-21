from __future__ import annotations

from uuid import uuid4

import pytest

from modules.distribution import DistributionError, DistributionService


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
REGION = "00000000-0000-4000-8000-000000000004"
POLICY = "00000000-0000-4000-8000-000000000005"
DECISION = "00000000-0000-4000-8000-000000000006"
STAMP = "2026-09-19T00:00:00Z"


def _service() -> tuple[DistributionService, dict, dict]:
    service = DistributionService()
    target = service.create_target(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target",
        platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev",
        created_at=STAMP,
    )
    version = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target-version",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US",
        channel="article", environment="dev", region_profile_version_id=REGION,
        synthetic_target_id="fake-official", capability_snapshot={},
        policy_snapshot_id=POLICY, eligible_delivery_modes=["manual_export", "simulation"], created_at=STAMP,
    )
    return service, target, version


def _intent(service: DistributionService, version: dict, *, mode: str = "manual_export", approval_id: str | None = None) -> dict:
    return service.create_publication_intent(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key=f"intent-{mode}",
        variant_version_id=str(uuid4()), asset_version_ids=[], target_version_id=version["id"],
        delivery_mode=mode, region_profile_version_id=REGION,
        payload_snapshot={"title": "Synthetic article", "body": {}, "tags": ["demo"], "disclosure": None},
        capability_snapshot_hash="a" * 64, intent_key=f"intent-key-{mode}", policy_snapshot_id=POLICY,
        approval_id=approval_id, created_at=STAMP,
    )


def _decision() -> dict:
    return {"id": DECISION, "org_id": ORG, "final_decision": "allow"}


def test_manual_export_creates_private_package_and_replays() -> None:
    service, target, version = _service()
    assert service.create_target(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="target",
                                 platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev",
                                 created_at=STAMP) == target
    intent = _intent(service, version)
    first = service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="execute",
                            intent_id=intent["id"], policy_decision=_decision(), executed_at=STAMP)
    replay = service.execute(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="execute",
                             intent_id=intent["id"], policy_decision=_decision(), executed_at=STAMP)
    assert first == replay
    assert first["intent"]["status"] == "exported"
    assert first["export_package"]["storage_object_ref"].startswith("private://")
    assert first["publication_record"] is None
    assert first["attempt"]["provider_mode"] == "manual"


def test_simulation_uses_fake_publisher_and_records_simulated_event() -> None:
    service, _, version = _service()
    intent = _intent(service, version, mode="simulation")
    result = service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="simulate",
                             intent_id=intent["id"], policy_decision=_decision(), executed_at=STAMP)
    assert result["intent"]["status"] == "simulated"
    assert result["publication_record"]["provider_mode"] == "fake"
    assert result["publication_record"]["result_snapshot"]["simulated"] is True
    assert service.events[-1]["event_type"] == "publication.simulated"


def test_policy_and_approval_block_without_side_effects() -> None:
    service, _, version = _service()
    intent = _intent(service, version, approval_id=str(uuid4()))
    with pytest.raises(DistributionError) as error:
        service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="blocked",
                        intent_id=intent["id"], policy_decision={**_decision(), "final_decision": "manual_review"}, executed_at=STAMP)
    assert error.value.code == "PUBLICATION_BLOCKED"
    assert service.attempts == {}
    with pytest.raises(DistributionError) as error:
        service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="blocked-approval",
                        intent_id=intent["id"], policy_decision=_decision(), approval=None, executed_at=STAMP)
    assert error.value.code == "PUBLICATION_BLOCKED"
    assert service.attempts == {}


def test_connected_modes_queue_without_external_side_effect_and_cross_tenant_are_rejected() -> None:
    service = DistributionService()
    target = service.create_target(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target",
                                   platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev", created_at=STAMP)
    connected = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="connected-version",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev",
        region_profile_version_id=REGION, account_profile_id=str(uuid4()), account_connection_id=str(uuid4()),
        eligible_delivery_modes=["authorized_api"], created_at=STAMP,
    )
    intent = _intent(service, connected, mode="authorized_api")
    queued = service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="auth",
                             intent_id=intent["id"], policy_decision=_decision(), executed_at=STAMP)
    assert queued["intent"]["status"] == "queued"
    assert queued["attempt"]["status"] == "created"
    assert queued["attempt"]["provider_mode"] == "sandbox"
    assert queued["publication_record"] is None
    assert queued["queue"]["side_effect_triggered"] is False
    assert service.events[-1]["event_type"] == "publication.queued"
    with pytest.raises(DistributionError) as error:
        service.create_target_version(
            org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="missing-connection",
            distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev",
            region_profile_version_id=REGION, eligible_delivery_modes=["authorized_api"], created_at=STAMP,
        )
    assert error.value.code == "ACCOUNT_CONNECTION_REQUIRED"
    with pytest.raises(DistributionError) as error:
        service.view_intent(org_id=str(uuid4()), intent_id=intent["id"])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_draft_only_is_a_connected_queue_mode_and_modes_are_unique() -> None:
    service = DistributionService()
    target = service.create_target(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target-draft",
                                   platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="staging",
                                   created_at=STAMP)
    connection = str(uuid4())
    version = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="draft-version",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
        environment="staging", region_profile_version_id=REGION, account_profile_id=str(uuid4()),
        account_connection_id=connection, eligible_delivery_modes=["draft_only"], created_at=STAMP,
    )
    intent = _intent(service, version, mode="draft_only")
    result = service.execute(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="draft-execute",
                             intent_id=intent["id"], policy_decision=_decision(), executed_at=STAMP)
    assert result["intent"]["status"] == "queued"
    assert result["attempt"]["provider_mode"] == "sandbox"
    assert result["attempt"]["account_connection_id"] == connection
    assert result["attempt"]["adapter_ref"] == "platform:official@v1"
    assert result["queue"]["delivery_mode"] == "draft_only"

    with pytest.raises(DistributionError) as error:
        service.create_target_version(
            org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="duplicate-modes",
            distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
            environment="staging", region_profile_version_id=REGION, synthetic_target_id="fake",
            policy_snapshot_id=POLICY, eligible_delivery_modes=["simulation", "simulation"], created_at=STAMP,
        )
    assert error.value.code == "INVALID_DISTRIBUTION_INPUT"
