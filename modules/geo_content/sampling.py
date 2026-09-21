"""Deterministic, account-free compliance sampling for GEO_CONTENT-002.

This module defines the sampling *port* and a pure offline adapter.  It never
opens a socket, resolves a provider, or treats an unverified external answer
as a fact.  Callers provide a captured answer (or an explicit unknown result),
and the adapter records mentions, citations, position, and correctness in a
replayable result.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid5

from .fixtures import (
    GeoQueryFixtureError,
    GeoQueryFixtureService,
    InMemoryGeoQueryFixtureStore,
    _HASH_RE,
    _hash,
    _if_match,
    _policy_hash,
    _resolve_tenant,
    _stamp,
    _text,
    _uuid,
    validate_fixture_integrity,
    validate_predecessors,
    _safe_tenant,
)


_SAMPLE_NAMESPACE = UUID("51d7f91d-63f5-5d6a-b4ef-6d33a0a0c772")
_URL_RE = re.compile(r"https?://[^\s<>\]\[(){}\"']+", re.IGNORECASE)
_UNKNOWN_STATES = frozenset({
    "unknown", "unavailable", "pending", "timeout", "error", "failed", "not_collected",
    "manual_review", "review", "requires_review", "needs_review",
})
_CORRECT = frozenset({"correct", "verified", "pass", "true", "yes", "1"})
_INCORRECT = frozenset({"incorrect", "invalid", "fail", "false", "no", "0"})


class GeoComplianceSamplingError(GeoQueryFixtureError):
    """Stable error for sampling command validation."""


class ComplianceSamplingPort(Protocol):
    """Provider-neutral port; implementations must not perform network I/O."""

    parser_version: str

    def sample(
        self,
        *,
        fixture: Mapping[str, Any],
        result: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
    ) -> Mapping[str, Any]: ...


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _stamp_now(value: Any = None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "created_at must include a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return _text(value, "created_at", maximum=64)


def _answer_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    if not isinstance(result, Mapping):
        return ""
    for name in ("answer", "text", "content", "response", "body", "output"):
        value = result.get(name)
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, Mapping):
            nested = _answer_text(value)
            if nested:
                return nested
    return ""


def _result_state(result: Any) -> str | None:
    if not isinstance(result, Mapping):
        return None
    value = result.get("status", result.get("state", result.get("result_status")))
    return value.strip().lower() if isinstance(value, str) else None


def _explicit_unknown(result: Any) -> bool:
    if result is None:
        return True
    if isinstance(result, Mapping):
        if result.get("manual_review") is True or result.get("review_required") is True:
            return True
        state = _result_state(result)
        if state in _UNKNOWN_STATES:
            return True
        if result.get("unknown") is True or result.get("external_result_unknown") is True:
            return True
    return False


def _contains_entity(text: str, entity: str) -> bool:
    if not entity:
        return False
    # Word boundaries are useful for ASCII names but break for CJK.  Use a
    # boundary only when both edges are word characters; otherwise exact
    # case-folded containment is the deterministic and locale-safe fallback.
    folded = text.casefold()
    target = entity.casefold()
    if target not in folded:
        return False
    if not (target[0].isalnum() and target[-1].isalnum()):
        return True
    start = folded.find(target)
    end = start + len(target)
    left = folded[start - 1] if start else " "
    right = folded[end] if end < len(folded) else " "
    return not (left.isalnum() or left == "_") and not (right.isalnum() or right == "_")


def _normalize_citations(result: Any, text: str) -> list[dict[str, Any]]:
    values: Any = result.get("citations", result.get("references", result.get("sources", []))) if isinstance(result, Mapping) else []
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Sequence):
        values = []
    citations: list[dict[str, Any]] = []
    for index, value in enumerate(values, start=1):
        if isinstance(value, Mapping):
            ref = value.get("url", value.get("ref", value.get("source_ref", value.get("id"))))
            position = value.get("position", value.get("rank", index))
            quote = value.get("quote", value.get("quoted_text"))
        else:
            ref = value
            position = index
            quote = None
        if ref is None:
            continue
        try:
            position_value = int(position)
        except (TypeError, ValueError):
            position_value = index
        if position_value < 1:
            position_value = index
        citation: dict[str, Any] = {
            "ref": _text(ref, "citations[].ref", maximum=2048),
            "position": position_value,
        }
        if quote is not None:
            citation["quote"] = _text(quote, "citations[].quote", maximum=4096)
        citations.append(citation)
    if not citations:
        for index, match in enumerate(_URL_RE.findall(text), start=1):
            citations.append({"ref": match.rstrip(".,;"), "position": index})
    return citations


def _explicit_correctness(result: Any) -> tuple[str | None, float | None]:
    if not isinstance(result, Mapping):
        return None, None
    value = result.get("correctness", result.get("is_correct"))
    score = result.get("correctness_score", result.get("accuracy"))
    score_value: float | None = None
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        score_value = max(0.0, min(1.0, float(score)))
    if isinstance(value, bool):
        return ("correct" if value else "incorrect"), (1.0 if value else 0.0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        score_value = max(0.0, min(1.0, float(value)))
        return ("correct" if score_value >= 0.5 else "incorrect"), score_value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _CORRECT:
            return "correct", 1.0 if score_value is None else score_value
        if normalized in _INCORRECT:
            return "incorrect", 0.0 if score_value is None else score_value
        if normalized in _UNKNOWN_STATES or normalized in {"unknown", "manual_review", "review"}:
            return "unknown", score_value
    return None, score_value


def _validate_sample_output(value: Mapping[str, Any]) -> None:
    """Fail closed when a sampling adapter violates the stable result shape."""

    if value.get("status") not in {"pass", "fail", "manual_review"}:
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler returned an invalid status")
    if value.get("correctness") not in {"correct", "incorrect", "unknown"}:
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler returned invalid correctness")
    if not isinstance(value.get("mentioned"), bool):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler mentioned must be boolean")
    if not isinstance(value.get("review_required"), bool):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler review_required must be boolean")
    if value["review_required"] != (value["status"] == "manual_review"):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler review status is inconsistent")
    if not isinstance(value.get("unknown_external_result"), bool):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler unknown flag must be boolean")
    mentions = value.get("mentions")
    citations = value.get("citations")
    positions = value.get("positions")
    if not isinstance(mentions, list) or any(
        not isinstance(item, Mapping)
        or not isinstance(item.get("entity"), str)
        or not item.get("entity")
        or not isinstance(item.get("mentioned"), bool)
        for item in mentions
    ):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler mentions are invalid")
    if not isinstance(citations, list) or any(
        not isinstance(item, Mapping)
        or not isinstance(item.get("ref"), str)
        or not item.get("ref")
        or not isinstance(item.get("position"), int)
        or isinstance(item.get("position"), bool)
        or item["position"] < 1
        for item in citations
    ):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler citations are invalid")
    if not isinstance(positions, list) or any(
        not isinstance(item, int) or isinstance(item, bool) or item < 1 for item in positions
    ):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler positions are invalid")
    if value.get("mention_count") != sum(1 for item in mentions if item["mentioned"]):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler mention count is inconsistent")
    if value.get("citation_count") != len(citations):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler citation count is inconsistent")
    if positions != [item["position"] for item in citations]:
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler citation positions are inconsistent")
    position = value.get("position")
    if position is not None and (
        not isinstance(position, int) or isinstance(position, bool) or position < 1
    ):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler position is invalid")
    score = value.get("correctness_score")
    if score is not None and (
        not isinstance(score, (int, float)) or isinstance(score, bool) or not 0.0 <= float(score) <= 1.0
    ):
        raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "sampler correctness score is invalid")
    for field in ("fixture_hash", "input_hash", "output_hash"):
        raw = value.get(field)
        if not isinstance(raw, str) or _HASH_RE.fullmatch(raw) is None:
            raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", f"sampler {field} is invalid")
    _text(value.get("parser_version"), "sampler.parser_version", maximum=64)
    for field in ("fixture_version", "duration_ms", "cost_cents"):
        raw = value.get(field)
        minimum = 1 if field == "fixture_version" else 0
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < minimum:
            raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", f"sampler {field} is invalid")


class DeterministicComplianceSampler:
    """Pure parser/evaluator for a captured answer.

    The adapter accepts a result supplied by a caller.  It does not fetch a
    URL referenced by a citation and does not infer an external answer when no
    result is available; that case is explicitly routed to manual review.
    """

    parser_version = "geo-compliance-002.v1"

    def __init__(self, *, parser_version: str | None = None, cost_cents: int = 0) -> None:
        self.parser_version = _text(parser_version, "parser_version", maximum=64) if parser_version else self.parser_version
        self.cost_cents = max(0, int(cost_cents))

    def sample(
        self,
        *,
        fixture: Mapping[str, Any],
        result: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
    ) -> Mapping[str, Any]:
        try:
            validate_fixture_integrity(fixture, predecessor_artifacts=predecessor_artifacts)
        except GeoQueryFixtureError as error:
            raise GeoComplianceSamplingError(
                "INVALID_GEO_SAMPLE", str(error), details={"cause": error.code}
            ) from error
        fixture_id = _text(fixture.get("id"), "fixture.id", maximum=128)
        org_id = _text(fixture.get("org_id"), "fixture.org_id", maximum=128)
        query = _text(fixture.get("query", fixture.get("prompt")), "fixture.query", maximum=4096)
        locale = _text(fixture.get("locale"), "fixture.locale", maximum=32)
        region = _text(fixture.get("region"), "fixture.region", maximum=128)
        if predecessor_artifacts is not None:
            validate_predecessors(predecessor_artifacts, org_id=org_id)
        text = _answer_text(result)
        unknown = _explicit_unknown(result)
        entities = fixture.get("expected_entities", [])
        if isinstance(entities, (str, bytes)) or not isinstance(entities, Sequence):
            raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", "fixture.expected_entities must be an array")
        mentions = [
            {"entity": _text(entity, "expected_entities[]", maximum=512), "mentioned": _contains_entity(text, str(entity))}
            for entity in entities
        ]
        mentioned = any(item["mentioned"] for item in mentions)
        citations = _normalize_citations(result, text)
        position: int | None = None
        if isinstance(result, Mapping):
            raw_position = result.get("position", result.get("rank", result.get("answer_position")))
            if raw_position is not None:
                try:
                    position = int(raw_position)
                except (TypeError, ValueError):
                    position = None
                if position is not None and position < 1:
                    position = None
        if position is None and citations:
            position = min(item["position"] for item in citations)
        explicit_correctness, score = _explicit_correctness(result)
        if unknown:
            correctness = "unknown"
            review_reason = "external result is unknown or unavailable"
        elif explicit_correctness is not None:
            correctness = explicit_correctness
            if correctness == "unknown":
                unknown = True
                review_reason = "captured result correctness is unknown"
            else:
                review_reason = None
        elif not text:
            correctness = "unknown"
            unknown = True
            review_reason = "captured result has no answer text"
        elif mentioned and (citations or not fixture.get("expected_claim_ids")):
            correctness = "correct"
            score = 1.0 if score is None else score
            review_reason = None
        elif mentioned:
            correctness = "unknown"
            review_reason = "mention has no claim citation"
            unknown = True
        else:
            correctness = "incorrect"
            score = 0.0 if score is None else score
            review_reason = None
        status = "manual_review" if unknown or correctness == "unknown" else ("pass" if correctness == "correct" else "fail")
        policy_hash = _policy_hash(policy_snapshot)
        input_payload = {
            "fixture_id": fixture_id,
            "fixture_hash": fixture.get("fixture_hash"),
            "result": deepcopy(result),
            "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
            "policy_snapshot_hash": policy_hash,
        }
        input_hash = _hash(input_payload)
        output_payload = {
            "fixture_id": fixture_id,
            "org_id": org_id,
            "query": query,
            "locale": locale,
            "region": region,
            "mentioned": mentioned,
            "mentions": mentions,
            "citations": citations,
            "position": position,
            "correctness": correctness,
            "correctness_score": score,
            "status": status,
            "review_required": status == "manual_review",
            "review_reason": review_reason,
            "unknown_external_result": unknown,
            "parser_version": self.parser_version,
            "fixture_hash": fixture.get("fixture_hash"),
            "input_hash": input_hash,
            "policy_snapshot_hash": policy_hash,
        }
        sample_id = str(uuid5(_SAMPLE_NAMESPACE, f"{org_id}:{fixture_id}:{input_hash}"))
        output_payload["sample_id"] = sample_id
        output_payload["mention"] = mentioned
        output_payload["mention_count"] = sum(1 for item in mentions if item["mentioned"])
        output_payload["citation_count"] = len(citations)
        output_payload["positions"] = [item["position"] for item in citations]
        output_payload["result_hash"] = _hash(result)
        output_payload["cost_cents"] = self.cost_cents
        output_payload["output_hash"] = _hash(output_payload)
        return output_payload

    evaluate = sample
    run = sample
    parse = sample


class GeoComplianceSamplingService:
    """Tenant/idempotency boundary around a compliance sampling Port."""

    task_id = "GEO_CONTENT-002"

    def __init__(
        self,
        *,
        fixture_service: GeoQueryFixtureService | None = None,
        sampler: ComplianceSamplingPort | None = None,
        clock: Any = None,
    ) -> None:
        self.fixture_service = fixture_service or GeoQueryFixtureService(clock=clock)
        self.store: InMemoryGeoQueryFixtureStore = self.fixture_service.store
        self.sampler = sampler or DeterministicComplianceSampler()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    def _reject(self, error: GeoQueryFixtureError, *, org_id: Any, tenant_context: Mapping[str, Any] | None, actor_id: Any, trace_id: Any, idempotency_key: Any) -> None:
        tenant = _safe_tenant(org_id, tenant_context)
        try:
            actor = str(actor_id) if actor_id is not None else "00000000-0000-4000-8000-000000000000"
        except Exception:
            actor = "unknown"
        try:
            trace = _text(trace_id or "geo-content-002", "trace_id", maximum=256)
        except GeoQueryFixtureError:
            trace = "geo-content-002"
        self.store.append_audit({
            "event_type": "geo.sample.rejected",
            "task_id": self.task_id,
            "org_id": tenant,
            "actor_id": actor,
            "trace_id": trace,
            "idempotency_key": idempotency_key,
            "aggregate_id": None,
            "input_hash": None,
            "output_hash": None,
            "input_version": None,
            "output_version": None,
            "policy_snapshot_hash": None,
            "status": "rejected",
            "reason": f"{error.code}: {error}",
            "duration_ms": 0,
            "cost_cents": 0,
            "created_at": _stamp_now(self.clock()),
        })

    def sample(
        self,
        *,
        fixture_id: Any = None,
        fixture: Mapping[str, Any] | None = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        result: Any = None,
        answer: Any = None,
        raw_result: Any = None,
        page_version_id: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        allow_created: bool = False,
        **_: Any,
    ) -> dict[str, Any]:
        self._lock.acquire()
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            if fixture is None:
                identity = _uuid(fixture_id, "fixture_id")
                assert identity is not None
                fixture_value = self.store.get_fixture(org_id=tenant, fixture_id=identity)
                if fixture_value is None:
                    if self.store.has_fixture(fixture_id=identity):
                        raise GeoComplianceSamplingError("TENANT_SCOPE_VIOLATION", "fixture is outside this organization")
                    raise GeoComplianceSamplingError("FIXTURE_NOT_FOUND", "fixture does not belong to organization")
            else:
                fixture_value = deepcopy(dict(fixture))
                if _uuid(fixture_value.get("org_id"), "fixture.org_id") != tenant:
                    raise GeoComplianceSamplingError("TENANT_SCOPE_VIOLATION", "fixture is outside this organization")
                identity = _uuid(fixture_value.get("id"), "fixture.id")
                assert identity is not None
            try:
                validate_fixture_integrity(
                    fixture_value,
                    predecessor_artifacts=predecessor_artifacts,
                )
            except GeoQueryFixtureError as error:
                raise GeoComplianceSamplingError("INVALID_GEO_SAMPLE", str(error), details={"cause": error.code}) from error
            if fixture_value.get("status") == "retired":
                raise GeoComplianceSamplingError("FIXTURE_NOT_ACTIVE", "retired fixture cannot be sampled")
            if fixture_value.get("status") == "created" and not allow_created:
                raise GeoComplianceSamplingError("FIXTURE_NOT_ACTIVE", "activate fixture before sampling")
            validate_predecessors(predecessor_artifacts, org_id=tenant)
            supplied_result = result if result is not None else (raw_result if raw_result is not None else answer)
            page_ref = None if page_version_id is None else _text(page_version_id, "page_version_id", maximum=256)
            policy_hash = _policy_hash(policy_snapshot)
            parser_version = _text(
                getattr(self.sampler, "parser_version", None),
                "sampler.parser_version",
                maximum=64,
            )
            request_hash = _hash({
                "command": "sample",
                "fixture_id": identity,
                "fixture_version": fixture_value.get("version", 1),
                "page_version_id": page_ref,
                "result": deepcopy(supplied_result),
                "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
                "policy_snapshot_hash": policy_hash,
                "parser_version": parser_version,
            })
            prior = self.store.get_command(org_id=tenant, idempotency_key=key, namespace="sample")
            if prior is not None:
                if prior.get("request_hash") != request_hash:
                    raise GeoComplianceSamplingError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            try:
                sampled = self.sampler.sample(
                    fixture=fixture_value,
                    result=supplied_result,
                    predecessor_artifacts=predecessor_artifacts,
                    policy_snapshot=policy_snapshot,
                )
                if not isinstance(sampled, Mapping):
                    raise TypeError("sampling port result must be an object")
                parsed = dict(sampled)
            except GeoQueryFixtureError:
                raise
            except Exception as error:
                raise GeoComplianceSamplingError(
                    "SAMPLING_PORT_FAILED", "offline sampling adapter failed"
                ) from error
            if parsed.get("fixture_hash") != fixture_value["fixture_hash"]:
                raise GeoComplianceSamplingError(
                    "INVALID_GEO_SAMPLE", "sampler fixture hash does not match the immutable fixture"
                )
            if parsed.get("parser_version") != parser_version:
                raise GeoComplianceSamplingError(
                    "INVALID_GEO_SAMPLE", "sampler parser version does not match its declared version"
                )
            parsed.update({
                "org_id": tenant,
                "fixture_id": identity,
                "fixture_hash": fixture_value["fixture_hash"],
                "page_version_id": page_ref,
                "trace_id": trace,
                "actor_id": actor,
                "fixture_version": int(fixture_value.get("version", 1)),
                "input_hash": request_hash,
                "policy_snapshot_hash": policy_hash,
                "parser_version": parser_version,
                "created_at": _stamp_now(self.clock()),
                "duration_ms": 0,
            })
            parsed["sample_id"] = str(uuid5(_SAMPLE_NAMESPACE, f"{tenant}:{identity}:{request_hash}"))
            # Recalculate after boundary metadata is attached so the output
            # digest covers exactly what callers receive.
            parsed["output_hash"] = _hash({key: value for key, value in parsed.items() if key != "output_hash"})
            _validate_sample_output(parsed)
            self.store.save_command(org_id=tenant, idempotency_key=key, request_hash=request_hash, response=parsed, namespace="sample")
            audit_event_type = "geo.sample.manual_review" if parsed.get("status") == "manual_review" else "geo.sample.completed"
            self.store.append_audit({
                "event_type": audit_event_type,
                "task_id": self.task_id,
                "org_id": tenant,
                "actor_id": actor,
                "trace_id": trace,
                "idempotency_key": key,
                "aggregate_id": identity,
                "input_hash": request_hash,
                "output_hash": parsed["output_hash"],
                "input_version": fixture_value.get("version", 1),
                "output_version": fixture_value.get("version", 1),
                "policy_snapshot_hash": policy_hash,
                "status": parsed.get("status"),
                "reason": parsed.get("review_reason"),
                "duration_ms": parsed.get("duration_ms", 0),
                "cost_cents": parsed.get("cost_cents", 0),
                "created_at": parsed["created_at"],
            })
            return deepcopy(parsed)
        except GeoQueryFixtureError as error:
            self._reject(error, org_id=org_id, tenant_context=tenant_context, actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key)
            raise
        finally:
            self._lock.release()

    sample_fixture = sample
    collect = sample
    evaluate = sample
    run = sample


# Compatibility names: all aliases remain the same offline implementation.
GeoContentSamplingService = GeoComplianceSamplingService
GeoSamplingService = GeoComplianceSamplingService
ComplianceSamplingService = GeoComplianceSamplingService
OfflineComplianceSampler = DeterministicComplianceSampler
FakeComplianceSampler = DeterministicComplianceSampler
SamplingError = GeoComplianceSamplingError


__all__ = [
    "ComplianceSamplingPort",
    "DeterministicComplianceSampler",
    "OfflineComplianceSampler",
    "FakeComplianceSampler",
    "GeoComplianceSamplingError",
    "SamplingError",
    "GeoComplianceSamplingService",
    "GeoContentSamplingService",
    "GeoSamplingService",
    "ComplianceSamplingService",
]
