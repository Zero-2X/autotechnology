from __future__ import annotations

import pytest

from modules.distribution import PublicationReconciler, ReconciliationError


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
INTENT = "00000000-0000-4000-8000-000000000003"
POLICY = "00000000-0000-4000-8000-000000000004"
DECISION = "00000000-0000-4000-8000-000000000005"
ATTEMPT = "00000000-0000-4000-8000-000000000006"
STAMP = "2026-09-19T00:00:00Z"


def _attempt(org_id: str = ORG, attempt_id: str = ATTEMPT) -> dict:
    return {
        "id": attempt_id, "org_id": org_id, "publication_intent_id": INTENT, "account_connection_id": None,
        "adapter_ref": "fake:official@v1", "provider_mode": "fake", "environment": "dev",
        "policy_snapshot_id": POLICY, "execution_policy_decision_id": DECISION, "adapter_version": "v1",
        "capability_snapshot": {}, "idempotency_key": "attempt", "provider_idempotency_key": "provider",
        "attempt_no": 1, "parent_attempt_id": None, "status": "running", "retryable": False,
        "next_attempt_at": None, "max_attempts": 1, "started_at": STAMP, "completed_at": None,
        "external_request_id": None, "external_object_id": None, "account_connection_snapshot": {},
        "error_class": None, "last_error_code": None, "last_error_at": None, "resolution_reason": None,
        "resolved_by": None, "resolved_at": None, "created_at": STAMP,
    }


def test_upload_acknowledge_publish_replay_and_record_creation() -> None:
    service = PublicationReconciler()
    uploaded = service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="uploaded",
                               delivery_attempt=_attempt(), observed_status="uploaded", observed_at=STAMP,
                               external_request_id="req-1", external_object_id="obj-1", observation_source="adapter")
    assert uploaded["publication_record"]["status"] == "acknowledged"
    published = service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="published",
                               delivery_attempt=_attempt(), observed_status="published", observed_at="2026-09-19T00:01:00Z",
                               external_request_id="req-1", external_object_id="obj-1", external_url="private://fake/obj-1", observation_source="poll")
    assert published["publication_record"]["status"] == "published"
    replay = service.observe(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="published",
                             delivery_attempt=_attempt(), observed_status="published", observed_at="2026-09-19T00:01:00Z",
                             external_request_id="req-1", external_object_id="obj-1", external_url="private://fake/obj-1", observation_source="poll")
    assert replay == published
    assert service.events[-1]["event_type"] == "publication.reconciled"


def test_unknown_result_requires_reason_and_never_becomes_success_by_regression() -> None:
    service = PublicationReconciler()
    unknown = service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown",
                              delivery_attempt=_attempt(attempt_id="00000000-0000-4000-8000-000000000007"), observed_status="unknown",
                              observed_at=STAMP, unknown_reason="provider response lost", observation_source="manual")
    assert unknown["publication_record"]["status"] == "unknown"
    with pytest.raises(ReconciliationError) as error:
        service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="unknown-no-reason",
                        delivery_attempt=_attempt(attempt_id="00000000-0000-4000-8000-000000000008"), observed_status="unknown", observed_at=STAMP)
    assert error.value.code == "UNKNOWN_REASON_REQUIRED"
    service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="success",
                    delivery_attempt=_attempt(), observed_status="published", observed_at="2026-09-19T00:02:00Z",
                    external_object_id="obj-1", observation_source="poll")
    with pytest.raises(ReconciliationError) as error:
        service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="regress",
                        delivery_attempt=_attempt(), observed_status="acknowledged", observed_at="2026-09-19T00:03:00Z", observation_source="poll")
    assert error.value.code == "OBSERVATION_REGRESSION"


def test_cross_tenant_attempt_is_rejected() -> None:
    service = PublicationReconciler()
    with pytest.raises(ReconciliationError) as error:
        service.observe(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="foreign",
                        delivery_attempt=_attempt(OTHER_ORG), observed_status="uploaded", observed_at=STAMP)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
