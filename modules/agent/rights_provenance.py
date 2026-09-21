"""Rights/Provenance Agent that extracts evidence clues without deciding rights."""

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
INPUT_REF = "rights-provenance-input/v1"
OUTPUT_REF = "rights-provenance-output/v1"
INPUT_SCHEMA = json.loads((_CONTRACTS / "rights-provenance-input.schema.json").read_text(encoding="utf-8"))
OUTPUT_SCHEMA = json.loads((_CONTRACTS / "rights-provenance-output.schema.json").read_text(encoding="utf-8"))
RIGHTS_VERSION_SCHEMA = json.loads((_CONTRACTS / "rights-record-version.schema.json").read_text(encoding="utf-8"))
EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
_OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA, format_checker=FormatChecker())
_RIGHTS_VERSION_VALIDATOR = Draft202012Validator(RIGHTS_VERSION_SCHEMA, format_checker=FormatChecker())
_EVENT_VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())


class RightsProvenancePort(Protocol):
    def get_version(
        self, *, org_id: UUID | str, rights_record_id: UUID | str, version_id: UUID | str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class RightsProvenanceModelRequest:
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
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "input": self.input,
            "response_schema_ref": self.response_schema_ref,
        })


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AgentError("RIGHTS_PROVENANCE_INPUT_INVALID", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise AgentError(
            "RIGHTS_PROVENANCE_INPUT_INVALID",
            f"{name} must be nonempty and at most {limit} characters",
        )
    return value.strip()


class _CapturePort:
    def __init__(self, source: ModelPort, allowed_citations: set[tuple[str, str, str]]) -> None:
        self.source = source
        self.allowed_citations = allowed_citations
        self.response: Any = None

    def generate(self, request: Any) -> Any:
        response = self.source.generate(request)
        RightsProvenanceAgent._validate_output(response.output, self.allowed_citations)
        self.response = response
        return response


class RightsProvenanceAgent:
    """Extract rights evidence and gaps while leaving every decision to rules or people."""

    def __init__(
        self, *, rights: RightsProvenancePort, model_port: ModelPort,
        registry: AgentRegistry | None = None, runner: AgentRunner | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> None:
        self.rights = rights
        self.model_port = model_port
        self.registry = registry or AgentRegistry()
        for ref, schema in ((INPUT_REF, INPUT_SCHEMA), (OUTPUT_REF, OUTPUT_SCHEMA)):
            previous = self.registry.schemas.setdefault(ref, schema)
            if previous != schema:
                raise AgentError("AGENT_SCHEMA_CONFLICT", "rights provenance schema reference already differs")
        self.runner = runner or AgentRunner(self.registry)
        if self.runner.registry is not self.registry:
            raise AgentError("AGENT_REGISTRY_MISMATCH", "runner and rights provenance agent must share a registry")
        self.ledger = ledger or AgentRunLedger()
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._results: dict[tuple[UUID, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def _definition(self, tenant: UUID) -> AgentDefinition:
        try:
            definition = self.registry.get(org_id=tenant, key="rights-provenance")
        except AgentError as exc:
            if exc.code != "AGENT_NOT_FOUND":
                raise
            return self.registry.register(
                org_id=tenant,
                key="rights-provenance",
                input_schema_ref=INPUT_REF,
                output_schema_ref=OUTPUT_REF,
                tool_allowlist=[],
                permissions=[],
                cost_limit_cents=20,
                timeout_ms=2000,
                human_escalation_conditions=[
                    "final_rights_decision_required",
                    "rights_evidence_gap",
                    "low_confidence",
                ],
            )
        if (
            definition.input_schema_ref != INPUT_REF
            or definition.output_schema_ref != OUTPUT_REF
            or definition.tool_allowlist
            or definition.permissions
        ):
            raise AgentError(
                "RIGHTS_PROVENANCE_DEFINITION_INVALID",
                "rights provenance definition must use safe schemas without tools or write permissions",
            )
        return definition

    def analyze(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, analysis_request_id: UUID | str,
        rights_record_id: UUID | str, rights_record_version_id: UUID | str,
        evidence_excerpts: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        request_id = _uuid(analysis_request_id, "analysis_request_id")
        record_id = _uuid(rights_record_id, "rights_record_id")
        version_id = _uuid(rights_record_version_id, "rights_record_version_id")
        trace = _text(trace_id, "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        excerpts = self._normalize_excerpts(evidence_excerpts)
        command_digest = _hash({
            "analysis_request_id": str(request_id),
            "rights_record_id": str(record_id),
            "rights_record_version_id": str(version_id),
            "evidence_excerpts": excerpts,
        })
        identity = (tenant, key)
        with self._lock:
            prior = self._results.get(identity)
            if prior is not None:
                if prior[0] != command_digest:
                    raise AgentError("IDEMPOTENCY_KEY_REUSED", "rights provenance input differs from prior request")
                return deepcopy(prior[1])

            version = self.rights.get_version(
                org_id=tenant,
                rights_record_id=record_id,
                version_id=version_id,
            )
            context, known_refs = self._rights_context(tenant, record_id, version_id, version)
            unknown_refs = sorted({item["evidence_ref"] for item in excerpts} - known_refs)
            if unknown_refs:
                raise AgentError(
                    "RIGHTS_PROVENANCE_EVIDENCE_UNKNOWN",
                    "every excerpt must reference the selected immutable rights version",
                )
            allowed_citations = {
                (item["evidence_ref"], item["locator"], item["quote"])
                for item in excerpts
            }
            values = {
                "analysis_request_id": str(request_id),
                "rights_context": context,
                "evidence_excerpts": excerpts,
                "tool_calls": [],
            }
            definition = self._definition(tenant)
            self.registry.validate_input(definition, values)
            request = RightsProvenanceModelRequest(
                "fake",
                "rights-provenance/v1",
                values,
                OUTPUT_REF,
                definition.timeout_ms,
                definition.cost_limit_cents,
                trace,
                str(tenant),
            )
            captured = _CapturePort(self.model_port, allowed_citations)
            run = self.runner.run(
                org_id=tenant,
                definition=definition,
                input=values,
                model_port=captured,
                model_request=request,
            )
            event = self._event(
                tenant=tenant,
                actor=actor,
                trace=trace,
                key=key,
                run_id=run.id,
                status=run.status,
                output_hash=run.output_hash,
                occurred_at=run.created_at,
            )
            result = {
                "org_id": str(tenant),
                "analysis_request_id": str(request_id),
                "rights_record_id": str(record_id),
                "rights_record_version_id": str(version_id),
                "agent_run_id": str(run.id),
                "status": run.status,
                "permission_clues": deepcopy(run.output["permission_clues"]),
                "scope_candidates": deepcopy(run.output["scope_candidates"]),
                "gaps": deepcopy(run.output["gaps"]),
                "confidence": run.output["confidence"],
                "needs_review": True,
                "final_rights_decision": "deferred",
                "output_hash": run.output_hash,
                "event": event,
                "extraction_only": True,
                "rights_record_written": False,
                "rights_status_mutated": False,
                "authorization_decision_created": False,
            }
            self.ledger.record_agent_run(
                org_id=tenant,
                agent_definition_id=definition.id,
                status=run.status,
                input_payload=values,
                output_payload=run.output,
            )
            response = captured.response
            self.ledger.record_model_call(
                org_id=tenant,
                model_config_id=request.model_id,
                prompt_version=request.prompt_version,
                request_hash=request.request_hash,
                input_payload=values,
                output_payload=run.output,
                cost_cents=response.cost_cents,
                latency_ms=response.latency_ms,
                status="succeeded",
                attempt_no=1,
            )
            self.audit.append({
                "event_type": "agent.rights_provenance.completed",
                "org_id": str(tenant),
                "actor_id": str(actor),
                "trace_id": trace,
                "agent_run_id": str(run.id),
                "input_schema_ref": INPUT_REF,
                "output_schema_ref": OUTPUT_REF,
                "input_hash": run.input_hash,
                "output_hash": run.output_hash,
                "policy_rule_version": context["recorded_scope"]["policy_rule_version"],
                "idempotency_key": key,
                "permission_clue_count": len(run.output["permission_clues"]),
                "scope_candidate_count": len(run.output["scope_candidates"]),
                "gap_count": len(run.output["gaps"]),
                "latency_ms": response.latency_ms,
                "cost_cents": response.cost_cents,
                "final_rights_decision": "deferred",
                "rights_record_written": False,
                "rights_status_mutated": False,
                "authorization_decision_created": False,
            })
            self._results[identity] = (command_digest, deepcopy(result))
            return deepcopy(result)

    run = analyze

    @staticmethod
    def _normalize_excerpts(value: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not 1 <= len(value) <= 50:
            raise AgentError(
                "RIGHTS_PROVENANCE_INPUT_INVALID",
                "evidence_excerpts must contain 1 to 50 controlled excerpts",
            )
        normalized: list[dict[str, str]] = []
        identities: set[tuple[str, str, str]] = set()
        for item in value:
            if not isinstance(item, Mapping):
                raise AgentError("RIGHTS_PROVENANCE_INPUT_INVALID", "evidence excerpt must be an object")
            excerpt = {
                "evidence_ref": _text(item.get("evidence_ref"), "evidence_ref", 2048),
                "locator": _text(item.get("locator"), "locator", 1000),
                "quote": _text(item.get("quote"), "quote", 4000),
            }
            identity = (excerpt["evidence_ref"], excerpt["locator"], excerpt["quote"])
            if identity in identities:
                raise AgentError("RIGHTS_PROVENANCE_INPUT_INVALID", "evidence excerpts must be unique")
            identities.add(identity)
            normalized.append(excerpt)
        return normalized

    @staticmethod
    def _rights_context(
        tenant: UUID, record_id: UUID, version_id: UUID, value: Mapping[str, Any],
    ) -> tuple[dict[str, Any], set[str]]:
        if not isinstance(value, Mapping):
            raise AgentError("RIGHTS_PROVENANCE_VERSION_INVALID", "rights version must be an object")
        if value.get("org_id") != str(tenant):
            raise AgentError("TENANT_SCOPE_VIOLATION", "rights version is outside this organization")
        if value.get("rights_record_id") != str(record_id) or value.get("id") != str(version_id):
            raise AgentError("RIGHTS_PROVENANCE_VERSION_INVALID", "rights version identity does not match the request")
        errors = sorted(_RIGHTS_VERSION_VALIDATOR.iter_errors(dict(value)), key=lambda error: list(error.path))
        if errors:
            raise AgentError("RIGHTS_PROVENANCE_VERSION_INVALID", errors[0].message)
        context = {
            "rights_record_id": str(record_id),
            "rights_record_version_id": str(version_id),
            "version_no": value["version_no"],
            "snapshot_hash": value["snapshot_hash"],
            "source_snapshot_ids": list(value["source_snapshot_ids"]),
            "license_ref": value["license_ref"],
            "contract_ref": value["contract_ref"],
            "evidence_object_refs": list(value["evidence_object_refs"]),
            "recorded_scope": {
                "rights_holder": value["rights_holder"],
                "permitted_regions": list(value["permitted_regions"]),
                "permitted_locales": list(value["permitted_locales"]),
                "permitted_media": list(value["permitted_media"]),
                "permitted_use": value["permitted_use"],
                "valid_from": value["valid_from"],
                "valid_to": value["valid_to"],
                "policy_rule_version": value["policy_rule_version"],
                "status": value["status"],
            },
        }
        known_refs = set(context["source_snapshot_ids"]) | set(context["evidence_object_refs"])
        if context["license_ref"] is not None:
            known_refs.add(context["license_ref"])
        if context["contract_ref"] is not None:
            known_refs.add(context["contract_ref"])
        return context, known_refs

    @staticmethod
    def _validate_output(
        output: Mapping[str, Any], allowed_citations: set[tuple[str, str, str]],
    ) -> None:
        errors = sorted(_OUTPUT_VALIDATOR.iter_errors(output), key=lambda error: list(error.path))
        if errors:
            raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", errors[0].message)
        clues, scopes, gaps = output["permission_clues"], output["scope_candidates"], output["gaps"]
        if not clues and not gaps:
            raise AgentError(
                "RIGHTS_PROVENANCE_OUTPUT_EMPTY",
                "rights extraction must return a permission clue or an evidence gap",
            )
        clue_keys = [item["clue_key"] for item in clues]
        if len(clue_keys) != len(set(clue_keys)):
            raise AgentError("RIGHTS_PROVENANCE_CLUE_DUPLICATE", "permission clue keys must be unique")
        for clue in clues:
            citation = (clue["evidence_ref"], clue["locator"], clue["quote"])
            if citation not in allowed_citations:
                raise AgentError(
                    "RIGHTS_PROVENANCE_CITATION_INVALID",
                    "permission clue is not present in a supplied controlled excerpt",
                )
        scope_keys = [item["scope_key"] for item in scopes]
        if len(scope_keys) != len(set(scope_keys)):
            raise AgentError("RIGHTS_PROVENANCE_SCOPE_DUPLICATE", "scope candidate keys must be unique")
        gap_keys = [item["gap_key"] for item in gaps]
        if len(gap_keys) != len(set(gap_keys)):
            raise AgentError("RIGHTS_PROVENANCE_GAP_DUPLICATE", "gap keys must be unique")
        known_clues = set(clue_keys)
        referenced = [key for item in scopes for key in item["evidence_clue_keys"]]
        referenced.extend(key for item in gaps for key in item["related_clue_keys"])
        if any(key not in known_clues for key in referenced):
            raise AgentError(
                "RIGHTS_PROVENANCE_CLUE_REFERENCE_INVALID",
                "scope candidates and gaps may reference only this run's permission clues",
            )

    def _event(
        self, *, tenant: UUID, actor: UUID, trace: str, key: str, run_id: UUID,
        status: str, output_hash: str | None, occurred_at: str,
    ) -> dict[str, Any]:
        payload = {
            "aggregate_id": str(run_id),
            "aggregate_version": 1,
            "from_state": "running",
            "to_state": status,
            "command": "rights_provenance_extract",
            "snapshot_hash": output_hash,
            "reason": "rights conclusion requires policy rules or human review",
            "agent_key": "rights-provenance",
            "extraction_only": True,
            "final_rights_decision": "deferred",
        }
        event = {
            "event_id": str(uuid4()),
            "event_type": "agent_run.completed",
            "event_schema_version": 1,
            "occurred_at": occurred_at,
            "org_id": str(tenant),
            "trace_id": trace,
            "aggregate_type": "AgentRun",
            "aggregate_id": str(run_id),
            "aggregate_version": 1,
            "actor_type": "user",
            "actor_id": str(actor),
            "idempotency_key": key,
            "payload": payload,
            "payload_hash": _hash(payload),
        }
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise AgentError("RIGHTS_PROVENANCE_EVENT_INVALID", errors[0].message)
        self.events.append(deepcopy(event))
        return event


__all__ = [
    "INPUT_REF",
    "INPUT_SCHEMA",
    "OUTPUT_REF",
    "OUTPUT_SCHEMA",
    "RightsProvenanceAgent",
    "RightsProvenanceModelRequest",
    "RightsProvenancePort",
]
