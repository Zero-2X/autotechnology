"""QA Agent that explains deterministic findings and proposes review tasks only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .ledger import AgentRunLedger
from .registry import AgentDefinition, AgentError, AgentRegistry
from .runner import AgentRunner, ModelPort


_ROOT = Path(__file__).resolve().parents[2]
_CONTRACTS = _ROOT / "packages/contracts/jsonschema"
INPUT_REF = "qa-agent-input/v1"
OUTPUT_REF = "qa-agent-output/v1"
INPUT_SCHEMA = json.loads((_CONTRACTS / "qa-agent-input.schema.json").read_text(encoding="utf-8"))
OUTPUT_SCHEMA = json.loads((_CONTRACTS / "qa-agent-output.schema.json").read_text(encoding="utf-8"))
REPORT_SCHEMA = json.loads((_CONTRACTS / "qa-report.schema.json").read_text(encoding="utf-8"))
EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
_OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA, format_checker=FormatChecker())
_REPORT_VALIDATOR = Draft202012Validator(REPORT_SCHEMA, format_checker=FormatChecker())
_EVENT_VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())


class QACheckPort(Protocol):
    def check_variant(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, variant_version: Mapping[str, Any],
        canonical_version: Mapping[str, Any], claims: Sequence[Mapping[str, Any]],
        evidence: Sequence[Mapping[str, Any]], source_map: Sequence[Mapping[str, Any]],
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class QAModelRequest:
    model_id: str
    prompt_version: str
    input: Mapping[str, Any]
    response_schema_ref: str
    timeout_ms: int
    budget_cents: int
    trace_id: str
    org_id: str

    @property
    def request_hash(self) -> str:
        return _hash({"model_id": self.model_id, "prompt_version": self.prompt_version,
                      "input": self.input, "response_schema_ref": self.response_schema_ref})


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_freeze(item) for item in value]
    return value


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AgentError("QA_AGENT_INPUT_INVALID", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise AgentError("QA_AGENT_INPUT_INVALID", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


class _CapturePort:
    def __init__(self, source: ModelPort, report: Mapping[str, Any]) -> None:
        self.source = source
        self.report = report
        self.response: Any = None

    def generate(self, request: Any) -> Any:
        response = self.source.generate(request)
        QAAgent._validate_output(response.output, self.report)
        self.response = response
        return response


class QAAgent:
    """Explain read-only QA findings and create proposed human tasks."""

    def __init__(
        self, *, qa_checker: QACheckPort, model_port: ModelPort,
        registry: AgentRegistry | None = None, runner: AgentRunner | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> None:
        self.qa_checker = qa_checker
        self.model_port = model_port
        self.registry = registry or AgentRegistry()
        for ref, schema in ((INPUT_REF, INPUT_SCHEMA), (OUTPUT_REF, OUTPUT_SCHEMA)):
            previous = self.registry.schemas.setdefault(ref, schema)
            if previous != schema:
                raise AgentError("AGENT_SCHEMA_CONFLICT", "QA Agent schema reference already differs")
        self.runner = runner or AgentRunner(self.registry)
        if self.runner.registry is not self.registry:
            raise AgentError("AGENT_REGISTRY_MISMATCH", "runner and QA Agent must share a registry")
        self.ledger = ledger or AgentRunLedger()
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._results: dict[tuple[UUID, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def _definition(self, tenant: UUID) -> AgentDefinition:
        try:
            definition = self.registry.get(org_id=tenant, key="qa")
        except AgentError as exc:
            if exc.code != "AGENT_NOT_FOUND":
                raise
            return self.registry.register(
                org_id=tenant, key="qa", input_schema_ref=INPUT_REF,
                output_schema_ref=OUTPUT_REF, tool_allowlist=[], permissions=[],
                cost_limit_cents=30, timeout_ms=2500,
                human_escalation_conditions=["qa_failure", "qa_warning", "manual_review_required"],
            )
        if definition.input_schema_ref != INPUT_REF or definition.output_schema_ref != OUTPUT_REF or definition.tool_allowlist or definition.permissions:
            raise AgentError("QA_AGENT_DEFINITION_INVALID", "QA definition must use safe schemas without tools or write permissions")
        return definition

    def review(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, qa_request_id: UUID | str,
        variant_version: Mapping[str, Any], canonical_version: Mapping[str, Any],
        claims: Sequence[Mapping[str, Any]] = (), evidence: Sequence[Mapping[str, Any]] = (),
        source_map: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        request_id = _uuid(qa_request_id, "qa_request_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(variant_version, Mapping) or not isinstance(canonical_version, Mapping):
            raise AgentError("QA_AGENT_INPUT_INVALID", "variant_version and canonical_version must be objects")
        variant, canonical = _freeze(variant_version), _freeze(canonical_version)
        if variant.get("org_id") != str(tenant) or canonical.get("org_id") != str(tenant):
            raise AgentError("TENANT_SCOPE_VIOLATION", "QA projections are outside this organization")
        variant_id = _uuid(variant.get("id"), "variant_version.id")
        canonical_id = _uuid(canonical.get("id"), "canonical_version.id")
        if variant.get("canonical_content_version_id") != str(canonical_id):
            raise AgentError("QA_AGENT_SOURCE_MISMATCH", "Variant references a different Canonical version")
        subject = {
            "variant_version_id": str(variant_id),
            "canonical_content_version_id": str(canonical_id),
            "variant_snapshot_hash": self._hash_field(variant.get("snapshot_hash"), "variant.snapshot_hash"),
            "canonical_content_hash": self._hash_field(canonical.get("content_hash"), "canonical.content_hash"),
        }
        digest = _hash({
            "qa_request_id": str(request_id), "subject": subject, "variant": variant,
            "canonical": canonical, "claims": _freeze(claims), "evidence": _freeze(evidence),
            "source_map": _freeze(source_map),
        })
        identity = (tenant, key)
        with self._lock:
            prior = self._results.get(identity)
            if prior is not None:
                if prior[0] != digest:
                    raise AgentError("IDEMPOTENCY_KEY_REUSED", "QA input differs from prior request")
                return deepcopy(prior[1])
            report = self.qa_checker.check_variant(
                org_id=tenant, actor_id=actor, trace_id=trace, idempotency_key=f"{key}:deterministic",
                variant_version=variant, canonical_version=canonical,
                claims=list(claims), evidence=list(evidence), source_map=list(source_map),
            )
            self._validate_report(tenant, variant_id, canonical_id, report)
            report_input = {
                "id": str(report["id"]), "rule_version": report["rule_version"],
                "status": report["status"], "findings": deepcopy(list(report["findings"])),
            }
            values = {"qa_request_id": str(request_id), "subject": subject,
                      "qa_report": report_input, "tool_calls": []}
            definition = self._definition(tenant)
            self.registry.validate_input(definition, values)
            request = QAModelRequest("fake", "qa/v1", values, OUTPUT_REF,
                                     definition.timeout_ms, definition.cost_limit_cents, trace, str(tenant))
            captured = _CapturePort(self.model_port, report_input)
            run = self.runner.run(org_id=tenant, definition=definition, input=values,
                                  model_port=captured, model_request=request)
            event = self._event(tenant=tenant, actor=actor, trace=trace, key=key,
                                run_id=run.id, status=run.status, output_hash=run.output_hash,
                                occurred_at=run.created_at)
            result = {
                "org_id": str(tenant), "qa_request_id": str(request_id),
                "variant_version_id": str(variant_id), "canonical_content_version_id": str(canonical_id),
                "agent_run_id": str(run.id), "status": run.status,
                "qa_report": deepcopy(report), "findings": deepcopy(run.output["findings"]),
                "human_tasks": deepcopy(run.output["human_tasks"]), "summary": run.output["summary"],
                "needs_review": True, "decision": "review_only", "approved": False, "published": False,
                "output_hash": run.output_hash, "event": event,
                "approval_created": False, "publication_side_effect": False,
            }
            self.ledger.record_agent_run(org_id=tenant, agent_definition_id=definition.id,
                                         status=run.status, input_payload=values, output_payload=run.output)
            response = captured.response
            self.ledger.record_model_call(org_id=tenant, model_config_id=request.model_id,
                                          prompt_version=request.prompt_version, request_hash=request.request_hash,
                                          input_payload=values, output_payload=run.output,
                                          cost_cents=response.cost_cents, latency_ms=response.latency_ms,
                                          status="succeeded", attempt_no=1)
            self.audit.append({"event_type": "agent.qa.completed", "org_id": str(tenant),
                               "actor_id": str(actor), "trace_id": trace, "agent_run_id": str(run.id),
                               "input_hash": run.input_hash, "output_hash": run.output_hash,
                               "rule_version": report["rule_version"], "idempotency_key": key,
                               "finding_count": len(run.output["findings"]), "human_task_count": len(run.output["human_tasks"]),
                               "latency_ms": response.latency_ms, "cost_cents": response.cost_cents,
                               "decision": "review_only", "approved": False, "published": False})
            self._results[identity] = (digest, deepcopy(result))
            return deepcopy(result)

    run = review

    @staticmethod
    def _hash_field(value: Any, name: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise AgentError("QA_AGENT_INPUT_INVALID", f"{name} must be a SHA-256 hash")
        return value.lower()

    @staticmethod
    def _validate_report(tenant: UUID, variant_id: UUID, canonical_id: UUID, report: Mapping[str, Any]) -> None:
        if not isinstance(report, Mapping):
            raise AgentError("QA_AGENT_REPORT_INVALID", "QA checker must return an object")
        errors = sorted(_REPORT_VALIDATOR.iter_errors(dict(report)), key=lambda error: list(error.path))
        if errors:
            raise AgentError("QA_AGENT_REPORT_INVALID", errors[0].message)
        if report.get("org_id") != str(tenant) or report.get("subject_type") != "variant_version" or report.get("subject_id") != str(variant_id):
            raise AgentError("QA_AGENT_REPORT_INVALID", "QA report subject is outside this request")
        if any(not isinstance(item, Mapping) for item in report.get("findings", [])):
            raise AgentError("QA_AGENT_REPORT_INVALID", "QA findings must be objects")
        if any(item.get("canonical_content_version_id") not in (None, str(canonical_id)) for item in report.get("findings", [])):
            raise AgentError("QA_AGENT_REPORT_INVALID", "QA finding references an unexpected Canonical version")

    @staticmethod
    def _validate_output(output: Mapping[str, Any], report: Mapping[str, Any]) -> None:
        errors = sorted(_OUTPUT_VALIDATOR.iter_errors(output), key=lambda error: list(error.path))
        if errors:
            raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", errors[0].message)
        source = list(report["findings"])
        findings = output["findings"]
        if len(findings) != len(source):
            raise AgentError("QA_AGENT_FINDING_COVERAGE", "every deterministic finding must have an explanation")
        keys = [item["finding_key"] for item in findings]
        if len(keys) != len(set(keys)):
            raise AgentError("QA_AGENT_FINDING_DUPLICATE", "finding keys must be unique")
        for item in findings:
            index = item["source_finding_index"]
            if index >= len(source):
                raise AgentError("QA_AGENT_FINDING_REFERENCE", "finding index is outside the deterministic report")
            original = source[index]
            for field in ("code", "severity", "path"):
                if item[field] != original.get(field):
                    raise AgentError("QA_AGENT_FINDING_DRIFT", "model changed a deterministic finding")
            if item["observed"] != original.get("observed") or item["expected"] != original.get("expected"):
                raise AgentError("QA_AGENT_FINDING_DRIFT", "model changed observed or expected QA values")
        task_keys = [item["task_key"] for item in output["human_tasks"]]
        if len(task_keys) != len(set(task_keys)):
            raise AgentError("QA_AGENT_TASK_DUPLICATE", "human task keys must be unique")
        known = set(keys)
        if any(key not in known for task in output["human_tasks"] for key in task["finding_keys"]):
            raise AgentError("QA_AGENT_TASK_REFERENCE", "human task references an unknown finding")
        if report["status"] != "passed" and not output["human_tasks"]:
            raise AgentError("QA_AGENT_TASK_REQUIRED", "failed or review QA requires a proposed human task")
        if report["status"] == "passed" and output["human_tasks"]:
            raise AgentError("QA_AGENT_TASK_UNNECESSARY", "passed QA must not create a review task")

    def _event(self, *, tenant: UUID, actor: UUID, trace: str, key: str, run_id: UUID,
               status: str, output_hash: str | None, occurred_at: str) -> dict[str, Any]:
        payload = {"aggregate_id": str(run_id), "aggregate_version": 1,
                   "from_state": "running", "to_state": status,
                   "command": "qa_review", "snapshot_hash": output_hash,
                   "reason": "QA output requires human review and cannot approve or publish",
                   "agent_key": "qa", "decision": "review_only", "approved": False, "published": False}
        event = {"event_id": str(uuid4()), "event_type": "agent_run.completed", "event_schema_version": 1,
                 "occurred_at": occurred_at, "org_id": str(tenant), "trace_id": trace,
                 "aggregate_type": "AgentRun", "aggregate_id": str(run_id), "aggregate_version": 1,
                 "actor_type": "user", "actor_id": str(actor), "idempotency_key": key,
                 "payload": payload, "payload_hash": _hash(payload)}
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise AgentError("QA_AGENT_EVENT_INVALID", errors[0].message)
        self.events.append(deepcopy(event))
        return event


__all__ = ["INPUT_REF", "INPUT_SCHEMA", "OUTPUT_REF", "OUTPUT_SCHEMA", "QAAgent", "QACheckPort", "QAModelRequest"]
