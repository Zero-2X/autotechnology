from uuid import uuid4

import pytest

from modules.feedback.core import FeedbackItemError, FeedbackItemService


ORG = str(uuid4())
ACTOR = str(uuid4())
OBS = str(uuid4())
CTX = {"org_id": ORG, "actor_id": ACTOR, "trace_id": "feedback-item"}


def observation():
    return {"id": OBS, "org_id": ORG, "source": "manual", "subject_type": "content", "subject_id": str(uuid4()),
            "metric_definition_id": str(uuid4()), "metric_definition_version_no": 1, "metric_name": "quality.issue",
            "metric_type": "string", "metric_value": "stale", "observed_at": "2026-09-21T00:00:00Z",
            "locale": "en-US", "region": "US", "data_quality": "validated", "dedupe_key": "manual:one",
            "source_snapshot_ref": "private://observation/one", "observation_version": 1}


def create(service=None, key="create"):
    service = service or FeedbackItemService()
    return service.create_feedback_item(observation_ids=[OBS], problem="stale content", recommendation_type="refresh",
        impact="high", priority="high", confidence=.9, reasoning_snapshot={"rule": "freshness"},
        context=CTX, idempotency_key=key, observations=[observation()])


def test_create_is_schema_valid_idempotent_and_audited():
    service = FeedbackItemService()
    first = create(service)
    assert first["status"] == "proposed"
    assert create(service) == first
    assert len(service.store.outbox) == 1
    assert service.store.audit[0]["event_type"] == "feedback.item.created"


def test_status_transition_requires_expected_version_and_quorum_actor():
    service = FeedbackItemService()
    item = create(service)
    approved = service.approve(item["id"], context=CTX, idempotency_key="approve", expected_version=1)
    assert approved["status"] == "approved" and approved["approver_id"] == ACTOR
    executed = service.transition_feedback_item(item["id"], status="executed", context=CTX, idempotency_key="execute", expected_version=2)
    assert executed["status"] == "executed"
    with pytest.raises(FeedbackItemError) as error:
        service.transition_feedback_item(item["id"], status="rejected", context=CTX, idempotency_key="bad", expected_version=2)
    assert error.value.code == "OPTIMISTIC_LOCK_CONFLICT"


def test_tenant_and_observation_source_boundaries():
    service = FeedbackItemService()
    with pytest.raises(FeedbackItemError) as error:
        service.create_feedback_item(observation_ids=[OBS], problem="x", recommendation_type="refresh", impact="low", priority="low",
            confidence=.5, reasoning_snapshot={}, context={"org_id": str(uuid4())}, idempotency_key="x", observations=[observation()])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    bad = {**observation(), "id": str(uuid4()), "source": "platform"}
    with pytest.raises(FeedbackItemError) as error:
        service.create_feedback_item(observation_ids=[bad["id"]], problem="x", recommendation_type="refresh", impact="low", priority="low",
            confidence=.5, reasoning_snapshot={}, context=CTX, idempotency_key="platform", observations=[bad])
    assert error.value.code == "SOURCE_NOT_ALLOWED"
