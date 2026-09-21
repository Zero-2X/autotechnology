"""Transform Agent that produces reviewable Variant drafts without persistence."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .ledger import AgentRunLedger
from .registry import AgentDefinition, AgentError, AgentRegistry
from .runner import AgentRunner, ModelPort


_ROOT = Path(__file__).resolve().parents[2]
_CONTRACTS = _ROOT / "packages/contracts/jsonschema"
INPUT_REF = "transform-input/v1"
OUTPUT_REF = "transform-output/v1"
INPUT_SCHEMA = json.loads((_CONTRACTS / "transform-input.schema.json").read_text(encoding="utf-8"))
OUTPUT_SCHEMA = json.loads((_CONTRACTS / "transform-output.schema.json").read_text(encoding="utf-8"))
DRAFT_SCHEMA = json.loads((_CONTRACTS / "variant-draft.schema.json").read_text(encoding="utf-8"))
EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
_OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA, format_checker=FormatChecker())
_DRAFT_VALIDATOR = Draft202012Validator(DRAFT_SCHEMA, format_checker=FormatChecker())
_EVENT_VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)*(?:\s?(?:%|ms|s|GB|MB|KB))?(?![A-Za-z0-9_])")
_CODE_RE = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_LINK_RE = re.compile(r"https?://[^\s)>\]}]+")


class CanonicalVersionPort(Protocol):
    def get_version(self, *, org_id: UUID | str, version_id: UUID | str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TransformModelRequest:
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
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _uuid(value: UUID | str, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise AgentError("TRANSFORM_INPUT_INVALID", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise AgentError("TRANSFORM_INPUT_INVALID", f"{name} must be nonempty and at most {limit} characters")
    return value.strip()


class _CapturePort:
    def __init__(self, source: ModelPort, expected: list[dict[str, Any]], sections: list[dict[str, Any]]) -> None:
        self.source = source
        self.expected = expected
        self.sections = sections
        self.response: Any = None

    def generate(self, request: Any) -> Any:
        response = self.source.generate(request)
        TransformAgent._validate_output(response.output, self.expected, self.sections)
        self.response = response
        return response


class TransformAgent:
    """Use AgentRunner for a candidate Variant draft; PROD-002 owns persistence."""

    def __init__(
        self, *, canonical_versions: CanonicalVersionPort, model_port: ModelPort,
        registry: AgentRegistry | None = None, runner: AgentRunner | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> None:
        self.canonical_versions = canonical_versions
        self.model_port = model_port
        self.registry = registry or AgentRegistry()
        for ref, schema in ((INPUT_REF, INPUT_SCHEMA), (OUTPUT_REF, OUTPUT_SCHEMA)):
            previous = self.registry.schemas.setdefault(ref, schema)
            if previous != schema:
                raise AgentError("AGENT_SCHEMA_CONFLICT", "transform schema reference already differs")
        self.runner = runner or AgentRunner(self.registry)
        if self.runner.registry is not self.registry:
            raise AgentError("AGENT_REGISTRY_MISMATCH", "runner and transform agent must share a registry")
        self.ledger = ledger or AgentRunLedger()
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._results: dict[tuple[UUID, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def _definition(self, tenant: UUID) -> AgentDefinition:
        try:
            definition = self.registry.get(org_id=tenant, key="transform")
        except AgentError as exc:
            if exc.code != "AGENT_NOT_FOUND":
                raise
            return self.registry.register(
                org_id=tenant,
                key="transform",
                input_schema_ref=INPUT_REF,
                output_schema_ref=OUTPUT_REF,
                tool_allowlist=[],
                permissions=[],
                cost_limit_cents=40,
                timeout_ms=3000,
                human_escalation_conditions=["protected_mapping_gap", "low_confidence", "localization_review"],
            )
        if (
            definition.input_schema_ref != INPUT_REF
            or definition.output_schema_ref != OUTPUT_REF
            or definition.tool_allowlist
            or definition.permissions
        ):
            raise AgentError("TRANSFORM_DEFINITION_INVALID", "transform definition must use safe schemas without tools or write permissions")
        return definition

    def generate(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, transform_request_id: UUID | str,
        canonical_content_version_id: UUID | str, locale: str, market: str,
        audience: str, tone: str, terminology: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        request_id = _uuid(transform_request_id, "transform_request_id")
        version_id = _uuid(canonical_content_version_id, "canonical_content_version_id")
        trace, key = _text(trace_id, "trace_id", 256), _text(idempotency_key, "idempotency_key", 200)
        target = {
            "locale": _text(locale, "locale", 64), "market": _text(market, "market", 64),
            "audience": _text(audience, "audience", 256), "tone": _text(tone, "tone", 128),
        }
        terms = self._normalize_terminology(terminology)
        digest = _hash({
            "transform_request_id": str(request_id),
            "canonical_content_version_id": str(version_id),
            "target": target, "terminology": terms,
        })
        identity = (tenant, key)
        with self._lock:
            prior = self._results.get(identity)
            if prior is not None:
                if prior[0] != digest:
                    raise AgentError("IDEMPOTENCY_KEY_REUSED", "transform input differs from prior request")
                return deepcopy(prior[1])
            source = self.canonical_versions.get_version(org_id=tenant, version_id=version_id)
            context, sections, protected = self._source_context(tenant, version_id, source, terms)
            values = {
                "transform_request_id": str(request_id), "source_context": context,
                "target": target, "tool_calls": [],
            }
            definition = self._definition(tenant)
            self.registry.validate_input(definition, values)
            request = TransformModelRequest(
                "fake", "transform/v1", values, OUTPUT_REF, definition.timeout_ms,
                definition.cost_limit_cents, trace, str(tenant),
            )
            captured = _CapturePort(self.model_port, protected, sections)
            run = self.runner.run(
                org_id=tenant, definition=definition, input=values,
                model_port=captured, model_request=request,
            )
            draft = self._draft(
                tenant=tenant, actor=actor, trace=trace, source=source,
                version_id=version_id, target=target, output=run.output,
                sections=sections,
            )
            event = self._event(
                tenant=tenant, actor=actor, trace=trace, key=key, run_id=run.id,
                status=run.status, output_hash=run.output_hash, occurred_at=run.created_at,
            )
            result = {
                "org_id": str(tenant), "transform_request_id": str(request_id),
                "canonical_content_version_id": str(version_id), "agent_run_id": str(run.id),
                "status": run.status, "variant_draft": draft,
                "preservation_map": deepcopy(run.output["preservation_map"]),
                "needs_review": True, "output_hash": run.output_hash, "event": event,
                "draft_only": True, "content_variant_created": False,
                "variant_version_created": False, "publication_side_effect": False,
            }
            self.ledger.record_agent_run(
                org_id=tenant, agent_definition_id=definition.id, status=run.status,
                input_payload=values, output_payload=run.output,
            )
            response = captured.response
            self.ledger.record_model_call(
                org_id=tenant, model_config_id=request.model_id,
                prompt_version=request.prompt_version, request_hash=request.request_hash,
                input_payload=values, output_payload=run.output,
                cost_cents=response.cost_cents, latency_ms=response.latency_ms,
                status="succeeded", attempt_no=1,
            )
            self.audit.append({
                "event_type": "agent.transform.completed", "org_id": str(tenant),
                "actor_id": str(actor), "trace_id": trace, "agent_run_id": str(run.id),
                "input_schema_ref": INPUT_REF, "output_schema_ref": OUTPUT_REF,
                "input_hash": run.input_hash, "output_hash": run.output_hash,
                "idempotency_key": key, "policy_snapshot": None,
                "latency_ms": response.latency_ms, "cost_cents": response.cost_cents,
                "protected_mapping_count": len(run.output["preservation_map"]),
                "draft_only": True, "content_variant_created": False,
                "variant_version_created": False, "publication_side_effect": False,
            })
            self._results[identity] = (digest, deepcopy(result))
            return deepcopy(result)

    run = generate

    @staticmethod
    def _normalize_terminology(value: Sequence[Mapping[str, Any]] | None) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) > 200:
            raise AgentError("TRANSFORM_INPUT_INVALID", "terminology must be at most 200 objects")
        result: list[dict[str, str]] = []
        keys: set[str] = set()
        for item in value:
            if not isinstance(item, Mapping):
                raise AgentError("TRANSFORM_INPUT_INVALID", "terminology item must be an object")
            term = {
                "term_key": _text(item.get("term_key"), "term_key", 128),
                "source_key": _text(item.get("source_key"), "term.source_key", 256),
                "source_term": _text(item.get("source_term"), "term.source_term", 1000),
                "target_term": _text(item.get("target_term"), "term.target_term", 1000),
            }
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", term["term_key"]):
                raise AgentError("TRANSFORM_INPUT_INVALID", "term_key has invalid format")
            if term["term_key"] in keys:
                raise AgentError("TRANSFORM_INPUT_INVALID", "term_key values must be unique")
            keys.add(term["term_key"])
            result.append(term)
        return result

    @staticmethod
    def _source_context(
        tenant: UUID, version_id: UUID, source: Mapping[str, Any], terms: list[dict[str, str]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(source, Mapping) or source.get("org_id") != str(tenant) or source.get("id") != str(version_id):
            raise AgentError("TENANT_SCOPE_VIOLATION", "canonical version is outside this organization")
        if source.get("status") == "withdrawn" or source.get("freshness_status") == "withdrawn":
            raise AgentError("CANONICAL_VERSION_WITHDRAWN", "withdrawn canonical version cannot be transformed")
        content_hash = source.get("content_hash")
        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", content_hash):
            raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical content hash is invalid")
        content_id = _uuid(source.get("canonical_content_id"), "canonical_content_id")
        raw_sections = source.get("sections")
        if not isinstance(raw_sections, Sequence) or isinstance(raw_sections, (str, bytes)) or not raw_sections:
            raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical version has no sections")
        sections: list[dict[str, Any]] = []
        keys: set[str] = set()
        for item in sorted(raw_sections, key=lambda row: (row.get("position", 0), row.get("key", ""))):
            if not isinstance(item, Mapping):
                raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical section must be an object")
            source_key = item.get("key")
            content = item.get("content")
            if not isinstance(source_key, str) or not source_key or source_key in keys:
                raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical section key is invalid")
            if not isinstance(content, str) or not content:
                raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical section content must be text")
            if type(item.get("position")) is not int or item["position"] < 1:
                raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical section position is invalid")
            claim = item.get("claim_id")
            if claim is not None:
                claim = str(_uuid(claim, "section.claim_id"))
            block_id = item.get("block_id") or source_key
            if not isinstance(block_id, str) or not block_id:
                raise AgentError("TRANSFORM_SOURCE_INVALID", "canonical block_id is invalid")
            keys.add(source_key)
            sections.append({
                "source_key": source_key, "block_id": block_id, "position": item["position"],
                "source_text": content, "claim_id": claim,
            })
        by_key = {section["source_key"]: section for section in sections}
        protected: list[dict[str, Any]] = []
        for term in terms:
            section = by_key.get(term["source_key"])
            if section is None or term["source_term"] not in section["source_text"]:
                raise AgentError("TRANSFORM_TERM_NOT_IN_SOURCE", "terminology source term is not present in its section")
            protected.append({
                "mapping_key": term["term_key"], "source_key": term["source_key"], "kind": "term",
                "source_value": term["source_term"], "target_value": term["target_term"],
                "occurrence_count": section["source_text"].count(term["source_term"]),
            })
        counters: list[tuple[str, str, re.Pattern[str]]] = [
            ("number", "number", _NUMBER_RE), ("code", "code", _CODE_RE), ("link", "link", _LINK_RE),
        ]
        index = 0
        for kind, prefix, pattern in counters:
            for section in sections:
                counts = Counter(pattern.findall(section["source_text"]))
                for token in dict.fromkeys(pattern.findall(section["source_text"])):
                    count = counts[token]
                    if not token:
                        continue
                    index += 1
                    protected.append({
                        "mapping_key": f"{prefix}_{index}", "source_key": section["source_key"],
                        "kind": kind, "source_value": token, "target_value": token,
                        "occurrence_count": count,
                    })
        context = {
            "canonical_content_id": str(content_id), "canonical_content_version_id": str(version_id),
            "source_content_hash": content_hash.lower(), "title": _text(source.get("title"), "source.title", 512),
            "abstract": source.get("abstract", "") if isinstance(source.get("abstract", ""), str) else "",
            "sections": sections, "protected_tokens": protected,
        }
        return context, sections, protected

    @staticmethod
    def _validate_output(
        output: Mapping[str, Any], expected: list[dict[str, Any]], sections: list[dict[str, Any]],
    ) -> None:
        errors = sorted(_OUTPUT_VALIDATOR.iter_errors(output), key=lambda error: list(error.path))
        if errors:
            raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", errors[0].message)
        blocks = output["blocks"]
        if len(blocks) != len(sections):
            raise AgentError("TRANSFORM_PROTECTED_MAPPING_INVALID", "transform changed the source block count")
        for section, block in zip(sections, blocks, strict=True):
            if (
                block["block_id"] != section["block_id"]
                or block["source_key"] != section["source_key"]
                or block["claim_id"] != section["claim_id"]
            ):
                raise AgentError("TRANSFORM_CLAIM_MAPPING_INVALID", "transform changed Claim or source mapping")
        supplied = output["preservation_map"]
        expected_by_key = {item["mapping_key"]: item for item in expected}
        supplied_by_key = {item["mapping_key"]: item for item in supplied}
        if len(supplied_by_key) != len(supplied) or set(supplied_by_key) != set(expected_by_key):
            raise AgentError("TRANSFORM_PROTECTED_MAPPING_INVALID", "transform added, removed, or duplicated protected mappings")
        for key, item in supplied_by_key.items():
            if item != expected_by_key[key]:
                raise AgentError("TRANSFORM_PROTECTED_MAPPING_INVALID", "transform changed a protected mapping")
        text_by_key = {block["source_key"]: block["localized_text"] for block in blocks}
        for item in expected:
            text = text_by_key[item["source_key"]]
            if text.count(item["target_value"]) < item["occurrence_count"]:
                raise AgentError("TRANSFORM_PROTECTED_TOKEN_MISSING", "localized text dropped a protected token")

    @staticmethod
    def _draft(
        *, tenant: UUID, actor: UUID, trace: str, source: Mapping[str, Any],
        version_id: UUID, target: Mapping[str, str], output: Mapping[str, Any],
        sections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        content_id = str(_uuid(source["canonical_content_id"], "canonical_content_id"))
        blocks = []
        for section, block in zip(sections, output["blocks"], strict=True):
            blocks.append({
                "block_id": block["block_id"], "source_key": block["source_key"],
                "source_text_hash": _hash(section["source_text"]),
                "localized_text": block["localized_text"], "claim_id": block["claim_id"],
                "disclosure": block["disclosure"],
            })
        material = {
            "org_id": str(tenant), "canonical_content_id": content_id,
            "canonical_content_version_id": str(version_id),
            "source_content_hash": str(source["content_hash"]).lower(),
            "locale": target["locale"], "market": target["market"],
            "audience": target["audience"], "tone": target["tone"],
            "title": output["title"], "abstract": output["abstract"], "blocks": blocks,
            "transform_mode": "agent_candidate",
        }
        draft = {
            "id": str(uuid4()), **material, "status": "draft", "needs_review": True,
            "draft_hash": _hash(material), "created_by": str(actor), "trace_id": trace,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        }
        errors = sorted(_DRAFT_VALIDATOR.iter_errors(draft), key=lambda error: list(error.path))
        if errors:
            raise AgentError("TRANSFORM_DRAFT_INVALID", errors[0].message)
        return draft

    def _event(
        self, *, tenant: UUID, actor: UUID, trace: str, key: str, run_id: UUID,
        status: str, output_hash: str | None, occurred_at: str,
    ) -> dict[str, Any]:
        payload = {
            "aggregate_id": str(run_id), "aggregate_version": 1,
            "from_state": "running", "to_state": status,
            "command": "transform_variant_draft", "snapshot_hash": output_hash,
            "reason": "candidate Variant draft requires human review before persistence or approval",
            "agent_key": "transform", "draft_only": True,
            "content_variant_created": False, "variant_version_created": False,
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
            raise AgentError("TRANSFORM_EVENT_INVALID", errors[0].message)
        self.events.append(deepcopy(event))
        return event


__all__ = ["CanonicalVersionPort", "INPUT_REF", "INPUT_SCHEMA", "OUTPUT_REF", "OUTPUT_SCHEMA", "TransformAgent", "TransformModelRequest"]
