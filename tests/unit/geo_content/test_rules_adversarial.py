from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.geo_content import GeoContentError, GeoContentRuleService


STAMP = "2026-09-19T12:00:00Z"


def _fixture() -> dict[str, object]:
    org, actor, page_id, canonical_id, entity_id, claim_id, evidence_id, source_id, rights_id = (
        str(uuid4()) for _ in range(9)
    )
    return {
        "org": org,
        "actor": actor,
        "page": {
            "id": page_id,
            "org_id": org,
            "status": "published",
            "title": "Acme guide",
            "locale": "en-US",
            "base_origin": "https://example.test",
            "canonical_url": "https://example.test/guides/acme",
            "canonical_content_version_id": canonical_id,
            "visible_content": {"blocks": [{"text": "Acme guide explains the product."}]},
            "entity_ids": [entity_id],
        },
        "canonical": {"id": canonical_id, "org_id": org, "freshness_status": "fresh"},
        "entities": [{"id": entity_id, "org_id": org, "canonical_name": "Acme", "aliases": [], "status": "active"}],
        "claims": [{
            "id": claim_id,
            "org_id": org,
            "entity_ids": [entity_id],
            "status": "verified",
            "freshness_status": "fresh",
            "evidence_ids": [evidence_id],
        }],
        "evidences": [{
            "id": evidence_id,
            "org_id": org,
            "claim_id": claim_id,
            "source_snapshot_id": source_id,
            "rights_record_version_id": rights_id,
            "status": "valid",
            "quote": "Acme",
            "locator": "paragraph:1",
        }],
        "snapshots": [{"id": source_id, "org_id": org, "source_id": str(uuid4()), "captured_at": "2026-09-01T00:00:00Z", "content_hash": "a" * 64, "storage_object_ref": f"private://{source_id}", "status": "usable"}],
        "rights": [{"id": rights_id, "org_id": org, "source_snapshot_ids": [source_id], "rights_holder": "Example", "policy_rule_version": "rights-v1", "snapshot_hash": "b" * 64, "status": "verified", "permitted_use": "commercial", "verified_by": actor, "verified_at": "2026-09-01T00:00:00Z"}],
    }


def _service() -> GeoContentRuleService:
    return GeoContentRuleService(clock=lambda: datetime(2026, 9, 19, 12, tzinfo=timezone.utc))


def _assess(service: GeoContentRuleService, fixture: dict[str, object], **kwargs):
    return service.assess(
        org_id=fixture["org"],
        actor_id=fixture["actor"],
        trace_id="geo-test",
        idempotency_key=kwargs.pop("idempotency_key", "geo-1"),
        page=fixture["page"],
        canonical=fixture["canonical"],
        entities=fixture["entities"],
        claims=fixture["claims"],
        evidences=fixture["evidences"],
        source_snapshots=fixture["snapshots"],
        rights_record_versions=fixture["rights"],
        **kwargs,
    )


def test_complete_trace_is_pass_and_contract_ready() -> None:
    fixture = _fixture()
    result = _assess(_service(), fixture)
    assert result["status"] == "pass"
    assert result["eligible_for_crawl"] is True
    assert result["eligible_for_citation"] is True
    assert result["dimensions"]["claim_traceability"]["status"] == "pass"


def test_empty_knowledge_inputs_never_claim_citation_readiness() -> None:
    fixture = _fixture()
    fixture["page"]["entity_ids"] = []
    result = _service().assess(
        org_id=fixture["org"], actor_id=fixture["actor"], trace_id="geo-test", idempotency_key="empty",
        page=fixture["page"], canonical=fixture["canonical"],
    )
    assert result["status"] == "review"
    assert result["eligible_for_crawl"] is True
    assert result["eligible_for_citation"] is False
    codes = {item["code"] for item in result["findings"]}
    assert {"CLAIMS_MISSING", "EVIDENCE_MISSING"} <= codes


def test_missing_provenance_status_and_orphan_evidence_fail_citation() -> None:
    fixture = _fixture()
    fixture["claims"][0].pop("status")
    fixture["evidences"][0]["claim_id"] = str(uuid4())
    fixture["rights"][0].pop("status")
    result = _assess(_service(), fixture, idempotency_key="missing-status")
    assert result["status"] == "fail"
    assert result["eligible_for_citation"] is False
    codes = {item["code"] for item in result["findings"]}
    assert {"CLAIM_STATUS_MISSING", "RIGHTS_STATUS_MISSING", "EVIDENCE_CLAIM_MISMATCH"} <= codes


def test_review_due_freshness_requires_citation_review() -> None:
    fixture = _fixture()
    fixture["claims"][0]["freshness_status"] = "review_due"
    result = _assess(_service(), fixture, idempotency_key="review-due")
    assert result["status"] == "review"
    assert result["eligible_for_citation"] is False


