from __future__ import annotations

import pytest

from modules.distribution import RetryPolicyError, RetryPolicyService


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
STAMP = "2026-09-19T00:00:00Z"


def test_quota_reservation_and_retry_after_are_tenant_scoped_and_idempotent() -> None:
    service = RetryPolicyService(quota_limit=2, window_seconds=60)
    first = service.reserve(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="one", now=STAMP)
    replay = service.reserve(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="one", now=STAMP)
    assert first == replay and first["remaining"] == 1
    second = service.reserve(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="two", now=STAMP)
    assert second["allowed"] is True and second["remaining"] == 0
    exceeded = service.reserve(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="three", now=STAMP)
    assert exceeded["allowed"] is False and exceeded["retry_after_seconds"] == 60


def test_error_classification_distinguishes_transient_exhausted_deterministic_and_unknown() -> None:
    service = RetryPolicyService()
    transient = service.classify(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="transient",
                                 error_code="PLATFORM_RATE_LIMITED", attempt_no=1, max_attempts=3,
                                 retry_after_seconds=17, now=STAMP)
    assert transient["classification"] == "transient" and transient["retryable"] is True and transient["retry_after_seconds"] == 17
    exhausted = service.classify(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="exhausted",
                                 error_code="PLATFORM_UNAVAILABLE", attempt_no=3, max_attempts=3, now=STAMP)
    assert exhausted["terminal_status"] == "dead_letter" and exhausted["manual_task_required"] is True
    deterministic = service.classify(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="deterministic",
                                     error_code="DRAFT_VERSION_CONFLICT", attempt_no=1, max_attempts=3, now=STAMP)
    assert deterministic["classification"] == "deterministic" and deterministic["retryable"] is False
    unknown = service.classify(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown",
                               error_code="OUTBOX_PUBLISH_UNKNOWN", attempt_no=1, max_attempts=3, now=STAMP)
    assert unknown["classification"] == "unknown" and unknown["manual_task_required"] is True
    assert service.events[-1]["event_type"] == "distribution.delivery.manual_escalation"


def test_invalid_retry_inputs_and_idempotency_reuse_are_rejected() -> None:
    service = RetryPolicyService()
    service.reserve(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="same", now=STAMP)
    with pytest.raises(RetryPolicyError) as error:
        service.reserve(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="same", now=STAMP, units=2)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(RetryPolicyError) as error:
        service.classify(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="invalid",
                         error_code="X", attempt_no=0, max_attempts=1)
    assert error.value.code == "INVALID_RETRY_POLICY"
