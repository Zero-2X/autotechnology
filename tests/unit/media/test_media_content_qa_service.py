from __future__ import annotations

from uuid import uuid4

import pytest

from modules.media import FakeTextExtractionPort, MediaContentQAError, MediaContentRightsQAService


def _fixture():
    org, actor, asset_id, rights_id = (str(uuid4()) for _ in range(4))
    asset = {
        "id": asset_id, "org_id": org, "version_no": 2, "media_type": "video",
        "variant_version_id": str(uuid4()), "rights_snapshot_ids": [rights_id], "file_hash": "a" * 64,
    }
    rights = {
        "id": rights_id, "org_id": org, "status": "verified", "valid_from": None, "valid_to": None,
        "permitted_regions": ["US"], "permitted_locales": ["en-US"], "permitted_media": ["video"],
        "permitted_use": "commercial", "snapshot_hash": "b" * 64,
    }
    source = "Latency is 20 ms in v1.2.3. AI generated. Sponsored. `x=1`."
    return org, actor, asset, rights, source


def test_content_rights_qa_passes_protected_tokens_disclosures_and_rights() -> None:
    org, actor, asset, rights, source = _fixture()
    extractor = FakeTextExtractionPort(text=source)
    service = MediaContentRightsQAService(extractor=extractor)
    report = service.run_content_qa(
        org_id=org, actor_id=actor, asset_version=asset, source_text=source, rights_versions=[rights],
        market="US", locale="en-US", ai_generated=True, advertising_required=True,
        idempotency_key="content-pass", evaluated_at="2026-09-20T12:00:00Z",
    )
    assert report["status"] == "passed"
    assert report["findings"] == []
    assert all(item["status"] == "passed" for item in report["checks"].values())
    replay = service.run_content_qa(
        org_id=org, actor_id=actor, asset_version=asset, source_text=source, rights_versions=[rights],
        market="US", locale="en-US", ai_generated=True, advertising_required=True,
        idempotency_key="content-pass", evaluated_at="2026-09-20T12:00:00Z",
    )
    assert replay == report
    assert len(extractor.calls) == 1


def test_content_rights_qa_fails_changed_number_code_version_disclosure_and_rights() -> None:
    org, actor, asset, rights, source = _fixture()
    observed = "Latency is 30 ms in v1.2.4. `x=2`."
    expired = {**rights, "status": "withdrawn", "permitted_regions": ["GB"]}
    report = MediaContentRightsQAService(extractor=FakeTextExtractionPort(text=observed)).run_content_qa(
        org_id=org, actor_id=actor, asset_version=asset, source_text=source, rights_versions=[expired],
        market="US", locale="en-US", ai_generated=True, advertising_required=True,
        idempotency_key="content-fail", evaluated_at="2026-09-20T12:00:00Z",
    )
    assert report["status"] == "failed"
    codes = {item["code"] for item in report["findings"]}
    assert {"MEDIA_NUMBER_MISMATCH", "MEDIA_CODE_MISMATCH", "MEDIA_VERSION_MISMATCH", "AI_LABEL_MISSING", "AD_DISCLOSURE_MISSING", "RIGHTS_NOT_ALLOWED"} <= codes


def test_content_rights_qa_unknown_extraction_needs_review_and_tenant_isolation() -> None:
    org, actor, asset, rights, source = _fixture()
    service = MediaContentRightsQAService()
    report = service.run_content_qa(
        org_id=org, actor_id=actor, asset_version=asset, source_text=source, rights_versions=[rights],
        market="US", locale="en-US", idempotency_key="content-review", evaluated_at="2026-09-20T12:00:00Z",
    )
    assert report["status"] == "needs_review"
    assert any(item["code"] == "TEXT_EXTRACTION_UNAVAILABLE" for item in report["findings"])
    foreign = {**rights, "org_id": str(uuid4())}
    with pytest.raises(MediaContentQAError) as error:
        service.run_content_qa(org_id=org, actor_id=actor, asset_version=asset, source_text=source,
                               rights_versions=[foreign], idempotency_key="foreign")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_content_rights_qa_expected_version_is_checked_before_write() -> None:
    org, actor, asset, rights, source = _fixture()
    service = MediaContentRightsQAService(extractor=FakeTextExtractionPort(text=source))
    with pytest.raises(MediaContentQAError) as error:
        service.run_content_qa(org_id=org, actor_id=actor, asset_version=asset, source_text=source,
                               rights_versions=[rights], expected_version=1, idempotency_key="stale")
    assert error.value.code == "VERSION_CONFLICT"
    assert service.store.reports == {}
