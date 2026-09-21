from __future__ import annotations

from hashlib import sha256
import json

import pytest

from modules.distribution import FakeWebhookPort, WebhookError, sign_fixture_payload


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
AGGREGATE = "00000000-0000-4000-8000-000000000004"
EVENT = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"
SECRET = "fixture-only-secret"


def _hash(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _event(*, org_id: str = ORG, event_id: str = EVENT) -> dict:
    payload = {"aggregate_id": AGGREGATE, "aggregate_version": 1, "provider_status": "published"}
    return {
        "event_id": event_id, "event_type": "provider.publication.updated", "event_schema_version": 1,
        "occurred_at": STAMP, "org_id": org_id, "trace_id": "provider-trace",
        "aggregate_type": "PublicationIntent", "aggregate_id": AGGREGATE, "aggregate_version": 1,
        "actor_type": "service", "actor_id": None, "idempotency_key": "provider-event-key",
        "payload": payload, "payload_hash": _hash(payload),
    }


def _port(*, max_attempts: int = 2) -> FakeWebhookPort:
    return FakeWebhookPort(verification_secrets={PLATFORM: SECRET}, max_attempts=max_attempts)


def _receive(port: FakeWebhookPort, *, key: str, external_id: str, event: dict,
             signature: str | None = None, handler=None) -> dict:
    return port.receive(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key=key,
        platform_id=PLATFORM, external_event_id=external_id, raw_payload=event,
        signature=signature if signature is not None else sign_fixture_payload(event, SECRET),
        received_at=STAMP, handler=handler,
    )


def test_signed_fixture_is_processed_and_external_duplicate_skips_handler() -> None:
    port = _port()
    calls: list[str] = []
    event = _event()
    first = _receive(port, key="receive-1", external_id="external-1", event=event,
                     handler=lambda value: calls.append(value["event_id"]) or {"accepted": True})
    duplicate = _receive(port, key="receive-2", external_id="external-1", event=event,
                         handler=lambda value: calls.append("duplicate") or {})

    assert first["receipt"]["status"] == "processed"
    assert first["receipt"]["raw_payload_ref"].startswith("private://")
    assert first["event"]["event_type"] == "webhook.processed"
    assert duplicate["receipt"]["status"] == "deduplicated"
    assert duplicate["event"]["event_type"] == "webhook.deduplicated"
    assert calls == [EVENT]


def test_invalid_signature_schema_and_cross_tenant_event_are_rejected() -> None:
    port = _port()
    event = _event()
    invalid_signature = _receive(port, key="bad-signature", external_id="external-signature",
                                 event=event, signature="sha256=invalid")
    assert invalid_signature["receipt"]["signature_valid"] is False
    assert invalid_signature["receipt"]["last_error"] == "INVALID_SIGNATURE"

    invalid_schema = {**event, "event_id": "not-a-uuid"}
    invalid_schema["idempotency_key"] = "schema-event-key"
    rejected_schema = _receive(port, key="bad-schema", external_id="external-schema", event=invalid_schema)
    assert rejected_schema["receipt"]["last_error"] == "INVALID_EVENT_SCHEMA"

    foreign = _event(org_id=OTHER_ORG, event_id="00000000-0000-4000-8000-000000000006")
    rejected_tenant = _receive(port, key="foreign", external_id="external-foreign", event=foreign)
    assert rejected_tenant["receipt"]["last_error"] == "TENANT_SCOPE_VIOLATION"
    assert all(result["event"]["event_type"] == "webhook.rejected"
               for result in (invalid_signature, rejected_schema, rejected_tenant))


def test_handler_failure_dead_letters_then_manual_replay_processes() -> None:
    port = _port(max_attempts=2)
    event = _event()

    def fail(_: dict) -> dict:
        raise RuntimeError("fixture handler unavailable")

    first = _receive(port, key="failure-1", external_id="external-failure", event=event, handler=fail)
    assert first["receipt"]["status"] == "received"
    assert first["receipt"]["processing_attempts"] == 1
    with pytest.raises(WebhookError) as error:
        port.replay(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="no-confirm",
                    receipt_id=first["receipt"]["id"], manual_confirmation=False, replayed_at=STAMP)
    assert error.value.code == "MANUAL_CONFIRMATION_REQUIRED"

    dead = port.replay(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="replay-fail",
                       receipt_id=first["receipt"]["id"], manual_confirmation=True,
                       handler=fail, replayed_at=STAMP)
    assert dead["receipt"]["status"] == "dead_letter"
    assert dead["event"]["event_type"] == "webhook.dead_lettered"

    processed = port.replay(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="replay-success",
                            receipt_id=dead["receipt"]["id"], manual_confirmation=True,
                            handler=lambda value: {"event_id": value["event_id"]}, replayed_at=STAMP)
    assert processed["receipt"]["status"] == "processed"
    assert processed["receipt"]["replay_count"] == 2
    assert processed["handler_result"] == {"event_id": EVENT}
    assert processed["side_effect_triggered"] is False


def test_rejected_receipt_conflicts_and_cross_tenant_replay_fail_closed() -> None:
    port = _port()
    event = _event()
    rejected = _receive(port, key="rejected", external_id="external-rejected", event=event,
                        signature="sha256=invalid")
    with pytest.raises(WebhookError) as error:
        port.replay(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="replay-rejected",
                    receipt_id=rejected["receipt"]["id"], manual_confirmation=True, replayed_at=STAMP)
    assert error.value.code == "INVALID_REPLAY_STATE"

    accepted = _receive(port, key="accepted", external_id="external-accepted", event=event)
    with pytest.raises(WebhookError) as error:
        port.replay(org_id=OTHER_ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="foreign-replay",
                    receipt_id=accepted["receipt"]["id"], manual_confirmation=True, replayed_at=STAMP)
    assert error.value.code == "WEBHOOK_RECEIPT_NOT_FOUND"

    changed = _event(event_id="00000000-0000-4000-8000-000000000007")
    with pytest.raises(WebhookError) as error:
        _receive(port, key="changed", external_id="external-accepted", event=changed)
    assert error.value.code == "EXTERNAL_EVENT_CONFLICT"

    with pytest.raises(WebhookError) as error:
        _receive(port, key="accepted", external_id="another-external-id", event=event)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
