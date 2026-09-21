from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "modules" / "geo_content" / "service.py"
SPEC = importlib.util.spec_from_file_location("geo_content_service", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
geo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(geo)

ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
ACTOR = "33333333-3333-4333-8333-333333333333"
STAMP = "2026-09-19T12:00:00Z"


def _page(*, robots: str | None = None, canonical: str = "https://example.com/guides/alpha", entity_ids: list[str] | None = None) -> dict:
    value = {
        "id": "page-1",
        "org_id": ORG,
        "status": "published",
        "title": "Alpha Guide",
        "locale": "en-US",
        "base_origin": "https://example.com",
        "canonical_url": canonical,
        "canonical_content_version_id": "canonical-1",
        "entity_ids": entity_ids or ["entity-1"],
        "visible_content": {"blocks": [{"key": "intro", "type": "paragraph", "text": "Alpha is a useful guide."}]},
    }
    if robots is not None:
        value["robots"] = robots
    return value


def _records() -> dict[str, list[dict]]:
    return {
        "entities": [{"id": "entity-1", "org_id": ORG, "canonical_name": "Alpha", "aliases": ["A"], "status": "active"}],
        "claims": [{"id": "claim-1", "org_id": ORG, "entity_ids": ["entity-1"], "evidence_ids": ["evidence-1"], "status": "verified", "freshness_status": "fresh"}],
        "evidences": [{"id": "evidence-1", "org_id": ORG, "claim_id": "claim-1", "source_snapshot_id": "snapshot-1", "rights_record_version_id": "rights-1", "status": "valid", "quote": "Alpha is useful.", "locator": "section:intro"}],
        "source_snapshots": [{"id": "snapshot-1", "org_id": ORG, "source_id": "source-1", "captured_at": "2026-09-01T00:00:00Z", "content_hash": "a" * 64, "storage_object_ref": "private://snapshot-1", "status": "usable", "valid_to": "2026-12-01T00:00:00Z"}],
        "rights_record_versions": [{"id": "rights-1", "org_id": ORG, "source_snapshot_ids": ["snapshot-1"], "rights_holder": "Example", "policy_rule_version": "rights-v1", "snapshot_hash": "b" * 64, "status": "verified", "permitted_use": "commercial", "verified_by": ACTOR, "verified_at": "2026-09-01T00:00:00Z", "valid_to": "2026-12-01T00:00:00Z"}],
    }


def _service() -> geo.GeoContentRuleService:
    return geo.GeoContentRuleService(clock=lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc))


def _assess(service: geo.GeoContentRuleService, *, key: str = "assessment-1", page: dict | None = None, **changes):
    values = _records()
    values.update(changes)
    return service.assess(
        org_id=ORG, actor_id=ACTOR, trace_id="trace-geo-1", idempotency_key=key,
        page=page or _page(), canonical={"id": "canonical-1", "org_id": ORG, "freshness_status": "fresh"}, assessed_at=STAMP, **values,
    )


def test_assessment_is_schema_valid_and_hash_is_explicit() -> None:
    result = _assess(_service())
    schema = json.loads((ROOT / "packages/contracts/jsonschema/geo-content-assessment.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
    assert result["status"] == "pass"
    assert result["eligible_for_crawl"] is True
    assert result["eligible_for_citation"] is True
    material = {key: value for key, value in result.items() if key not in {"output_hash", "audit_evidence"}}
    expected = sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert result["output_hash"] == expected


def test_missing_lineage_and_robots_block_citation_and_crawl() -> None:
    service = _service()
    result = _assess(service, page=_page(robots="noindex"), claims=[{"id": "claim-1", "org_id": ORG, "entity_ids": ["entity-1"], "status": "verified", "freshness_status": "fresh"}], evidences=[])
    codes = {item["code"] for item in result["findings"]}
    assert result["status"] == "fail"
    assert result["eligible_for_citation"] is False
    assert {"CLAIM_NO_EVIDENCE", "EVIDENCE_MISSING", "ROBOTS_NOINDEX"}.issubset(codes)


def test_stale_source_and_unverified_rights_are_not_citation_ready() -> None:
    records = _records()
    records["claims"][0]["freshness_status"] = "stale"
    records["source_snapshots"][0].update(status="expired")
    records["rights_record_versions"][0].update(status="pending")
    result = _assess(_service(), **records)
    codes = {item["code"] for item in result["findings"]}
    assert result["status"] == "fail"
    assert {"CLAIM_NOT_CURRENT", "SOURCE_NOT_USABLE", "RIGHTS_NOT_VERIFIED"}.issubset(codes)


def test_tenant_scope_and_idempotency_conflicts_are_stable() -> None:
    service = _service()
    foreign = _page()
    foreign["org_id"] = OTHER_ORG
    with pytest.raises(geo.GeoContentError) as scope:
        _assess(service, page=foreign)
    assert scope.value.code == "TENANT_SCOPE_VIOLATION"
    first = _assess(service, key="same-key")
    replay = _assess(service, key="same-key")
    assert replay == first
    changed = _page(canonical="https://example.com/guides/changed")
    with pytest.raises(geo.GeoContentError) as reused:
        _assess(service, key="same-key", page=changed)
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_canonical_path_and_entity_visibility_are_checked() -> None:
    service = _service()
    result = _assess(service, page=_page(canonical="https://example.com/guides/../alpha"))
    assert "CANONICAL_URL_INVALID" in {item["code"] for item in result["findings"]}
    hidden = _page()
    hidden["visible_content"] = {"blocks": [{"key": "intro", "type": "paragraph", "text": "Unrelated text."}]}
    result = _assess(service, key="hidden", page=hidden)
    assert "ENTITY_NOT_VISIBLE" in {item["code"] for item in result["findings"]}


def test_missing_status_is_not_trusted_by_default() -> None:
    records = _records()
    for row in records["entities"] + records["claims"] + records["evidences"] + records["source_snapshots"] + records["rights_record_versions"]:
        row.pop("status", None)
    result = _assess(_service(), key="missing-status", **records)
    codes = {item["code"] for item in result["findings"]}
    assert result["eligible_for_citation"] is False
    assert {"ENTITY_STATUS_MISSING", "CLAIM_STATUS_MISSING", "EVIDENCE_STATUS_MISSING", "SOURCE_STATUS_MISSING", "RIGHTS_STATUS_MISSING"}.issubset(codes)
