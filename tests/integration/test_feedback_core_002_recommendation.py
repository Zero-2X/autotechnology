from __future__ import annotations

from hashlib import sha256
import json

from modules.distribution import FakeDeliveryWorkflowService, FakeOfficialAdapter
from modules.feedback.core import FeedbackRecommendationService


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
POLICY = "00000000-0000-4000-8000-000000000004"
DECISION = "00000000-0000-4000-8000-000000000005"
INTENT = "00000000-0000-4000-8000-000000000006"
VARIANT = "00000000-0000-4000-8000-000000000007"
TARGET = "00000000-0000-4000-8000-000000000008"
REGION = "00000000-0000-4000-8000-000000000009"
METRIC = "00000000-0000-4000-8000-000000000010"
SCORING = "00000000-0000-4000-8000-000000000011"
STAMP = "2026-09-19T00:00:00Z"


def test_fake_publication_observation_proposes_reprioritize_without_mutating_delivery() -> None:
    payload = {"title": "Feedback fixture", "body": {}, "tags": ["fake"], "disclosure": None}
    intent = {
        "id": INTENT, "org_id": ORG, "variant_version_id": VARIANT, "asset_version_ids": [],
        "distribution_target_version_id": TARGET, "delivery_mode": "simulation",
        "region_profile_version_id": REGION, "payload_snapshot": payload,
        "payload_snapshot_hash": sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "scheduled_at": None, "policy_snapshot_id": POLICY, "capability_snapshot_hash": "b" * 64,
        "intent_key": "feedback-fixture", "derived_from_intent_id": None, "status": "planned",
        "created_by": ACTOR, "created_at": STAMP, "updated_at": STAMP, "resolved_at": None,
    }
    workflow = FakeDeliveryWorkflowService(adapter=FakeOfficialAdapter(platform_id=PLATFORM))
    published = workflow.publish(
        org_id=ORG, actor_id=ACTOR, trace_id="publish", idempotency_key="fake-publish",
        publication_intent=intent, policy_snapshot_id=POLICY,
        execution_policy_decision_id=DECISION, now=STAMP,
    )
    publication_before = dict(published["publication_record"])
    feedback = FeedbackRecommendationService()
    result = feedback.record_and_recommend(
        org_id=ORG, actor_id=ACTOR, trace_id="feedback", idempotency_key="fake-observation",
        observation={
            "id": "00000000-0000-4000-8000-000000000012", "org_id": ORG, "source": "fake",
            "subject_type": "publication", "subject_id": publication_before["id"],
            "metric_definition_id": METRIC, "metric_definition_version_no": 1,
            "metric_name": "opportunity_score", "metric_type": "number", "metric_value": 0.9,
            "observed_at": STAMP, "locale": "en-US", "region": "US", "data_quality": "validated",
            "dedupe_key": f"fake:opportunity:{publication_before['id']}",
            "source_snapshot_ref": f"private://feedback/{publication_before['id']}", "observation_version": 1,
        },
        scoring_version={
            "id": SCORING, "org_id": ORG, "version": 1, "algorithm": "threshold-v1",
            "weights": {"opportunity_score_threshold": 0.8}, "active": True, "created_at": STAMP,
        },
    )

    assert result["recommendation"]["recommendation_type"] == "reprioritize"
    assert result["recommendation"]["target_id"] == publication_before["id"]
    assert result["action_created"] is False and result["production_rules_mutated"] is False
    assert published["publication_record"] == publication_before
