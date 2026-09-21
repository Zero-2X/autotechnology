"""Research Agent that emits cited candidates and verification items only."""

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
INPUT_REF = "research-input/v1"
OUTPUT_REF = "research-output/v1"
INPUT_SCHEMA = json.loads((_CONTRACTS / "research-input.schema.json").read_text(encoding="utf-8"))
OUTPUT_SCHEMA = json.loads((_CONTRACTS / "research-output.schema.json").read_text(encoding="utf-8"))
EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
_OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA, format_checker=FormatChecker())
_EVENT_VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())


class ResearchSourcePort(Protocol):
    def get(self, *, org_id: UUID | str, source_snapshot_id: UUID | str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ResearchModelRequest:
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
        return _hash({
            "model_id": self.model_id, "prompt_version": self.prompt_version,
            "input": self.input, "response_schema_ref": self.response_schema_ref,
        })


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AgentError("RESEARCH_INPUT_INVALID", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise AgentError("RESEARCH_INPUT_INVALID", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


class _CapturePort:
    def __init__(self, source: ModelPort, allowed_citations: set[tuple[str, str, str]]) -> None:
        self.source = source
        self.allowed_citations = allowed_citations
        self.response: Any = None

    def generate(self, request: Any) -> Any:
        response = self.source.generate(request)
        ResearchAgent._validate_research_output(response.output, self.allowed_citations)
        self.response = response
        return response


class ResearchAgent:
    """Run bounded research without creating Claims or KnowledgeCore versions."""

    def __init__(self, *, sources: ResearchSourcePort, model_port: ModelPort,
                 registry: AgentRegistry | None = None, runner: AgentRunner | None = None,
                 ledger: AgentRunLedger | None = None) -> None:
        self.sources = sources
        self.model_port = model_port
        self.registry = registry or AgentRegistry()
        for ref, schema in ((INPUT_REF, INPUT_SCHEMA), (OUTPUT_REF, OUTPUT_SCHEMA)):
            previous = self.registry.schemas.setdefault(ref, schema)
            if previous != schema:
                raise AgentError("AGENT_SCHEMA_CONFLICT", "research schema reference already differs")
        self.runner = runner or AgentRunner(self.registry)
        if self.runner.registry is not self.registry:
            raise AgentError("AGENT_REGISTRY_MISMATCH", "runner and research agent must share a registry")
        self.ledger = ledger or AgentRunLedger()
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._results: dict[tuple[UUID, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def _definition(self, tenant: UUID) -> AgentDefinition:
        try:
            definition = self.registry.get(org_id=tenant, key="research")
        except AgentError as exc:
            if exc.code != "AGENT_NOT_FOUND":
                raise
            return self.registry.register(
                org_id=tenant, key="research", input_schema_ref=INPUT_REF, output_schema_ref=OUTPUT_REF,
                tool_allowlist=[], permissions=[], cost_limit_cents=20, timeout_ms=2000,
                human_escalation_conditions=["all_candidates_require_review", "citation_mismatch", "low_confidence"],
            )
        if (definition.input_schema_ref != INPUT_REF or definition.output_schema_ref != OUTPUT_REF
                or definition.tool_allowlist or definition.permissions):
            raise AgentError("RESEARCH_DEFINITION_INVALID", "research definition must use safe schemas without tools or write permissions")
        return definition

    def research(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, research_request_id: UUID | str, question: str,
        source_snapshot_ids: Sequence[UUID | str],
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        request_id = _uuid(research_request_id, "research_request_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        inquiry = _text(question, "question", 2000)
        if isinstance(source_snapshot_ids, (str, bytes)) or not isinstance(source_snapshot_ids, Sequence):
            raise AgentError("RESEARCH_INPUT_INVALID", "source_snapshot_ids must be a sequence")
        snapshot_ids = [_uuid(value, "source_snapshot_id") for value in source_snapshot_ids]
        if not 1 <= len(snapshot_ids) <= 20 or len(set(snapshot_ids)) != len(snapshot_ids):
            raise AgentError("RESEARCH_INPUT_INVALID", "source_snapshot_ids must contain 1 to 20 unique values")
        command_digest = _hash({"research_request_id": str(request_id), "question": inquiry,
                                "source_snapshot_ids": [str(value) for value in snapshot_ids]})
        identity = (tenant, key)
        with self._lock:
            prior = self._results.get(identity)
            if prior is not None:
                if prior[0] != command_digest:
                    raise AgentError("IDEMPOTENCY_KEY_REUSED", "research input differs from prior request")
                return deepcopy(prior[1])

            materials: list[dict[str, Any]] = []
            allowed_citations: set[tuple[str, str, str]] = set()
            for snapshot_id in snapshot_ids:
                value = self.sources.get(org_id=tenant, source_snapshot_id=snapshot_id)
                material = self._material(tenant, snapshot_id, value)
                materials.append(material)
                for excerpt in material["excerpts"]:
                    allowed_citations.add((material["source_snapshot_id"], excerpt["locator"], excerpt["quote"]))
            values = {
                "research_request_id": str(request_id), "question": inquiry,
                "sources": materials, "tool_calls": [],
            }
            definition = self._definition(tenant)
            self.registry.validate_input(definition, values)
            request = ResearchModelRequest(
                "fake", "research/v1", values, OUTPUT_REF,
                definition.timeout_ms, definition.cost_limit_cents, trace, str(tenant),
            )
            captured = _CapturePort(self.model_port, allowed_citations)
            run = self.runner.run(org_id=tenant, definition=definition, input=values,
                                  model_port=captured, model_request=request)
            event = self._event(tenant=tenant, actor=actor, trace=trace, key=key,
                                run_id=run.id, status=run.status, output_hash=run.output_hash,
                                occurred_at=run.created_at)
            result = {
                "org_id": str(tenant), "research_request_id": str(request_id),
                "agent_run_id": str(run.id), "status": run.status,
                "candidate_facts": deepcopy(run.output["candidate_facts"]),
                "verification_items": deepcopy(run.output["verification_items"]),
                "confidence": run.output["confidence"], "needs_review": True,
                "output_hash": run.output_hash, "event": event,
                "candidate_only": True, "claims_created": False,
                "knowledge_core_mutated": False,
            }
            self.ledger.record_agent_run(
                org_id=tenant, agent_definition_id=definition.id, status=run.status,
                input_payload=values, output_payload=run.output,
            )
            response = captured.response
            self.ledger.record_model_call(
                org_id=tenant, model_config_id=request.model_id, prompt_version=request.prompt_version,
                request_hash=request.request_hash, input_payload=values, output_payload=run.output,
                cost_cents=response.cost_cents, latency_ms=response.latency_ms,
                status="succeeded", attempt_no=1,
            )
            self.audit.append({
                "event_type": "agent.research.completed", "org_id": str(tenant),
                "actor_id": str(actor), "trace_id": trace, "agent_run_id": str(run.id),
                "input_hash": run.input_hash, "output_hash": run.output_hash,
                "idempotency_key": key, "candidate_count": len(run.output["candidate_facts"]),
                "verification_item_count": len(run.output["verification_items"]),
                "claims_created": False, "knowledge_core_mutated": False,
            })
            self._results[identity] = (command_digest, deepcopy(result))
            return deepcopy(result)

    run = research

    @staticmethod
    def _material(tenant: UUID, snapshot_id: UUID, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or value.get("org_id") != str(tenant) or value.get("id") != str(snapshot_id):
            raise AgentError("TENANT_SCOPE_VIOLATION", "SourceSnapshot is outside this organization")
        if value.get("status") != "usable":
            raise AgentError("RESEARCH_SOURCE_NOT_USABLE", "research requires usable SourceSnapshot records")
        content_hash = value.get("content_hash")
        if not isinstance(content_hash, str) or len(content_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in content_hash):
            raise AgentError("RESEARCH_SOURCE_INVALID", "SourceSnapshot content_hash is invalid")
        excerpts = value.get("excerpts")
        if isinstance(excerpts, (str, bytes)) or not isinstance(excerpts, Sequence) or not 1 <= len(excerpts) <= 50:
            raise AgentError("RESEARCH_SOURCE_INVALID", "SourceSnapshot requires 1 to 50 controlled excerpts")
        normalized: list[dict[str, str]] = []
        for excerpt in excerpts:
            if not isinstance(excerpt, Mapping):
                raise AgentError("RESEARCH_SOURCE_INVALID", "source excerpt must be an object")
            normalized.append({
                "locator": _text(excerpt.get("locator"), "excerpt.locator", 1000),
                "quote": _text(excerpt.get("quote"), "excerpt.quote", 4000),
            })
        return {"source_snapshot_id": str(snapshot_id), "content_hash": content_hash,
                "excerpts": normalized}

    @staticmethod
    def _validate_research_output(output: Mapping[str, Any], allowed_citations: set[tuple[str, str, str]]) -> None:
        errors = sorted(_OUTPUT_VALIDATOR.iter_errors(output), key=lambda error: list(error.path))
        if errors:
            raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", errors[0].message)
        candidates = output["candidate_facts"]
        items = output["verification_items"]
        if not candidates and not items:
            raise AgentError("RESEARCH_OUTPUT_EMPTY", "research must return a candidate or verification item")
        candidate_keys = [candidate["candidate_key"] for candidate in candidates]
        if len(candidate_keys) != len(set(candidate_keys)):
            raise AgentError("RESEARCH_CANDIDATE_DUPLICATE", "candidate keys must be unique")
        for candidate in candidates:
            for citation in candidate["citations"]:
                identity = (citation["source_snapshot_id"], citation["locator"], citation["quote"])
                if identity not in allowed_citations:
                    raise AgentError("RESEARCH_CITATION_INVALID", "candidate citation is not present in a supplied SourceSnapshot excerpt")
        item_keys = [item["item_key"] for item in items]
        if len(item_keys) != len(set(item_keys)):
            raise AgentError("RESEARCH_ITEM_DUPLICATE", "verification item keys must be unique")
        known = set(candidate_keys)
        if any(key not in known for item in items for key in item["related_candidate_keys"]):
            raise AgentError("RESEARCH_ITEM_REFERENCE_INVALID", "verification item references an unknown candidate")

    def _event(self, *, tenant: UUID, actor: UUID, trace: str, key: str, run_id: UUID,
               status: str, output_hash: str | None, occurred_at: str) -> dict[str, Any]:
        payload = {
            "aggregate_id": str(run_id), "aggregate_version": 1,
            "from_state": "running", "to_state": status, "command": "research",
            "snapshot_hash": output_hash, "reason": "candidate facts require human verification",
            "agent_key": "research", "candidate_only": True,
        }
        event = {
            "event_id": str(uuid4()), "event_type": "agent_run.completed", "event_schema_version": 1,
            "occurred_at": occurred_at, "org_id": str(tenant), "trace_id": trace,
            "aggregate_type": "AgentRun", "aggregate_id": str(run_id), "aggregate_version": 1,
            "actor_type": "user", "actor_id": str(actor), "idempotency_key": key,
            "payload": payload, "payload_hash": _hash(payload),
        }
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise AgentError("RESEARCH_EVENT_INVALID", errors[0].message)
        self.events.append(deepcopy(event))
        return event


__all__ = [
    "INPUT_REF", "INPUT_SCHEMA", "OUTPUT_REF", "OUTPUT_SCHEMA",
    "ResearchAgent", "ResearchModelRequest", "ResearchSourcePort",
]
