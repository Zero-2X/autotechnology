from __future__ import annotations

from hashlib import sha256
import json

from modules.distribution import FakeDeliveryWorkflowService, FakeOfficialAdapter


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
POLICY = "00000000-0000-4000-8000-000000000004"
DECISION = "00000000-0000-4000-8000-000000000005"
INTENT = "00000000-0000-4000-8000-000000000006"
VARIANT = "00000000-0000-4000-8000-000000000007"
TARGET = "00000000-0000-4000-8000-000000000008"
REGION = "00000000-0000-4000-8000-000000000009"
STAMP = "2026-09-19T00:00:00Z"


def _intent() -> dict:
    payload = {"title": "DIST-010 fake publication", "body": {}, "tags": ["fake"], "disclosure": None}
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "id": INTENT, "org_id": ORG, "variant_version_id": VARIANT, "asset_version_ids": [],
        "distribution_target_version_id": TARGET, "delivery_mode": "simulation",
        "region_profile_version_id": REGION, "payload_snapshot": payload,
        "payload_snapshot_hash": digest, "scheduled_at": None, "policy_snapshot_id": POLICY,
        "capability_snapshot_hash": "b" * 64, "intent_key": "dist-010-intent",
        "derived_from_intent_id": None, "status": "planned", "created_by": ACTOR,
        "created_at": STAMP, "updated_at": STAMP, "resolved_at": None,
    }


def _workflow() -> FakeDeliveryWorkflowService:
    return FakeDeliveryWorkflowService(adapter=FakeOfficialAdapter(platform_id=PLATFORM))


def test_fake_workflow_publishes_and_consumes_the_same_event_once() -> None:
    result = _workflow().publish(
        org_id=ORG, actor_id=ACTOR, trace_id="trace-success", idempotency_key="dist-010-success",
        publication_intent=_intent(), policy_snapshot_id=POLICY,
        execution_policy_decision_id=DECISION, now=STAMP,
    )

    assert result["status"] == "succeeded"
    assert result["delivery_attempt"]["provider_mode"] == "fake"
    assert result["publication_record"]["status"] == "published"
    assert result["publication_record"]["result_snapshot"]["simulated"] is True
    assert result["event_consumption"]["first"] == result["event_consumption"]["replay"]
    assert result["event_consumption"]["handler_calls"] == 1


def test_fake_workflow_exhaustion_creates_dead_letter_and_replay_plan() -> None:
    workflow = _workflow()
    workflow.adapter.fail_next(org_id=ORG, error_code="PLATFORM_RATE_LIMITED")
    pending = workflow.publish(
        org_id=ORG, actor_id=ACTOR, trace_id="trace-failure", idempotency_key="dist-010-failure",
        publication_intent=_intent(), policy_snapshot_id=POLICY,
        execution_policy_decision_id=DECISION, max_attempts=2, attempt_no=1, now=STAMP,
    )
    assert pending["status"] == "retry_pending"
    assert pending["classification"]["retryable"] is True

    workflow.adapter.fail_next(org_id=ORG, error_code="PLATFORM_UNAVAILABLE")
    dead = workflow.publish(
        org_id=ORG, actor_id=ACTOR, trace_id="trace-failure", idempotency_key="dist-010-failure",
        publication_intent=_intent(), policy_snapshot_id=POLICY,
        execution_policy_decision_id=DECISION, max_attempts=2, attempt_no=2, now=STAMP,
    )
    assert dead["status"] == "dead_letter"
    assert dead["delivery_attempt"]["status"] == "dead_letter"
    assert dead["human_task"]["task_type"] == "support_escalation"

    replay = workflow.replay(
        org_id=ORG, actor_id=ACTOR, trace_id="trace-replay",
        delivery_attempt=dead["delivery_attempt"], manual_confirmation=True, requested_at=STAMP,
    )
    assert replay["side_effect_triggered"] is False
    assert replay["requires_manual_trigger"] is True
    assert replay["delivery_attempt"]["provider_idempotency_key"] == dead["delivery_attempt"]["provider_idempotency_key"]
