from __future__ import annotations

from uuid import uuid4

from modules.distribution import DistributionService, ManualExportVerticalSliceService


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
REGION = "00000000-0000-4000-8000-000000000004"
POLICY = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"


def _slice_inputs(service: DistributionService) -> tuple[dict, dict, dict, dict, dict]:
    target = service.create_target(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target",
                                   platform_id=PLATFORM, market="US", locale="en-US", channel="article", environment="dev",
                                   created_at=STAMP)
    target_version = service.create_target_version(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="target-version",
        distribution_target_id=target["id"], platform_id=PLATFORM, market="US", locale="en-US", channel="article",
        environment="dev", region_profile_version_id=REGION, policy_snapshot_id=POLICY,
        eligible_delivery_modes=["manual_export"], created_at=STAMP,
    )
    canonical_id, variant_id, qa_id, approval_id = str(uuid4()), str(uuid4()), str(uuid4()), str(uuid4())
    canonical = {"id": canonical_id, "org_id": ORG, "status": "approved", "freshness_status": "fresh", "content_hash": "c" * 64}
    variant = {"id": variant_id, "org_id": ORG, "status": "approved", "canonical_content_version_id": canonical_id,
               "snapshot_hash": "v" * 64}
    qa = {"id": qa_id, "org_id": ORG, "subject_id": variant_id, "status": "passed"}
    approval = {"id": approval_id, "org_id": ORG, "status": "approved", "approval_type": "distribution"}
    return target_version, canonical, variant, qa, approval


def test_vertical_slice_gates_predecessors_and_creates_private_export() -> None:
    distribution = DistributionService()
    target_version, canonical, variant, qa, approval = _slice_inputs(distribution)
    service = ManualExportVerticalSliceService(distribution=distribution)
    decision = {"id": str(uuid4()), "org_id": ORG, "final_decision": "allow"}
    result = service.run(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="slice",
        canonical_version=canonical, variant_version=variant, qa_report=qa, approval=approval,
        target_version_id=target_version["id"], policy_decision=decision,
        payload_snapshot={"title": "Slice", "body": {}, "tags": [], "disclosure": None},
        region_profile_version_id=REGION, capability_snapshot_hash="a" * 64, intent_key="slice-intent", created_at=STAMP,
    )
    assert result["stages"]["publication_intent"]["status"] == "exported"
    assert result["stages"]["export_package"]["storage_object_ref"].startswith("private://")
    assert result["side_effect_triggered"] is False
    assert service.run(
        org_id=ORG, actor_id=ACTOR, trace_id="other", idempotency_key="slice",
        canonical_version=canonical, variant_version=variant, qa_report=qa, approval=approval,
        target_version_id=target_version["id"], policy_decision=decision,
        payload_snapshot={"title": "Slice", "body": {}, "tags": [], "disclosure": None},
        region_profile_version_id=REGION, capability_snapshot_hash="a" * 64, intent_key="slice-intent", created_at=STAMP,
    ) == result


def test_vertical_slice_rejects_unapproved_or_cross_tenant_predecessor() -> None:
    distribution = DistributionService()
    target_version, canonical, variant, qa, approval = _slice_inputs(distribution)
    service = ManualExportVerticalSliceService(distribution=distribution)
    from modules.distribution import VerticalSliceError
    approval["status"] = "pending"
    try:
        service.run(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="blocked",
                    canonical_version=canonical, variant_version=variant, qa_report=qa, approval=approval,
                    target_version_id=target_version["id"], policy_decision={"id": str(uuid4()), "org_id": ORG, "final_decision": "allow"},
                    payload_snapshot={"title": "Slice", "body": {}, "tags": [], "disclosure": None},
                    region_profile_version_id=REGION, capability_snapshot_hash="a" * 64, intent_key="blocked", created_at=STAMP)
    except VerticalSliceError as error:
        assert error.code == "APPROVAL_NOT_GRANTED"
    else:  # pragma: no cover
        raise AssertionError("unapproved predecessor must be rejected")
