from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.qa import QAError, QAService


STAMP = "2026-09-19T00:00:00Z"


def _fixture():
    tenant, actor, canonical_id, variant_id, claim_id, evidence_id, source_id = (str(uuid4()) for _ in range(7))
    text = "Claim has 20 ms latency; see https://example.test and `x=1`."
    canonical = {
        "id": canonical_id, "org_id": tenant, "canonical_content_id": str(uuid4()),
        "version_no": 1, "status": "approved", "freshness_status": "fresh",
        "title": "Latency", "abstract": "", "sections": [{"key": "intro", "position": 1, "content": text}],
        "claims": [], "code_blocks": [], "created_at": STAMP,
    }
    variant = {
        "id": variant_id, "org_id": tenant, "content_variant_id": str(uuid4()),
        "canonical_content_version_id": canonical_id, "version_no": 1, "locale": "en-US", "market": "US",
        "audience": "engineers", "tone": "neutral", "region_profile_version_id": str(uuid4()),
        "source_variant_version_id": None, "body": {"blocks": [{
            "block_id": "intro", "localized_text": text, "term_refs": [], "disclosure": None,
        }]}, "term_memory_version": "pending", "disclosure": None, "policy_snapshot_id": None,
        "status": "draft", "snapshot_hash": "b" * 64, "created_by": actor, "created_at": STAMP,
    }
    claim = {
        "id": claim_id, "org_id": tenant, "entity_ids": [], "statement": "Claim has 20 ms latency.",
        "fact_type": "performance.latency", "applicable_versions": [canonical_id],
        "applicable_regions": [], "applicable_locales": ["en-US"], "valid_from": None, "valid_to": None,
        "review_due_at": None, "supersedes_claim_id": None, "freshness_status": "fresh", "status": "verified",
        "version": 1, "content_hash": "c" * 64, "created_by": actor, "created_at": STAMP, "updated_at": STAMP,
    }
    evidence = {
        "id": evidence_id, "org_id": tenant, "source_snapshot_id": source_id, "claim_id": claim_id,
        "rights_record_version_id": None, "evidence_type": "source.quote", "quote": "20 ms latency",
        "locator": "p1", "applicable_versions": [canonical_id], "applicable_regions": [],
        "applicable_locales": ["en-US"], "valid_from": None, "valid_to": None, "review_due_at": None,
        "captured_at": STAMP, "status": "valid", "version": 1, "content_hash": "d" * 64,
        "created_by": actor, "created_at": STAMP,
    }
    return tenant, actor, canonical, variant, claim, evidence, {"block_id": "intro", "claim_id": claim_id}


class Terms:
    def check(self, **kwargs):
        return [{"code": "TERM_REVIEW", "severity": "warning", "path": "/body/blocks/0",
                 "message": "term needs human review", "observed": "pending", "expected": "approved"}]


def test_passing_report_covers_claim_evidence_and_protected_tokens() -> None:
    tenant, actor, canonical, variant, claim, evidence, source_map = _fixture()
    service = QAService()
    report = service.check_variant(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="pass",
        variant_version=variant, canonical_version=canonical, claims=[claim], evidence=[evidence],
        source_map=[source_map], evaluated_at=STAMP,
    )
    assert report["status"] == "passed"
    assert report["findings"] == []
    schema = json.loads((Path(__file__).resolve().parents[3] /
                         "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)
    assert service.audit[0]["status"] == "passed"


def test_stale_claim_missing_evidence_and_changed_numbers_links_and_code_fail() -> None:
    tenant, actor, canonical, variant, claim, evidence, source_map = _fixture()
    claim["freshness_status"] = "stale"
    variant["body"]["blocks"][0]["localized_text"] = "Claim has 30 ms latency; see https://other.test and `x=2`."
    service = QAService()
    report = service.check_variant(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="fail",
        variant_version=variant, canonical_version=canonical, claims=[claim], evidence=[], source_map=[],
        evaluated_at=STAMP,
    )
    assert report["status"] == "failed"
    codes = {item["code"] for item in report["findings"]}
    assert {"CLAIM_STALE", "CLAIM_EVIDENCE_MISSING", "CLAIM_NOT_MAPPED", "MISSING_NUMBER",
            "MISSING_URL", "MISSING_CODE", "ADDED_NUMBER", "ADDED_URL", "ADDED_CODE"} <= codes


def test_expired_evidence_and_terminology_review_are_reported() -> None:
    tenant, actor, canonical, variant, claim, evidence, source_map = _fixture()
    evidence["status"] = "expired"
    evidence["locator"] = None
    service = QAService(terminology_port=Terms())
    report = service.check_variant(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="review",
        variant_version=variant, canonical_version=canonical, claims=[claim], evidence=[evidence],
        source_map=[source_map], evaluated_at=STAMP,
    )
    assert report["status"] == "failed"
    assert {item["code"] for item in report["findings"]} >= {"EVIDENCE_NOT_VALID", "EVIDENCE_LOCATOR_MISSING", "TERM_REVIEW"}


def test_idempotency_and_tenant_scope_do_not_repeat_or_leak() -> None:
    tenant, actor, canonical, variant, claim, evidence, source_map = _fixture()
    service = QAService()
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="same",
                variant_version=variant, canonical_version=canonical, claims=[claim], evidence=[evidence],
                source_map=[source_map], evaluated_at=STAMP)
    first = service.check_variant(**args)
    assert service.check_variant(**args) == first
    with pytest.raises(QAError) as error:
        service.check_variant(**{**args, "variant_version": {**variant, "tone": "formal"}})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(QAError) as error:
        service.check_variant(**{**args, "org_id": str(uuid4())})
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    assert len(service.audit) == 1