def test_policy_and_records_are_tenant_scoped() -> None:
    fixture = _fixture()
    with pytest.raises(GeoContentError) as error:
        _assess(_service(), fixture, idempotency_key="foreign-policy", policy_snapshot={"org_id": str(uuid4())})
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    foreign = _fixture()
    fixture["entities"][0]["org_id"] = foreign["org"]
    with pytest.raises(GeoContentError) as error:
        _assess(_service(), fixture, idempotency_key="foreign-record")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


@pytest.mark.parametrize("url", [
    "https://example.test/a//b",
    "https://example.test/a/../b",
    "https://example.test/a/./b",
    "https://example.test/a%GG",
])
def test_noncanonical_absolute_urls_are_not_crawlable(url: str) -> None:
    fixture = _fixture()
    fixture["page"]["canonical_url"] = url
    result = _assess(_service(), fixture, idempotency_key="url-" + str(abs(hash(url))))
    assert result["dimensions"]["crawlability"]["status"] == "fail"
    assert "CANONICAL_URL_INVALID" in result["dimensions"]["crawlability"]["finding_codes"]


def test_idempotency_replay_is_stable_and_conflict_is_rejected() -> None:
    fixture = _fixture()
    service = _service()
    first = _assess(service, fixture, idempotency_key="same")
    assert _assess(service, fixture, idempotency_key="same") == first
    fixture["page"]["title"] = "Changed"
    with pytest.raises(GeoContentError) as error:
        _assess(service, fixture, idempotency_key="same")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_canonical_origin_and_path_must_match_the_page() -> None:
    fixture = _fixture()
    fixture["page"]["base_origin"] = "https://example.test"
    fixture["page"]["canonical_url"] = "https://evil.test/guides/acme"
    result = _assess(_service(), fixture, idempotency_key="cross-origin")
    codes = set(result["dimensions"]["crawlability"]["finding_codes"])
    assert "CANONICAL_ORIGIN_MISMATCH" in codes
    fixture = _fixture()
    fixture["page"]["base_origin"] = "https://example.test"
    fixture["page"]["url_path"] = "/guides/other"
    fixture["page"]["canonical_url"] = "/guides/acme"
    result = _assess(_service(), fixture, idempotency_key="path-mismatch")
    assert "CANONICAL_URL_MISMATCH" in set(result["dimensions"]["crawlability"]["finding_codes"])


def test_absolute_canonical_requires_an_explicit_origin() -> None:
    fixture = _fixture()
    fixture["page"].pop("base_origin")
    result = _assess(_service(), fixture, idempotency_key="absolute-origin-missing")
    codes = set(result["dimensions"]["crawlability"]["finding_codes"])
    assert "CANONICAL_ORIGIN_MISSING" in codes
    assert result["eligible_for_crawl"] is False


def test_relative_canonical_without_origin_is_not_crawlable() -> None:
    fixture = _fixture()
    fixture["page"].pop("base_origin")
    fixture["page"].pop("canonical_url")
    fixture["page"]["url_path"] = "/guides/acme"
    result = _assess(_service(), fixture, idempotency_key="origin-missing")
    assert "CANONICAL_ORIGIN_MISSING" in set(result["dimensions"]["crawlability"]["finding_codes"])
    assert result["eligible_for_crawl"] is False


def test_entity_name_matching_does_not_accept_word_substrings() -> None:
    fixture = _fixture()
    fixture["page"]["visible_content"] = {"blocks": [{"text": "The acmeatic example is unrelated."}]}
    result = _assess(_service(), fixture, idempotency_key="entity-boundary")
    assert "ENTITY_NOT_VISIBLE" in set(result["dimensions"]["entity_consistency"]["finding_codes"])


def test_entity_declaration_empty_or_null_is_not_silently_accepted() -> None:
    fixture = _fixture()
    fixture["page"]["entity_ids"] = []
    result = _assess(_service(), fixture, idempotency_key="entity-empty")
    assert "ENTITY_DECLARATION_EMPTY" in set(result["dimensions"]["entity_consistency"]["finding_codes"])
    fixture = _fixture()
    fixture["page"]["entity_ids"] = [None]
    result = _assess(_service(), fixture, idempotency_key="entity-null")
    assert "ENTITY_DECLARATION_INVALID" in set(result["dimensions"]["entity_consistency"]["finding_codes"])


def test_single_character_alias_is_a_valid_visibility_match() -> None:
    fixture = _fixture()
    fixture["entities"][0]["aliases"] = ["A"]
    fixture["page"]["visible_content"] = {"blocks": [{"text": "A guide explains the product."}]}
    result = _assess(_service(), fixture, idempotency_key="single-alias")
    assert "ENTITY_NOT_VISIBLE" not in set(result["dimensions"]["entity_consistency"]["finding_codes"])


