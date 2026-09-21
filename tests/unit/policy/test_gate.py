from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
import yaml

from modules.policy import PolicyGateService
from modules.policy.gate import QAError


STAMP = "2026-09-19T00:00:00Z"
ROOT = Path(__file__).resolve().parents[3]


def _snapshot(tenant: str, subject: str) -> dict:
    value = yaml.safe_load((ROOT / "docs/governance/policy-snapshot-synthetic-v1.yaml").read_text(encoding="utf-8"))
    value["id"], value["org_id"], value["subject_id"] = str(uuid4()), tenant, subject
    value["input_hash"], value["rules_hash"], value["snapshot_hash"] = "0" * 64, "1" * 64, "2" * 64
    value["created_by"] = str(uuid4())
    return value


def _allow_context() -> dict:
    return {
        "risk_level": "R0", "qa_status": "passed", "rights_allowed": True, "region_decision": "allow",
        "release_level": "architecture_mvp", "release_mode": "manual_export", "account_state": "not_required",
        "data_processing_allowed": True, "model_allowed": True,
    }


def test_policy_gate_allows_safe_mvp_and_emits_contract_decision() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    service = PolicyGateService()
    decision = service.evaluate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="allow-1",
        subject_type="variant", subject_id=subject, policy_snapshot=_snapshot(tenant, subject),
        context=_allow_context(), evaluated_at=STAMP,
    )
    assert decision["final_decision"] == "allow"
    assert decision["distribution_policy"] == "allow"
    schema = json.loads((ROOT / "packages/contracts/jsonschema/policy-decision.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(decision)


def test_policy_gate_denies_high_risk_rights_region_and_real_mvp_mode() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    context = {**_allow_context(), "risk_level": "R3", "qa_status": "failed", "rights_allowed": False,
               "region_decision": "deny", "release_mode": "authorized_api"}
    decision = PolicyGateService().evaluate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="deny-1",
        subject_type="variant", subject_id=subject, policy_snapshot=_snapshot(tenant, subject),
        context=context, evaluated_at=STAMP,
    )
    assert decision["final_decision"] == "deny"
    assert {"RISK_R3_BLOCKED", "QA_FAILED", "RIGHTS_DENIED", "REGION_DENIED", "RELEASE_MODE_NOT_ALLOWED"} <= set(decision["reasons"])


def test_policy_gate_unknowns_review_and_expired_snapshot_denies() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    review = _snapshot(tenant, subject)
    review["review_due_at"] = "2026-09-18T00:00:00Z"
    decision = PolicyGateService().evaluate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="review-1",
        subject_type="variant", subject_id=subject, policy_snapshot=review,
        context={"risk_level": "unknown", "release_mode": "manual_export"}, evaluated_at=STAMP,
    )
    assert decision["final_decision"] == "manual_review"
    assert {"POLICY_SNAPSHOT_REVIEW_DUE", "RISK_LEVEL_UNKNOWN", "QA_REVIEW_REQUIRED", "ACCOUNT_UNKNOWN"} <= set(decision["reasons"])
    expired = _snapshot(tenant, subject)
    expired["expires_at"] = "2026-09-18T00:00:00Z"
    denied = PolicyGateService().evaluate(
        org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="expired-1",
        subject_type="variant", subject_id=subject, policy_snapshot=expired,
        context=_allow_context(), evaluated_at=STAMP,
    )
    assert denied["final_decision"] == "deny"
    assert "POLICY_SNAPSHOT_EXPIRED" in denied["reasons"]


def test_policy_gate_idempotency_and_tenant_scope() -> None:
    tenant, actor, subject = str(uuid4()), str(uuid4()), str(uuid4())
    service = PolicyGateService()
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="same-1",
                subject_type="variant", subject_id=subject, policy_snapshot=_snapshot(tenant, subject),
                context=_allow_context(), evaluated_at=STAMP)
    first = service.evaluate(**args)
    assert service.evaluate(**args) == first
    with pytest.raises(QAError) as error:
        service.evaluate(**{**args, "context": {**_allow_context(), "release_mode": "simulation"}})
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    foreign = _snapshot(str(uuid4()), subject)
    with pytest.raises(QAError) as error:
        service.evaluate(**{**args, "policy_snapshot": foreign, "idempotency_key": "foreign-1"})
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
