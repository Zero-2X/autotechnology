from __future__ import annotations

from uuid import uuid4

import pytest

from modules.distribution import DistributionError, ManualAdapter


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
VARIANT = "00000000-0000-4000-8000-000000000003"
ASSET = "00000000-0000-4000-8000-000000000004"
INTENT = "00000000-0000-4000-8000-000000000005"
STAMP = "2026-09-19T00:00:00Z"


def _intent(org_id: str = ORG) -> dict:
    return {
        "id": INTENT, "org_id": org_id, "variant_version_id": VARIANT, "asset_version_ids": [ASSET],
        "payload_snapshot": {"title": "Manual title", "body": {}, "tags": ["one"], "disclosure": "Ad"},
    }


def test_manual_adapter_builds_private_content_media_checklist_and_evidence_package() -> None:
    adapter = ManualAdapter()
    first = adapter.export(
        org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="export", publication_intent=_intent(),
        media=[{"asset_version_id": ASSET, "storage_object_ref": "private://asset/source", "position": 1, "alt": "hero"}],
        checklist=[{"key": "rights", "status": "passed"}, {"key": "qa", "status": "pending"}],
        evidence=[{"ref": "private://evidence/qa", "kind": "qa"}], generated_at=STAMP,
    )
    replay = adapter.export(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="export", publication_intent=_intent(),
                            media=[{"asset_version_id": ASSET, "storage_object_ref": "private://asset/source", "position": 1, "alt": "hero"}],
                            checklist=[{"key": "rights", "status": "passed"}, {"key": "qa", "status": "pending"}],
                            evidence=[{"ref": "private://evidence/qa", "kind": "qa"}], generated_at=STAMP)
    assert first == replay
    assert first["export_package"]["storage_object_ref"].startswith("private://")
    assert first["manifest"]["title"] == "Manual title"
    assert first["manifest"]["media"][0]["storage_object_ref"].startswith("private://")
    assert {item["name"] for item in first["files"]} >= {"manifest.json", "content/title.txt", "content/body.json", "evidence/index.json"}
    assert adapter.events[-1]["event_type"] == "distribution.manual_export.created"


def test_manual_adapter_rejects_public_media_and_cross_tenant_intent() -> None:
    adapter = ManualAdapter()
    with pytest.raises(DistributionError) as error:
        adapter.export(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="public",
                       publication_intent=_intent(), media=[{"asset_version_id": ASSET, "storage_object_ref": "https://example.test/image"}], generated_at=STAMP)
    assert error.value.code == "PUBLIC_MEDIA_URL_FORBIDDEN"
    with pytest.raises(DistributionError) as error:
        adapter.export(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="foreign",
                       publication_intent=_intent(OTHER_ORG), generated_at=STAMP)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_manual_adapter_rejects_idempotency_payload_reuse() -> None:
    adapter = ManualAdapter()
    adapter.export(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="same", publication_intent=_intent(), generated_at=STAMP)
    changed = {**_intent(), "payload_snapshot": {"title": "Changed", "body": {}, "tags": ["one"], "disclosure": "Ad"}}
    with pytest.raises(DistributionError) as error:
        adapter.export(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="same", publication_intent=changed, generated_at=STAMP)
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
