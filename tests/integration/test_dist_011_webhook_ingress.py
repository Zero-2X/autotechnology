from __future__ import annotations

from modules.distribution import FakeOfficialAdapter, FakeWebhookPort, sign_fixture_payload


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
POLICY = "00000000-0000-4000-8000-000000000004"
DECISION = "00000000-0000-4000-8000-000000000005"
INTENT = "00000000-0000-4000-8000-000000000006"
VARIANT = "00000000-0000-4000-8000-000000000007"
STAMP = "2026-09-19T00:00:00Z"
SECRET = "dist-011-fixture-secret"


def test_fake_publication_event_round_trips_through_signed_fixture_ingress() -> None:
    adapter = FakeOfficialAdapter(platform_id=PLATFORM)
    draft = adapter.create_draft(
        org_id=ORG, actor_id=ACTOR, trace_id="publish-trace", idempotency_key="draft",
        publication_intent={
            "id": INTENT, "org_id": ORG, "variant_version_id": VARIANT,
            "payload_snapshot": {"title": "Webhook fixture", "body": {}, "tags": [], "disclosure": None},
        },
        policy_snapshot_id=POLICY, execution_policy_decision_id=DECISION, created_at=STAMP,
    )
    published = adapter.publish(
        org_id=ORG, actor_id=ACTOR, trace_id="publish-trace", idempotency_key="publish",
        draft_id=draft["id"], expected_version=1, published_at=STAMP,
    )
    provider_event = adapter.events[-1]
    ingress = FakeWebhookPort(verification_secrets={PLATFORM: SECRET})
    handled: list[str] = []

    result = ingress.receive(
        org_id=ORG, actor_id=ACTOR, trace_id="webhook-trace", idempotency_key="ingress-1",
        platform_id=PLATFORM, external_event_id=provider_event["event_id"],
        raw_payload=provider_event, signature=sign_fixture_payload(provider_event, SECRET), received_at=STAMP,
        handler=lambda event: handled.append(event["payload"]["external_object_id"]) or {"recorded": True},
    )
    duplicate = ingress.receive(
        org_id=ORG, actor_id=ACTOR, trace_id="webhook-replay", idempotency_key="ingress-2",
        platform_id=PLATFORM, external_event_id=provider_event["event_id"],
        raw_payload=provider_event, signature=sign_fixture_payload(provider_event, SECRET), received_at=STAMP,
        handler=lambda event: handled.append("duplicate") or {},
    )

    assert result["receipt"]["status"] == "processed"
    assert result["handler_result"] == {"recorded": True}
    assert duplicate["receipt"]["status"] == "deduplicated"
    assert handled == [published["publication_record"]["external_object_id"]]
    assert len(ingress.receipts) == 1
