from __future__ import annotations

import pytest

from modules.distribution import DeliveryIdempotencyError, DeliveryIdempotencyService


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
INTENT = "00000000-0000-4000-8000-000000000003"
TARGET = "00000000-0000-4000-8000-000000000004"
VARIANT = "00000000-0000-4000-8000-000000000005"
REGION = "00000000-0000-4000-8000-000000000006"
POLICY = "00000000-0000-4000-8000-000000000007"
DECISION = "00000000-0000-4000-8000-000000000008"
ATTEMPT = "00000000-0000-4000-8000-000000000009"
STAMP = "2026-09-19T00:00:00Z"


def _intent(org_id: str = ORG) -> dict:
    return {
        "id": INTENT, "org_id": org_id, "variant_version_id": VARIANT, "asset_version_ids": [],
        "distribution_target_version_id": TARGET, "delivery_mode": "simulation", "region_profile_version_id": REGION,
        "payload_snapshot": {"title": "Intent", "body": {}, "tags": [], "disclosure": None},
        "payload_snapshot_hash": "a" * 64, "scheduled_at": None, "policy_snapshot_id": POLICY,
        "capability_snapshot_hash": "b" * 64, "intent_key": "intent-key", "derived_from_intent_id": None,
        "status": "planned", "created_by": ACTOR, "created_at": STAMP, "updated_at": STAMP, "resolved_at": None,
    }


def _attempt() -> dict:
    return {
        "id": ATTEMPT, "org_id": ORG, "publication_intent_id": INTENT, "account_connection_id": None,
        "adapter_ref": "fake:official@v1", "provider_mode": "fake", "environment": "dev",
        "policy_snapshot_id": POLICY, "execution_policy_decision_id": DECISION, "adapter_version": "v1",
        "capability_snapshot": {}, "idempotency_key": "attempt-command", "provider_idempotency_key": "provider-attempt",
        "attempt_no": 1, "parent_attempt_id": None, "status": "succeeded", "retryable": False,
        "next_attempt_at": None, "max_attempts": 1, "started_at": STAMP, "completed_at": STAMP,
        "external_request_id": None, "external_object_id": None, "account_connection_snapshot": {},
        "error_class": None, "last_error_code": None, "last_error_at": None, "resolution_reason": None,
        "resolved_by": None, "resolved_at": None, "created_at": STAMP,
    }


def _event(key: str = "event-command") -> dict:
    payload = {"aggregate_id": INTENT, "aggregate_version": 1, "to_state": "simulated"}
    from hashlib import sha256
    import json
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"event_id": "00000000-0000-4000-8000-000000000010", "event_type": "publication.simulated",
            "event_schema_version": 1, "occurred_at": STAMP, "org_id": ORG, "trace_id": "trace",
            "aggregate_type": "publication_intent", "aggregate_id": INTENT, "aggregate_version": 1,
            "actor_type": "service", "actor_id": ACTOR, "idempotency_key": key,
            "payload": payload, "payload_hash": digest}


def test_intent_attempt_and_event_replay_do_not_duplicate_facts_or_handlers() -> None:
    service = DeliveryIdempotencyService()
    intent = service.accept_intent(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="intent", intent=_intent())
    assert service.accept_intent(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="intent", intent=_intent()) == intent
    attempt = service.accept_attempt(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="attempt", attempt=_attempt())
    assert service.accept_attempt(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="attempt", attempt=_attempt()) == attempt
    calls = []
    first = service.consume_event(org_id=ORG, actor_id=ACTOR, trace_id="trace", envelope=_event(), handler=lambda event: calls.append(event["event_id"]) or {"done": True})
    replay = service.consume_event(org_id=ORG, actor_id=ACTOR, trace_id="replay", envelope=_event(), handler=lambda event: calls.append("duplicate") or {"done": False})
    assert first == replay and calls == [first["event_id"]]


def test_conflicting_payloads_duplicate_attempts_and_cross_tenant_are_rejected() -> None:
    service = DeliveryIdempotencyService()
    service.accept_intent(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="intent", intent=_intent())
    with pytest.raises(DeliveryIdempotencyError) as error:
        service.accept_intent(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="intent",
                              intent={**_intent(), "intent_key": "changed"})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    service.accept_attempt(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="attempt", attempt=_attempt())
    with pytest.raises(DeliveryIdempotencyError) as error:
        service.accept_attempt(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="changed-attempt",
                               attempt={**_attempt(), "status": "failed"})
    assert error.value.code == "DUPLICATE_DELIVERY_ATTEMPT"
    with pytest.raises(DeliveryIdempotencyError) as error:
        service.accept_intent(org_id=OTHER_ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="foreign", intent=_intent())
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
