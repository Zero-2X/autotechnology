"""Deterministic fake/manual observation recommendations for FEEDBACK-CORE-002."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from modules.feedback.core.contracts import (
    ContractError,
    FeedbackItem,
    RefreshRecommendation,
    validate_observation,
    validate_scoring_version,
)


_ROOT = Path(__file__).resolve().parents[3]
_EVENT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class FeedbackRecommendationError(ValueError):
    """Stable errors for observation ingestion and recommendation scoring."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise FeedbackRecommendationError("INVALID_FEEDBACK_INPUT", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedbackRecommendationError("INVALID_FEEDBACK_INPUT", f"{name} must be nonempty text")
    text = value.strip()
    if len(text) > limit:
        raise FeedbackRecommendationError("INVALID_FEEDBACK_INPUT", f"{name} is too long")
    return text


class FeedbackRecommendationService:
    """Record account-free observations and propose explainable local actions."""

    rule_version = "feedback-core-002/v1"
    _RULES = {
        "stale_days": ("refresh", "greater_or_equal", "stale_days_threshold", 30.0),
        "freshness_score": ("refresh", "less_or_equal", "freshness_score_threshold", 0.5),
        "refresh_required": ("refresh", "equals", "refresh_required", True),
        "priority_score_delta": ("reprioritize", "absolute_greater_or_equal", "priority_delta_threshold", 0.2),
        "opportunity_score": ("reprioritize", "greater_or_equal", "opportunity_score_threshold", 0.8),
        "reprioritize_required": ("reprioritize", "equals", "reprioritize_required", True),
    }

    def __init__(self) -> None:
        self.observations: dict[tuple[str, str], dict[str, Any]] = {}
        self.feedback_items: dict[tuple[str, str], dict[str, Any]] = {}
        self.recommendations: dict[tuple[str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._results: dict[tuple[str, str], dict[str, Any]] = {}
        self._dedupe: dict[tuple[str, str], str] = {}
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def record_and_recommend(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, observation: Mapping[str, Any],
        scoring_version: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one immutable observation and optionally propose an action."""

        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(observation, Mapping) or not isinstance(scoring_version, Mapping):
            raise FeedbackRecommendationError("INVALID_FEEDBACK_INPUT", "observation and scoring_version must be objects")
        try:
            observed = validate_observation(deepcopy(dict(observation)))
            scoring = validate_scoring_version(deepcopy(dict(scoring_version)))
        except ContractError as exc:
            raise FeedbackRecommendationError(exc.code, str(exc)) from exc
        if observed["org_id"] != tenant or scoring["org_id"] != tenant:
            raise FeedbackRecommendationError("TENANT_SCOPE_VIOLATION", "feedback inputs are outside this organization")
        if observed["source"] not in {"fake", "manual"}:
            raise FeedbackRecommendationError("SOURCE_NOT_ALLOWED", "M1 recommendations accept only fake or manual observations")
        if not scoring["active"]:
            raise FeedbackRecommendationError("SCORING_VERSION_INACTIVE", "recommendations require an active scoring version")
        digest = _hash({"operation": "record_and_recommend", "observation": observed, "scoring_version": scoring})
        dedupe_identity = (tenant, observed["dedupe_key"])
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise FeedbackRecommendationError("IDEMPOTENCY_KEY_REUSED", "feedback command differs from prior request")
                return deepcopy(prior[1])
            prior_digest = self._dedupe.get(dedupe_identity)
            if prior_digest is not None:
                if prior_digest != digest:
                    raise FeedbackRecommendationError("OBSERVATION_DEDUPE_CONFLICT", "observation dedupe key contains another payload")
                result = deepcopy(self._results[dedupe_identity])
                self._commands[(tenant, key)] = (digest, deepcopy(result))
                return result

            observation_id = observed["id"]
            observed_event = self._event(
                event_type="observation.recorded", tenant=tenant, actor=actor, trace=trace,
                key=f"{key}:observation", aggregate_type="Observation", aggregate_id=observation_id,
                payload={"source": observed["source"], "metric_name": observed["metric_name"],
                         "subject_id": observed["subject_id"], "data_quality": observed["data_quality"]},
                occurred_at=observed["observed_at"],
            )
            decision = self._evaluate(observed, scoring)
            feedback_contract: dict[str, Any] | None = None
            recommendation_contract: dict[str, Any] | None = None
            recommendation_event: dict[str, Any] | None = None
            if decision is not None:
                feedback_id = uuid5(NAMESPACE_URL, f"feedback:{tenant}:{observed['dedupe_key']}:{scoring['id']}")
                reasoning = {
                    "rule_version": self.rule_version, "scoring_version_id": scoring["id"],
                    "scoring_version": scoring["version"], "source": observed["source"],
                    "metric_name": observed["metric_name"], "metric_value": observed["metric_value"],
                    "comparison": decision["comparison"], "threshold": decision["threshold"],
                    "target_id": observed["subject_id"], "evidence": decision["evidence"],
                }
                confidence = decision["confidence"]
                feedback = FeedbackItem.create(
                    id=feedback_id, org_id=tenant, observation_ids=[observation_id],
                    problem=decision["problem"], recommendation_type=decision["recommendation_type"],
                    impact="high" if confidence >= 0.85 else "medium",
                    priority="urgent" if confidence >= 0.95 else "high" if confidence >= 0.75 else "medium",
                    confidence=confidence, reasoning_snapshot=reasoning, owner_actor_id=None,
                    due_at=None, approver_id=None, expires_at=None, created_action_id=None,
                    status="proposed", created_at=observed["observed_at"],
                )
                feedback_contract = feedback.as_contract()
                recommendation = RefreshRecommendation.create(
                    id=uuid5(NAMESPACE_URL, f"recommendation:{feedback_id}"), org_id=tenant,
                    feedback_item_id=feedback_id, recommendation_type=decision["recommendation_type"],
                    target_id=observed["subject_id"], confidence=confidence,
                    status="proposed", created_at=observed["observed_at"],
                )
                recommendation_contract = recommendation.as_contract()
                recommendation_event = self._event(
                    event_type="feedback.recommendation_created", tenant=tenant, actor=actor, trace=trace,
                    key=f"{key}:recommendation", aggregate_type="FeedbackItem",
                    aggregate_id=str(feedback_id), payload={"recommendation_type": decision["recommendation_type"],
                                                           "target_id": observed["subject_id"],
                                                           "confidence": confidence},
                    occurred_at=observed["observed_at"],
                )
                self.feedback_items[(tenant, str(feedback_id))] = deepcopy(feedback_contract)
                self.recommendations[(tenant, recommendation_contract["id"])] = deepcopy(recommendation_contract)

            self.observations[(tenant, observation_id)] = deepcopy(observed)
            result = {
                "observation": deepcopy(observed), "feedback_item": deepcopy(feedback_contract),
                "recommendation": deepcopy(recommendation_contract),
                "events": [observed_event] + ([recommendation_event] if recommendation_event else []),
                "production_rules_mutated": False, "action_created": False,
            }
            self._dedupe[dedupe_identity] = digest
            self._results[dedupe_identity] = deepcopy(result)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self.audit.append({
                "event_type": "feedback.observation.evaluated", "org_id": tenant, "actor_id": actor,
                "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                "output_hash": _hash(result), "scoring_version_id": scoring["id"],
                "rule_version": self.rule_version, "recommendation_type": decision["recommendation_type"] if decision else None,
                "production_rules_mutated": False,
            })
            return deepcopy(result)

    ingest = record_and_recommend
    evaluate = record_and_recommend

    def _evaluate(self, observation: Mapping[str, Any], scoring: Mapping[str, Any]) -> dict[str, Any] | None:
        if observation["data_quality"] == "raw":
            return None
        rule = self._RULES.get(observation["metric_name"])
        if rule is None:
            return None
        recommendation_type, comparison, weight_name, default_threshold = rule
        threshold = scoring["weights"].get(weight_name, default_threshold)
        value = observation["metric_value"]
        if comparison == "equals":
            triggered = type(value) is bool and value is threshold
            confidence = 0.95
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(threshold, bool):
                return None
            numeric, limit = float(value), float(threshold)
            if comparison == "greater_or_equal":
                triggered = numeric >= limit
                distance = max(0.0, numeric - limit) / max(abs(limit), 1.0)
            elif comparison == "less_or_equal":
                triggered = numeric <= limit
                distance = max(0.0, limit - numeric) / max(abs(limit), 1.0)
            else:
                triggered = abs(numeric) >= limit
                distance = max(0.0, abs(numeric) - limit) / max(abs(limit), 1.0)
            confidence = min(0.95, 0.7 + min(0.25, distance * 0.25))
        if not triggered:
            return None
        if observation["data_quality"] == "estimated":
            confidence *= 0.8
        confidence = round(confidence, 4)
        symbol = {"greater_or_equal": ">=", "less_or_equal": "<=",
                  "absolute_greater_or_equal": "absolute >=", "equals": "=="}[comparison]
        return {
            "recommendation_type": recommendation_type, "comparison": comparison, "threshold": threshold,
            "confidence": confidence,
            "problem": f"{observation['metric_name']} triggered a {recommendation_type} review",
            "evidence": [
                f"metric {observation['metric_name']}={observation['metric_value']}",
                f"rule {symbol} {threshold}",
                f"source {observation['source']} with {observation['data_quality']} quality",
            ],
        }

    def _event(self, *, event_type: str, tenant: str, actor: str, trace: str, key: str,
               aggregate_type: str, aggregate_id: str, payload: Mapping[str, Any], occurred_at: str) -> dict[str, Any]:
        event_payload = {"aggregate_id": aggregate_id, "aggregate_version": 1, **dict(payload)}
        event = {
            "event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
            "occurred_at": occurred_at, "org_id": tenant, "trace_id": trace,
            "aggregate_type": aggregate_type, "aggregate_id": aggregate_id, "aggregate_version": 1,
            "actor_type": "user", "actor_id": actor, "idempotency_key": key,
            "payload": event_payload, "payload_hash": _hash(event_payload),
        }
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise FeedbackRecommendationError("INVALID_FEEDBACK_EVENT", errors[0].message)
        self.events.append(deepcopy(event))
        return event


__all__ = ["FeedbackRecommendationError", "FeedbackRecommendationService"]