def test_incomplete_or_expired_snapshot_cannot_be_citation_ready() -> None:
    fixture = _fixture()
    fixture["snapshots"][0].pop("content_hash")
    result = _assess(_service(), fixture, idempotency_key="snapshot-incomplete")
    assert "SOURCE_SNAPSHOT_INCOMPLETE" in set(result["dimensions"]["citation_readiness"]["finding_codes"])
    fixture = _fixture()
    fixture["snapshots"][0]["valid_to"] = "2026-01-01T00:00:00Z"
    result = _assess(_service(), fixture, idempotency_key="snapshot-expired")
    assert result["eligible_for_citation"] is False
    assert "FRESHNESS_EXPIRED" in set(result["dimensions"]["freshness"]["finding_codes"])


def test_claim_evidence_and_rights_source_links_are_bidirectional() -> None:
    fixture = _fixture()
    fixture["claims"][0]["evidence_ids"] = []
    result = _assess(_service(), fixture, idempotency_key="claim-reverse")
    assert "CLAIM_EVIDENCE_MISMATCH" in set(result["dimensions"]["claim_traceability"]["finding_codes"])
    fixture = _fixture()
    fixture["rights"][0]["source_snapshot_ids"] = [str(uuid4())]
    result = _assess(_service(), fixture, idempotency_key="rights-source")
    assert "RIGHTS_SOURCE_MISMATCH" in set(result["dimensions"]["citation_readiness"]["finding_codes"])


def test_scope_mismatch_and_unsupported_aliases_are_blocked() -> None:
    fixture = _fixture()
    fixture["claims"][0]["applicable_locales"] = ["fr-FR"]
    result = _assess(_service(), fixture, idempotency_key="claim-scope")
    assert "CLAIM_SCOPE_MISMATCH" in set(result["dimensions"]["claim_traceability"]["finding_codes"])
    fixture = _fixture()
    fixture["evidences"][0].pop("source_snapshot_id")
    fixture["evidences"][0]["source_id"] = fixture["snapshots"][0]["id"]
    result = _assess(_service(), fixture, idempotency_key="source-alias")
    assert "SOURCE_SNAPSHOT_MISSING" in set(result["dimensions"]["citation_readiness"]["finding_codes"])


def test_source_root_requires_current_snapshot_and_singular_alias_is_rejected() -> None:
    fixture = _fixture()
    source_id = fixture["snapshots"][0]["source_id"]
    fixture["source_rows"] = [{"id": source_id, "org_id": fixture["org"], "status": "usable"}]
    result = _assess(_service(), fixture, idempotency_key="source-current-missing", sources=fixture["source_rows"])
    assert "SOURCE_CURRENT_SNAPSHOT_MISSING" in set(result["dimensions"]["citation_readiness"]["finding_codes"])
    with pytest.raises(GeoContentError) as error:
        _assess(_service(), fixture, idempotency_key="source-singular", predecessor_artifacts={"source": {"id": source_id, "org_id": fixture["org"]}})
    assert error.value.code == "UNSUPPORTED_GEO_CONTENT_ALIAS"


def test_invalid_policy_and_org_are_rejected_and_audited() -> None:
    fixture = _fixture()
    service = _service()
    with pytest.raises(GeoContentError) as policy_error:
        _assess(service, fixture, idempotency_key="policy-list", policy_snapshot=[])
    assert policy_error.value.code == "INVALID_GEO_CONTENT_INPUT"
    with pytest.raises(GeoContentError) as org_error:
        service.assess(org_id="not-a-uuid", actor_id=fixture["actor"], trace_id="geo-test", idempotency_key="bad-org")
    assert org_error.value.code == "INVALID_TENANT_CONTEXT"
    assert service.audit[-1]["event_type"] == "geo_content.assessment.rejected"


def test_rejection_paths_are_audited_and_assessed_at_is_idempotent_input() -> None:
    fixture = _fixture()
    service = _service()
    with pytest.raises(GeoContentError):
        _assess(service, fixture, idempotency_key="audit-policy", policy_snapshot={"org_id": str(uuid4())})
    assert service.audit[-1]["event_type"] == "geo_content.assessment.rejected"
    first = service.assess(
        org_id=fixture["org"], actor_id=fixture["actor"], trace_id="geo-test", idempotency_key="time-key",
        page=fixture["page"], canonical=fixture["canonical"], entities=fixture["entities"], claims=fixture["claims"],
        evidences=fixture["evidences"], source_snapshots=fixture["snapshots"], rights_record_versions=fixture["rights"], assessed_at=STAMP,
    )
    with pytest.raises(GeoContentError) as error:
        service.assess(
            org_id=fixture["org"], actor_id=fixture["actor"], trace_id="geo-test", idempotency_key="time-key",
            page=fixture["page"], canonical=fixture["canonical"], entities=fixture["entities"], claims=fixture["claims"],
            evidences=fixture["evidences"], source_snapshots=fixture["snapshots"], rights_record_versions=fixture["rights"], assessed_at="2026-09-20T12:00:00Z",
        )
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert first["assessed_at"] == STAMP
