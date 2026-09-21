from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.qa import AdvancedQAService, QAError

from .test_service import STAMP, _fixture


def _rights(tenant: str, actor: str, *, status: str = "verified") -> dict:
    return {
        "id": str(uuid4()), "org_id": tenant, "rights_record_id": str(uuid4()), "version_no": 1,
        "source_snapshot_ids": [str(uuid4())], "license_ref": "license:test", "contract_ref": None,
        "evidence_object_refs": [], "terms_snapshot_hash": "a" * 64, "rights_holder": "Holder",
        "permitted_regions": ["US"], "permitted_locales": ["en-US"], "permitted_media": ["text"],
        "permitted_use": "commercial", "valid_from": None, "valid_to": None, "status": status,
        "policy_rule_version": "rights-v1", "verified_by": actor if status == "verified" else None,
        "verified_at": STAMP if status == "verified" else None,
        "verification_reason": "checked" if status == "verified" else None, "supersedes_version_id": None,
        "snapshot_hash": "b" * 64, "created_by": actor, "created_at": STAMP,
    }


def test_advanced_qa_passes_with_threshold_and_allowed_rights() -> None:
    tenant, actor, canonical, variant, *_ = _fixture()
    report = AdvancedQAService().check_variant(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="pass-2",
        variant_version=variant, canonical_version=canonical, rights_versions=[_rights(tenant, actor)],
        rights_required=True, min_similarity=0.8, evaluated_at=STAMP,
    )
    assert report["status"] == "passed"
    assert report["findings"] == []
    schema = json.loads((Path(__file__).resolve().parents[3] /
                         "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(report)


def test_advanced_qa_reports_similarity_duplicate_blocks_disclosures_and_rights() -> None:
    tenant, actor, canonical, variant, *_ = _fixture()
    variant["body"]["blocks"].append({**variant["body"]["blocks"][0], "block_id": "duplicate"})
    variant["body"]["blocks"][0]["localized_text"] = "Different copy with no retained source tokens."
    variant["body"]["blocks"][1]["localized_text"] = variant["body"]["blocks"][0]["localized_text"]
    existing = deepcopy(variant)
    existing["id"] = str(uuid4())
    existing["content_variant_id"] = str(uuid4())
    report = AdvancedQAService().check_variant(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="fail-2",
        variant_version=variant, canonical_version=canonical, existing_variants=[existing],
        rights_versions=[_rights(tenant, actor, status="expired")], ai_generated=True,
        advertising_required=True, required_ad_disclosure="Sponsored", rights_required=True,
        min_similarity=0.8, evaluated_at=STAMP,
    )
    assert report["status"] == "failed"
    codes = {item["code"] for item in report["findings"]}
    assert {"SIMILARITY_TOO_LOW", "DUPLICATE_VARIANT", "DUPLICATE_BLOCK", "AI_LABEL_MISSING",
            "AD_DISCLOSURE_MISSING", "RIGHTS_NOT_ALLOWED"} <= codes


class BrokenSimilarity:
    def score(self, **kwargs):
        raise RuntimeError("offline")


def test_advanced_qa_port_failure_is_review_and_idempotency_is_scoped() -> None:
    tenant, actor, canonical, variant, *_ = _fixture()
    service = AdvancedQAService(similarity_port=BrokenSimilarity())
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="same-2",
                variant_version=variant, canonical_version=canonical, min_similarity=0.8, evaluated_at=STAMP)
    first = service.check_variant(**args)
    assert first["status"] == "needs_review"
    assert any(item["code"] == "SIMILARITY_CHECK_ERROR" for item in first["findings"])
    assert service.check_variant(**args) == first
    with pytest.raises(QAError) as error:
        service.check_variant(**{**args, "min_similarity": 0.1})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    foreign = {**variant, "org_id": str(uuid4())}
    with pytest.raises(QAError) as error:
        service.check_variant(**{**args, "existing_variants": [foreign], "idempotency_key": "foreign-2"})
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
