from __future__ import annotations

from uuid import uuid4

from modules.agent import QAAgent, QAModelRequest
from modules.agent.qa import OUTPUT_REF, OUTPUT_SCHEMA
from modules.model_gateway import FakeModelProvider
from modules.qa import QAService


def test_qa_agent_uses_deterministic_report_and_returns_review_only_tasks() -> None:
    tenant, actor, variant_id, canonical_id, request_id = (uuid4() for _ in range(5))
    variant = {"id": str(variant_id), "org_id": str(tenant), "canonical_content_version_id": str(canonical_id),
               "snapshot_hash": "a" * 64, "status": "draft", "locale": "en-US", "blocks": []}
    canonical = {"id": str(canonical_id), "org_id": str(tenant), "content_hash": "b" * 64,
                 "status": "draft", "freshness_status": "fresh", "title": "Source", "sections": []}
    checker_service = QAService()
    report = checker_service.check_variant(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="qa:deterministic",
                                   variant_version=variant, canonical_version=canonical, claims=[], evidence=[], source_map=[])
    class FrozenChecker:
        def __init__(self, value):
            self.value = value
        def check_variant(self, **kwargs):
            return self.value
    checker = FrozenChecker(report)
    findings = []
    for index, finding in enumerate(report["findings"]):
        findings.append({"finding_key": f"finding_{index}", "source_finding_index": index,
                         "code": finding["code"], "severity": finding["severity"], "path": finding["path"],
                         "explanation": finding["message"], "observed": finding.get("observed"), "expected": finding.get("expected")})
    tasks = [{"task_key": "qa_review", "task_type": "qa_review", "priority": "high",
              "reason": "Deterministic QA findings require human review.",
              "finding_keys": [item["finding_key"] for item in findings]}] if findings else []
    values = {"qa_request_id": str(request_id), "subject": {"variant_version_id": str(variant_id),
              "canonical_content_version_id": str(canonical_id), "variant_snapshot_hash": "a" * 64,
              "canonical_content_hash": "b" * 64}, "qa_report": {"id": report["id"], "rule_version": report["rule_version"],
              "status": report["status"], "findings": report["findings"]}, "tool_calls": []}
    output = {"findings": findings, "human_tasks": tasks, "summary": "Deterministic QA requires review.",
              "needs_review": True, "decision": "review_only", "approved": False, "published": False}
    request = QAModelRequest("fake", "qa/v1", values, OUTPUT_REF, 2500, 30, "trace", str(tenant))
    provider = FakeModelProvider(fixtures={request.request_hash: output}, schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    agent = QAAgent(qa_checker=checker, model_port=provider)
    result = agent.review(org_id=tenant, actor_id=actor, trace_id="trace", idempotency_key="qa",
                          qa_request_id=request_id, variant_version=variant, canonical_version=canonical,
                          claims=[], evidence=[], source_map=[])
    assert result["decision"] == "review_only" and result["approved"] is False and result["published"] is False
    assert result["qa_report"]["rule_version"] == "qa-001/v1"
