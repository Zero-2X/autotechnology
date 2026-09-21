from __future__ import annotations

from uuid import uuid4

import pytest

from modules.distribution import FakeOfficialAdapter, FakeOfficialError


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
POLICY = "00000000-0000-4000-8000-000000000004"
DECISION = "00000000-0000-4000-8000-000000000005"
INTENT = "00000000-0000-4000-8000-000000000006"
VARIANT = "00000000-0000-4000-8000-000000000007"
STAMP = "2026-09-19T00:00:00Z"


def _intent() -> dict:
    return {
        "id": INTENT, "org_id": ORG, "variant_version_id": VARIANT, "asset_version_ids": [],
        "payload_snapshot": {"title": "Fake official draft", "body": {}, "tags": ["demo"], "disclosure": None},
    }


def _adapter() -> tuple[FakeOfficialAdapter, dict]:
    adapter = FakeOfficialAdapter(platform_id=PLATFORM)
    draft = adapter.create_draft(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="draft",
                                 publication_intent=_intent(), policy_snapshot_id=POLICY,
                                 execution_policy_decision_id=DECISION, created_at=STAMP)
    return adapter, draft


def test_fake_official_capability_draft_upload_schedule_publish_and_metrics() -> None:
    adapter, draft = _adapter()
    capability = adapter.get_capability(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="capability")
    assert set(capability["actions"]) >= {"draft", "upload", "schedule", "publish", "metrics"}
    uploaded = adapter.upload_media(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="upload",
                                    draft_id=draft["id"], media={"asset_version_id": str(uuid4()), "storage_object_ref": "private://asset/media"}, expected_version=1)
    assert uploaded["version"] == 2
    assert adapter.upload_media(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="upload",
                                draft_id=draft["id"], media={"asset_version_id": uploaded["media"][0]["asset_version_id"], "storage_object_ref": "private://asset/media"}, expected_version=1) == uploaded
    scheduled = adapter.schedule(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="schedule",
                                 draft_id=draft["id"], expected_version=2, scheduled_at="2026-09-20T00:00:00Z", now=STAMP)
    assert scheduled["status"] == "scheduled"
    published = adapter.publish(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="publish",
                                draft_id=draft["id"], expected_version=3, published_at="2026-09-20T00:00:00Z")
    assert published["publication_record"]["status"] == "published"
    assert published["publication_record"]["provider_mode"] == "fake"
    assert published["delivery_attempt"]["adapter_ref"] == "fake:official@v1"
    assert published["publication_record"]["result_snapshot"]["simulated"] is True
    metrics = adapter.get_metrics(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="metrics", draft_id=draft["id"])
    assert metrics["views"] == 0 and metrics["likes"] == 0
    assert adapter.events[-1]["event_type"] == "publication.recorded"


def test_fake_official_error_codes_and_tenant_scope_are_deterministic() -> None:
    adapter, draft = _adapter()
    adapter.fail_next(org_id=ORG, error_code="PLATFORM_RATE_LIMITED")
    with pytest.raises(FakeOfficialError) as error:
        adapter.upload_media(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="rate",
                             draft_id=draft["id"], media={"asset_version_id": str(uuid4()), "storage_object_ref": "private://asset/media"}, expected_version=1)
    assert error.value.code == "PLATFORM_RATE_LIMITED"
    with pytest.raises(FakeOfficialError) as error:
        adapter.publish(org_id=OTHER_ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="foreign",
                        draft_id=draft["id"], expected_version=1, published_at=STAMP)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(FakeOfficialError) as error:
        adapter.schedule(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="invalid-time",
                         draft_id=draft["id"], expected_version=1, scheduled_at=STAMP, now=STAMP)
    assert error.value.code == "SCHEDULE_INVALID"


def test_fake_official_stale_version_is_rejected_without_mutating_draft() -> None:
    adapter, draft = _adapter()
    with pytest.raises(FakeOfficialError) as error:
        adapter.upload_media(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="stale",
                             draft_id=draft["id"], media={"asset_version_id": str(uuid4()), "storage_object_ref": "private://asset/media"}, expected_version=2)
    assert error.value.code == "DRAFT_VERSION_CONFLICT"
    assert adapter.drafts[(ORG, draft["id"])]["version"] == 1
