from uuid import uuid4

import pytest

from modules.feedback.core import FeedbackItemError, FeedbackRecommendationServiceV2


ORG = str(uuid4())
ITEM = str(uuid4())
TARGET = str(uuid4())
CTX = {"org_id": ORG, "actor_id": str(uuid4()), "trace_id": "feedback-rec"}


def item(kind="refresh", status="proposed"):
    return {"id": ITEM, "org_id": ORG, "observation_ids": [TARGET], "recommendation_type": kind,
            "confidence": .8, "status": status}


def test_generates_typed_recommendation_without_mutating_production_rules():
    service = FeedbackRecommendationServiceV2()
    result = service.recommend(feedback_item=item("channel_change"), context=CTX, idempotency_key="one", evidence=[{"metric": "low_ctr"}])
    assert result["target_type"] == "channel"
    assert result["recommendation_type"] == "channel_strategy"
    assert result["status"] == "proposed"
    assert service.audit[0]["production_rules_mutated"] is False
    assert "metric" not in service.outbox[0]["payload"]
    assert service.recommend(feedback_item=item("channel_change"), context=CTX, idempotency_key="one", evidence=[{"metric": "low_ctr"}]) == result


def test_tenant_and_status_gates_and_idempotency_conflict():
    service = FeedbackRecommendationServiceV2()
    with pytest.raises(FeedbackItemError) as error:
        service.recommend(feedback_item={**item(), "org_id": str(uuid4())}, context=CTX, idempotency_key="x")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(FeedbackItemError) as error:
        service.recommend(feedback_item=item(status="executed"), context=CTX, idempotency_key="x")
    assert error.value.code == "FEEDBACK_NOT_ACTIONABLE"
    service.recommend(feedback_item=item(), context=CTX, idempotency_key="same")
    with pytest.raises(FeedbackItemError) as error:
        service.recommend(feedback_item=item("reprioritize"), context=CTX, idempotency_key="same")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
