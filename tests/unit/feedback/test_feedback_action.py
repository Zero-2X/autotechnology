from uuid import uuid4

import pytest

from modules.feedback.core import FeedbackActionService, FeedbackItemError


ORG, ACTOR, ITEM, TARGET = [str(uuid4()) for _ in range(4)]
CTX = {"org_id": ORG, "actor_id": ACTOR, "trace_id": "feedback-action"}
POLICY = {"decision": "allow", "side_effect_blocked": False, "policy_snapshot_id": str(uuid4())}


def make(service=None):
    service = service or FeedbackActionService()
    return service.create_action(feedback_item_id=ITEM, action_type="refresh", target_type="variant", target_id=TARGET,
        target_version=2, context=CTX, idempotency_key="create", policy_decision=POLICY)


def test_lifecycle_requires_approval_and_preserves_side_effect_boundary():
    service = FeedbackActionService(); action = make(service)
    assert action["status"] == "proposed" and action["result_snapshot"]["side_effect_blocked"] is True
    with pytest.raises(FeedbackItemError) as error:
        service.start(action["id"], context=CTX, idempotency_key="start-before-approval", expected_version=1, policy_decision=POLICY)
    assert error.value.code == "INVALID_ACTION_TRANSITION"
    approved = service.approve(action["id"], context=CTX, idempotency_key="approve", expected_version=1,
                               approval={"status": "approved", "approved_by": ACTOR, "approved_at": "2026-09-21T00:00:00Z"})
    running = service.start(action["id"], context=CTX, idempotency_key="start", expected_version=2, policy_decision=POLICY)
    done = service.complete(action["id"], context=CTX, idempotency_key="complete", expected_version=3,
                             result_snapshot={"output_hash": "a" * 64, "affected_version": 3})
    assert approved["status"] == "approved" and running["status"] == "executing" and done["status"] == "executed"
    assert done["result_snapshot"]["side_effect_blocked"] is False
    assert all(event["payload"]["side_effect_triggered"] is False for event in service.outbox)


def test_policy_sensitive_and_version_guards():
    service = FeedbackActionService()
    with pytest.raises(FeedbackItemError) as error:
        service.create_action(feedback_item_id=ITEM, action_type="refresh", target_type="variant", target_id=TARGET,
            target_version=1, context=CTX, idempotency_key="blocked", policy_decision={"decision": "deny"})
    assert error.value.code == "POLICY_BLOCKED"
    action = make(service)
    with pytest.raises(FeedbackItemError) as error:
        service.cancel(action["id"], context=CTX, idempotency_key="cancel", expected_version=2)
    assert error.value.code == "OPTIMISTIC_LOCK_CONFLICT"
    with pytest.raises(FeedbackItemError) as error:
        service.complete(action["id"], context=CTX, idempotency_key="sensitive", expected_version=1,
                         result_snapshot={"token": "secret"})
    assert error.value.code == "INVALID_ACTION_TRANSITION"
