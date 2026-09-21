"""Planner Agent: structured suggestions over a locked TopicBrief, without tools."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from .ledger import AgentRunLedger
from .registry import AgentDefinition, AgentError, AgentRegistry
from .runner import AgentRunner, ModelPort


_CONTRACTS = Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema"
INPUT_REF = "planner-input/v1"
OUTPUT_REF = "planner-output/v1"
INPUT_SCHEMA = json.loads((_CONTRACTS / "planner-input.schema.json").read_text(encoding="utf-8"))
OUTPUT_SCHEMA = json.loads((_CONTRACTS / "planner-output.schema.json").read_text(encoding="utf-8"))
_OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA, format_checker=FormatChecker())


class TopicBriefPort(Protocol):
    def get(self, *, org_id: UUID | str, brief_id: UUID | str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class PlannerModelRequest:
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
        material = {
            "model_id": self.model_id, "prompt_version": self.prompt_version,
            "input": self.input, "response_schema_ref": self.response_schema_ref,
        }
        return _hash(material)


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AgentError("PLANNER_INPUT_INVALID", f"{name} must be a UUID") from exc


class _CapturePort:
    def __init__(self, source: ModelPort, brief_id: UUID) -> None:
        self.source = source
        self.brief_id = brief_id
        self.response: Any = None

    def generate(self, request: Any) -> Any:
        response = self.source.generate(request)
        PlannerAgent._validate_plan(response.output, self.brief_id)
        self.response = response
        return self.response


class PlannerAgent:
    """Generate a plan; never invokes WorkflowService or a side-effect tool."""

    def __init__(self, *, topic_briefs: TopicBriefPort, model_port: ModelPort,
                 registry: AgentRegistry | None = None, runner: AgentRunner | None = None,
                 ledger: AgentRunLedger | None = None) -> None:
        self.topic_briefs = topic_briefs
        self.model_port = model_port
        self.registry = registry or AgentRegistry()
        for ref, schema in ((INPUT_REF, INPUT_SCHEMA), (OUTPUT_REF, OUTPUT_SCHEMA)):
            previous = self.registry.schemas.setdefault(ref, schema)
            if previous != schema:
                raise AgentError("AGENT_SCHEMA_CONFLICT", "planner schema reference already differs")
        self.runner = runner or AgentRunner(self.registry)
        if self.runner.registry is not self.registry:
            raise AgentError("AGENT_REGISTRY_MISMATCH", "runner and planner must share a registry")
        self.ledger = ledger or AgentRunLedger()
        self._results: dict[tuple[UUID, str], tuple[str, dict[str, Any]]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def _definition(self, tenant: UUID) -> AgentDefinition:
        try:
            definition = self.registry.get(org_id=tenant, key="planner")
        except AgentError as exc:
            if exc.code != "AGENT_NOT_FOUND":
                raise
            return self.registry.register(
                org_id=tenant, key="planner", input_schema_ref=INPUT_REF, output_schema_ref=OUTPUT_REF,
                tool_allowlist=[], permissions=[], cost_limit_cents=10, timeout_ms=1000,
                human_escalation_conditions=["low_confidence", "explicit_review"],
            )
        if definition.input_schema_ref != INPUT_REF or definition.output_schema_ref != OUTPUT_REF or definition.tool_allowlist:
            raise AgentError("PLANNER_DEFINITION_INVALID", "planner definition must use the safe schemas and no tools")
        return definition

    @staticmethod
    def _validate_plan(output: Mapping[str, Any], brief_id: UUID) -> None:
        errors = list(_OUTPUT_VALIDATOR.iter_errors(output))
        if errors:
            raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", errors[0].message)
        if output["topic_plan"]["topic_brief_id"] != str(brief_id):
            raise AgentError("PLANNER_BRIEF_MISMATCH", "plan references another TopicBrief")
        prior: set[str] = set()
        for step in output["workflow_plan"]["steps"]:
            key = step["step_key"]
            if key in prior or any(dependency not in prior for dependency in step["depends_on"]):
                raise AgentError("PLANNER_DEPENDENCY_INVALID", "workflow steps must have unique keys and forward dependencies")
            prior.add(key)

    def plan(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
             topic_brief_id: UUID | str, goal: str) -> dict[str, Any]:
        tenant, actor, brief_id = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _uuid(topic_brief_id, "topic_brief_id")
        if not isinstance(trace_id, str) or not trace_id.strip() or len(trace_id) > 256:
            raise AgentError("PLANNER_INPUT_INVALID", "trace_id is invalid")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200:
            raise AgentError("PLANNER_INPUT_INVALID", "idempotency_key is invalid")
        brief = self.topic_briefs.get(org_id=tenant, brief_id=brief_id)
        if not isinstance(brief, Mapping) or brief.get("org_id") != str(tenant) or brief.get("id") != str(brief_id):
            raise AgentError("TENANT_SCOPE_VIOLATION", "TopicBrief is outside this organization")
        if brief.get("status") not in {"locked", "approved"}:
            raise AgentError("PLANNER_BRIEF_NOT_LOCKED", "TopicBrief must be locked or approved")
        audience = brief.get("audience")
        values = {
            "topic_brief_id": str(brief_id), "brief_hash": brief.get("input_snapshot_hash"),
            "goal": goal, "audience": audience.get("role") if isinstance(audience, Mapping) else None,
            "problem": brief.get("problem") or brief.get("problem_statement"), "tool_calls": [],
        }
        definition = self._definition(tenant)
        self.registry.validate_input(definition, values)
        digest = _hash(values)
        identity = (tenant, idempotency_key)
        with self._lock:
            prior = self._results.get(identity)
            if prior is not None:
                if prior[0] != digest:
                    raise AgentError("IDEMPOTENCY_KEY_REUSED", "planner input differs from prior request")
                return deepcopy(prior[1])
            request = PlannerModelRequest("fake", "planner/v1", values, OUTPUT_REF,
                                          definition.timeout_ms, definition.cost_limit_cents,
                                          trace_id.strip(), str(tenant))
            captured = _CapturePort(self.model_port, brief_id)
            run = self.runner.run(org_id=tenant, definition=definition, input=values,
                                  model_port=captured, model_request=request)
            result = {
                "org_id": str(tenant), "topic_brief_id": str(brief_id), "agent_run_id": str(run.id),
                "status": run.status, "topic_plan": deepcopy(run.output["topic_plan"]),
                "workflow_plan": deepcopy(run.output["workflow_plan"]),
                "confidence": run.output["confidence"], "needs_review": run.status == "needs_review",
                "output_hash": run.output_hash,
            }
            self.ledger.record_agent_run(org_id=tenant, agent_definition_id=definition.id,
                                         status=run.status, input_payload=values, output_payload=run.output)
            response = captured.response
            self.ledger.record_model_call(
                org_id=tenant, model_config_id=request.model_id, prompt_version=request.prompt_version,
                request_hash=request.request_hash, input_payload=values, output_payload=run.output,
                cost_cents=response.cost_cents, latency_ms=response.latency_ms,
                status="succeeded", attempt_no=1,
            )
            self.audit.append({
                "event_type": "agent.planner.completed", "org_id": str(tenant), "actor_id": str(actor),
                "trace_id": trace_id.strip(), "agent_run_id": str(run.id),
                "input_hash": run.input_hash, "output_hash": run.output_hash,
                "idempotency_key": idempotency_key,
            })
            self._results[identity] = (digest, deepcopy(result))
            return deepcopy(result)


__all__ = ["PlannerAgent", "PlannerModelRequest", "TopicBriefPort", "INPUT_REF", "OUTPUT_REF"]
