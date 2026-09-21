from __future__ import annotations

import pytest

from modules.distribution import DeadLetterError, DeliveryDeadLetterService


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
INTENT = "00000000-0000-4000-8000-000000000003"
POLICY = "00000000-0000-4000-8000-000000000004"
DECISION = "00000000-0000-4000-8000-000000000005"
ATTEMPT = "00000000-0000-4000-8000-000000000006"
STAMP = "2026-09-19T00:00:00Z"


def _attempt(*, status: str = "running", retryable: bool = True, attempt_no: int = 1, max_attempts: int = 2,
             org_id: str = ORG, attempt_id: str = ATTEMPT) -> dict:
    return {
        "id": attempt_id, "org_id": org_id, "publication_intent_id": INTENT, "account_connection_id": None,
        "adapter_ref": "fake:official@v1", "provider_mode": "fake", "environment": "dev",
        "policy_snapshot_id": POLICY, "execution_policy_decision_id": DECISION, "adapter_version": "v1",
        "capability_snapshot": {}, "idempotency_key": "attempt-key", "provider_idempotency_key": "provider-key",
        "attempt_no": attempt_no, "parent_attempt_id": None, "status": status, "retryable": retryable,
        "next_attempt_at": None, "max_attempts": max_attempts, "started_at": STAMP,
        "completed_at": None, "external_request_id": None, "external_object_id": None,
        "account_connection_snapshot": {}, "error_class": None, "last_error_code": None,
        "last_error_at": None, "resolution_reason": None, "resolved_by": None, "resolved_at": None,
        "created_at": STAMP,
    }


def test_unknown_creates_one_human_task_and_blocks_retry() -> None:
    service = DeliveryDeadLetterService()
    result = service.mark_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown-1",
                                  delivery_attempt=_attempt(), reason="provider response lost", observed_at=STAMP)
    assert result["delivery_attempt"]["status"] == "unknown"
    assert result["delivery_attempt"]["retryable"] is False
    assert result["human_task"]["task_type"] == "unknown_result"
    assert result["event"]["event_type"] == "delivery.unknown"
    assert result["side_effect_triggered"] is False
    replay = service.mark_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown-2",
                                  delivery_attempt=result["delivery_attempt"], reason="provider response lost", observed_at=STAMP)
    assert replay["human_task"]["id"] == result["human_task"]["id"]
    assert len(service.human_tasks) == 1


def test_dead_letter_requires_retry_limit_and_is_idempotent() -> None:
    service = DeliveryDeadLetterService()
    with pytest.raises(DeadLetterError, match="attempts remaining"):
        service.dead_letter(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="dead-early",
                            delivery_attempt=_attempt(), reason="transient")
    failed = _attempt(status="failed", attempt_no=2, max_attempts=2)
    first = service.dead_letter(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="dead-1",
                                delivery_attempt=failed, reason="retry limit reached", occurred_at=STAMP)
    second = service.dead_letter(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="dead-1",
                                 delivery_attempt=failed, reason="retry limit reached", occurred_at=STAMP)
    assert first == second
    assert first["delivery_attempt"]["status"] == "dead_letter"
    assert first["human_task"]["task_type"] == "support_escalation"
    assert first["event"]["event_type"] == "delivery.dead_lettered"


def test_unknown_resolution_closes_task_and_emits_resolution_event() -> None:
    service = DeliveryDeadLetterService()
    unknown = service.mark_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown",
                                   delivery_attempt=_attempt(), reason="timeout", observed_at=STAMP)
    resolved = service.resolve_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="resolve",
                                      delivery_attempt=unknown["delivery_attempt"], outcome="succeeded",
                                      resolution_reason="verified in provider console", evidence_ref="evidence://1",
                                      resolved_at=STAMP)
    assert resolved["delivery_attempt"]["status"] == "succeeded"
    assert resolved["publication_record"]["status"] == "published"
    assert resolved["human_task"]["status"] == "completed"
    assert resolved["event"]["event_type"] == "delivery.unknown_resolved"


def test_replay_requires_original_key_and_never_calls_side_effect() -> None:
    service = DeliveryDeadLetterService()
    unknown = service.mark_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown",
                                   delivery_attempt=_attempt(), reason="timeout", observed_at=STAMP)
    with pytest.raises(DeadLetterError, match="original idempotency key"):
        service.replay_one(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="different",
                           delivery_attempt=unknown["delivery_attempt"], manual_confirmation=True)
    with pytest.raises(DeadLetterError, match="manual confirmation"):
        service.replay_one(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="attempt-key",
                           delivery_attempt=unknown["delivery_attempt"], manual_confirmation=False)
    result = service.replay_one(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="attempt-key",
                                delivery_attempt=unknown["delivery_attempt"], manual_confirmation=True)
    assert result["delivery_attempt"]["status"] == "created"
    assert result["delivery_attempt"]["idempotency_key"] == "attempt-key"
    assert result["delivery_attempt"]["provider_idempotency_key"] == "provider-key"
    assert result["delivery_attempt"]["parent_attempt_id"] == ATTEMPT
    assert result["requires_manual_trigger"] is True
    assert result["side_effect_triggered"] is False


def test_cross_tenant_and_version_conflict_are_rejected() -> None:
    service = DeliveryDeadLetterService()
    with pytest.raises(DeadLetterError, match="outside this organization"):
        service.mark_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="foreign",
                             delivery_attempt=_attempt(org_id=OTHER_ORG), reason="timeout")
    result = service.mark_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="version-1",
                                  delivery_attempt=_attempt(attempt_id="00000000-0000-4000-8000-000000000007"), reason="timeout")
    with pytest.raises(DeadLetterError, match="does not match"):
        service.resolve_unknown(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="version-2",
                                delivery_attempt=result["delivery_attempt"], outcome="failed", resolution_reason="confirmed",
                                evidence_ref="evidence://2", expected_version=2)
