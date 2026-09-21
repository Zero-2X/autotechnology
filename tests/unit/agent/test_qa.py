from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from modules.agent import AgentError, QAAgent, QAModelRequest
from modules.agent.qa import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider


class Checker:
    def __init__(self, tenant, variant_id, canonical_id, status="failed") -> None:
        self.tenant, self.variant_id, self.canonical_id, self.status = tenant, variant_id, canonical_id, status
        self.calls = 0
        self.report = {
            "id": str(uuid4()), "org_id": str(tenant), "subject_type": "variant_version",
            "subject_id": str(variant_id), "rule_version": "qa-001/v1", "status": status,
            "findings": [{"code": "MISSING_NUMBER", "severity": "error", "path": "/body/number",
                           "message": "number token is missing", "observed": 0, "expected": 1}],
            "created_at": "2026-09-19T00:00:00Z",
        }

    def check_variant(self, **kwargs):
        self.calls += 1
        return deepcopy(self.report)


def _setup(status="failed"):
    tenant, actor, request_id, variant_id, canonical_id = (uuid4() for _ in range(5))
    checker = Checker(tenant, variant_id, canonical_id, status=status)
    if status == "passed":
        checker.report["findings"] = []
    variant = {"id": str(variant_id), "org_id": str(tenant), "canonical_content_version_id": str(canonical_id),
               "snapshot_hash": "a" * 64}
    canonical = {"id": str(canonical_id), "org_id": str(tenant), "content_hash": "b" * 64}
    subject = {"variant_version_id": str(variant_id), "canonical_content_version_id": str(canonical_id),
               "variant_snapshot_hash": "a" * 64, "canonical_content_hash": "b" * 64}
    report_input = {"id": checker.report["id"], "rule_version": checker.report["rule_version"],
                    "status": status, "findings": checker.report["findings"]}
    values = {"qa_request_id": str(request_id), "subject": subject, "qa_report": report_input, "tool_calls": []}
    findings = []
    if checker.report["findings"]:
        finding = checker.report["findings"][0]
        findings = [{"finding_key": "finding_0", "source_finding_index": 0,
                     "code": finding["code"], "severity": finding["severity"], "path": finding["path"],
                     "explanation": "The number required by the source is absent.",
                     "observed": finding["observed"], "expected": finding["expected"]}]
    output = {"findings": findings,
              "human_tasks": [] if status == "passed" else [{"task_key": "review_0", "task_type": "qa_review",
                             "priority": "high", "reason": "Review the missing number before approval.",
                             "finding_keys": ["finding_0"]}],
              "summary": "QA requires review.", "needs_review": True, "decision": "review_only",
              "approved": False, "published": False}
    request = QAModelRequest("fake", "qa/v1", values, OUTPUT_REF, 2500, 30, "trace", str(tenant))
    provider = FakeModelProvider(fixtures={request.request_hash: output}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    agent = QAAgent(qa_checker=checker, model_port=provider)
    args = dict(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="qa",
                qa_request_id=request_id, variant_version=variant, canonical_version=canonical,
                claims=[], evidence=[], source_map=[])
    return agent, checker, provider, args


def test_qa_agent_explains_findings_proposes_task_and_never_approves_or_publishes() -> None:
    agent, checker, provider, args = _setup()
    result = agent.review(**args)
    assert result["status"] == "needs_review" and result["needs_review"] is True
    assert result["decision"] == "review_only" and result["approved"] is False and result["published"] is False
    assert result["human_tasks"][0]["task_type"] == "qa_review"
    assert result["approval_created"] is False and result["publication_side_effect"] is False
    assert provider.call_count == checker.calls == 1
    assert len(agent.ledger.agent_runs) == len(agent.ledger.model_calls) == 1
    replay = agent.review(**args)
    assert replay["findings"][0]["code"] == "MISSING_NUMBER"
    assert provider.call_count == checker.calls == 1


def test_qa_agent_rejects_cross_tenant_or_mismatched_report_before_model() -> None:
    agent, checker, provider, args = _setup()
    args["variant_version"]["org_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        agent.review(**args)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    args["variant_version"]["org_id"] = str(args["org_id"])
    checker.report["subject_id"] = str(uuid4())
    with pytest.raises(AgentError) as error:
        agent.review(**args)
    assert error.value.code == "QA_AGENT_REPORT_INVALID"
    assert provider.call_count == 0


def test_qa_agent_rejects_finding_drift_unknown_task_and_approval_fields() -> None:
    agent, checker, provider, args = _setup()
    fixture = next(iter(provider.fixtures.values()))
    fixture["approved"] = True
    with pytest.raises(ValueError) as error:
        agent.review(**args)
    assert getattr(error.value, "code", None) == "MODEL_OUTPUT_SCHEMA_INVALID"
    fixture["approved"] = False
    fixture["findings"][0]["code"] = "ADDED_NUMBER"
    with pytest.raises(AgentError) as error:
        agent.review(**args)
    assert error.value.code == "QA_AGENT_FINDING_DRIFT"
    fixture["findings"][0]["code"] = "MISSING_NUMBER"
    fixture["human_tasks"][0]["finding_keys"] = ["unknown"]
    with pytest.raises(AgentError) as error:
        agent.review(**args)
    assert error.value.code == "QA_AGENT_TASK_REFERENCE"


def test_qa_agent_passed_report_cannot_create_human_task() -> None:
    agent, checker, provider, args = _setup(status="passed")
    fixture = next(iter(provider.fixtures.values()))
    fixture["findings"] = []
    fixture["human_tasks"] = []
    result = agent.review(**args)
    assert result["qa_report"]["status"] == "passed" and result["human_tasks"] == []
