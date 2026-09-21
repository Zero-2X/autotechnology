from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "apps" / "knowledge-site" / "scripts" / "site_structured_data.py"
SPEC = importlib.util.spec_from_file_location("knowledge_site_site_structured_data", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
site_jsonld = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(site_jsonld)

ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"
PAGE_VERSION = "44444444-4444-4444-8444-444444444444"
STAMP = "2026-09-19T12:00:00Z"


def _page(*, status: str = "published", org_id: str = ORG, path: str = "/guides/structured", technical: bool = False) -> dict:
    return {
        "id": PAGE_VERSION,
        "org_id": org_id,
        "site_page_id": "55555555-5555-4555-8555-555555555555",
        "page_key": "guides/structured",
        "version_no": 1,
        "locale": "en-US",
        "url_path": path,
        "canonical_url": path,
        "status": status,
        "title": "Structured <Guide>",
        "summary": "A & useful summary",
        "author": {"id": ACTOR, "name": "A <Writer>", "url": None},
        "reviewer": {"id": "reviewer-1", "name": "Reviewer", "url": None},
        "updated_at": STAMP,
        "published_at": STAMP,
        "methodology": {"summary": "Check", "steps": ["Read", "Check"]},
        "limitations": ["Limited"],
        "faq": [{"question": "Q?", "answer": "A & B"}],
        "visible_content": {"blocks": [{"key": "intro", "type": "paragraph", "text": "Body </script> & text"}]},
        "snapshot_hash": "a" * 64,
        "is_technical": technical,
    }


def _service() -> site_jsonld.SiteStructuredDataService:
    return site_jsonld.SiteStructuredDataService(clock=lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc))


def test_generates_visible_content_graph_and_contract() -> None:
    result = _service().generate(
        page_version=_page(), base_origin="HTTPS://Example.COM/",
        tenant_context={"org_id": ORG, "actor_id": ACTOR, "trace_id": "trace-003"},
        organization={"name": "Example Org"}, idempotency_key="jsonld-1",
    )
    schema = json.loads((ROOT / "packages/contracts/jsonschema/site-structured-data.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    assert result["canonical_url"] == "https://example.com/guides/structured"
    graph = result["jsonld"]["@graph"]
    types = [node["@type"] for node in graph]
    assert "Article" in types and "Organization" in types and types.count("Person") == 2
    article = next(node for node in graph if node["@type"] == "Article")
    assert "Body </script> & text" in article["articleBody"]
    assert result["script"].count("</script>") == 1
    assert "\\u003c" in result["jsonld_text"]
    assert result["video_included"] is False


def test_tech_article_and_video_require_phase_six_approval() -> None:
    service = _service()
    asset = {
        "id": "video-1", "org_id": ORG, "type": "video", "phase": 6,
        "status": "approved", "contentUrl": "https://cdn.example.com/video.mp4",
        "uploadDate": STAMP, "name": "Guide video",
    }
    before = service.generate(page_version=_page(technical=True), base_origin="https://example.com", phase=5, video_asset=asset)
    assert before["article_type"] == "TechArticle"
    assert before["video_included"] is False
    after = service.generate(page_version=_page(technical=True), base_origin="https://example.com", phase=6, video_asset=asset)
    assert after["video_included"] is True
    assert any(node["@type"] == "VideoObject" for node in after["jsonld"]["@graph"])
    blocked = service.generate(page_version=_page(), base_origin="https://example.com", phase=6, video_asset={**asset, "status": "draft"})
    assert blocked["video_included"] is False


def test_tenant_and_publication_state_are_checked_without_leaking_content() -> None:
    service = _service()
    with pytest.raises(site_jsonld.StructuredDataError) as foreign:
        service.generate(page_version=_page(org_id=OTHER_ORG), org_id=ORG, base_origin="https://example.com")
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"
    assert "Structured" not in str(foreign.value)
    with pytest.raises(site_jsonld.StructuredDataError) as draft:
        service.generate(page_version=_page(status="draft"), base_origin="https://example.com")
    assert draft.value.code == "PAGE_NOT_RENDERABLE"
    assert service.audit_for(org_id=ORG)[-1]["status"] == "rejected"


def test_idempotency_replay_is_stable_and_conflict_is_rejected() -> None:
    service = _service()
    kwargs = {"page_version": _page(), "base_origin": "https://example.com", "idempotency_key": "same-key"}
    first = service.generate(**kwargs)
    replay = service.generate(**kwargs)
    assert replay == first
    with pytest.raises(site_jsonld.StructuredDataError) as reused:
        service.generate(**{**kwargs, "article_type": "TechArticle"})
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert len([row for row in service.audit_for(org_id=ORG) if row["status"] == "succeeded"]) == 1


def test_invalid_canonical_and_video_tenant_are_rejected() -> None:
    service = _service()
    with pytest.raises(site_jsonld.StructuredDataError) as canonical:
        service.generate(page_version=_page(path="/guides/structured?x=1"), base_origin="https://example.com")
    assert canonical.value.code in {"INVALID_CANONICAL_URL", "CANONICAL_URL_MISMATCH"}
    with pytest.raises(site_jsonld.StructuredDataError) as video:
        service.generate(
            page_version=_page(), base_origin="https://example.com", phase=6,
            video_asset={"org_id": OTHER_ORG, "status": "approved", "phase": 6, "contentUrl": "https://cdn.example.com/a.mp4", "uploadDate": STAMP},
        )
    assert video.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(site_jsonld.StructuredDataError) as unscoped_video:
        service.generate(
            page_version=_page(), base_origin="https://example.com", phase=6,
            video_asset={"status": "approved", "phase": 6, "contentUrl": "https://cdn.example.com/a.mp4", "uploadDate": STAMP},
        )
    assert unscoped_video.value.code == "INVALID_VIDEO_ASSET"


def test_invalid_source_hash_and_empty_visible_body_are_rejected() -> None:
    service = _service()
    invalid_hash = _page()
    invalid_hash["snapshot_hash"] = "not-a-sha256"
    with pytest.raises(site_jsonld.StructuredDataError) as snapshot:
        service.generate(page_version=invalid_hash, base_origin="https://example.com")
    assert snapshot.value.code == "INVALID_SNAPSHOT_HASH"

    empty = _page()
    empty["visible_content"] = {"blocks": []}
    empty["methodology"] = {"summary": "", "steps": []}
    empty["limitations"] = []
    empty["faq"] = []
    with pytest.raises(site_jsonld.StructuredDataError) as body:
        service.generate(page_version=empty, base_origin="https://example.com")
    assert body.value.code == "VISIBLE_CONTENT_REQUIRED"
