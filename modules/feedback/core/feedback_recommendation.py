"""Recommendation-only feedback loop projection for FEEDBACK-CORE-004."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from .feedback_item import FeedbackItemError, _stamp, _text, _uuid

_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/feedback-recommendation.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_NAMESPACE = UUID("65a5ff51-8e02-55be-99d2-f727e68755de")
_EVENT_NAMESPACE = UUID("8d4ed5a2-fd05-5cca-a302-9bc37d79f3ad")


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class FeedbackRecommendationServiceV2:
    """Turn a FeedbackItem into explainable, non-executing recommendations."""

    task_id = "FEEDBACK-CORE-004"
    rule_version = "feedback-core-004.v1"

    def __init__(self, *, clock: Any | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.recommendations: dict[tuple[str, str], dict[str, Any]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self._lock = RLock()

    def recommend(self, *, feedback_item: Mapping[str, Any], context: Mapping[str, Any], idempotency_key: Any,
                  target_type: str | None = None, target_id: Any = None, evidence: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
        tenant = _uuid(context.get("org_id"), "org_id")
        actor = _uuid(context.get("actor_id", "00000000-0000-4000-8000-000000000001"), "actor_id")
        trace = _text(context.get("trace_id", self.task_id), "trace_id", 256)
        key = _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(feedback_item, Mapping) or feedback_item.get("org_id") != tenant:
            raise FeedbackItemError("TENANT_SCOPE_VIOLATION", "feedback item belongs to another organization")
        if feedback_item.get("status") not in {"proposed", "approved"}:
            raise FeedbackItemError("FEEDBACK_NOT_ACTIONABLE", "only proposed or approved feedback can produce recommendations")
        try:
            item_id = _uuid(feedback_item.get("id"), "feedback_item.id")
            confidence = float(feedback_item.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "feedback item is malformed") from exc
        if not 0 <= confidence <= 1:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "feedback confidence must be between zero and one")
        action = feedback_item.get("recommendation_type")
        mapping = {
            "refresh": ("refresh_queue", "refresh"), "reprioritize": ("topic_opportunity", "reprioritize"),
            "revise": ("variant", "variant_strategy"), "channel_change": ("channel", "channel_strategy"),
            "prompt_eval": ("prompt_eval", "prompt_eval"), "retire": ("topic_opportunity", "reprioritize"),
        }
        default_target, rec_type = mapping.get(action, (None, None))
        target = target_type or default_target
        if target not in {"topic_opportunity", "refresh_queue", "variant", "channel", "prompt_eval"}:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "target_type is unsupported")
        target_identity = _uuid(target_id or feedback_item.get("target_id") or feedback_item["observation_ids"][0], "target_id")
        evidence_hash = _hash([dict(row) for row in evidence])
        created = _stamp(self.clock())
        identity = str(uuid5(_NAMESPACE, f"{tenant}:{item_id}:{target}:{target_identity}:{self.rule_version}"))
        result = {"id": identity, "org_id": tenant, "feedback_item_id": item_id, "recommendation_type": rec_type,
                  "target_type": target, "target_id": target_identity, "confidence": round(confidence, 4),
                  "reasoning": {"rule_version": self.rule_version, "evidence_hash": evidence_hash}, "status": "proposed", "created_at": created}
        _VALIDATOR.validate(result)
        digest = _hash({"feedback_item": dict(feedback_item), "target_type": target, "target_id": target_identity, "evidence_hash": evidence_hash})
        with self._lock:
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest:
                    raise FeedbackItemError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            existing = self.recommendations.get((tenant, identity))
            if existing is not None:
                return deepcopy(existing)
            self.recommendations[(tenant, identity)] = deepcopy(result)
            self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(result)}
            payload = {"aggregate_id": identity, "aggregate_version": 1, "feedback_item_id": item_id,
                       "recommendation_type": rec_type, "target_type": target, "target_id": target_identity,
                       "confidence": result["confidence"], "reasoning_hash": _hash(result["reasoning"])}
            self.outbox.append({"event_id": str(uuid5(_EVENT_NAMESPACE, identity)), "event_type": "feedback.recommendation.created",
                                "event_schema_version": 1, "occurred_at": created, "org_id": tenant, "trace_id": trace,
                                "correlation_id": None, "causation_id": None, "aggregate_type": "FeedbackRecommendation",
                                "aggregate_id": identity, "aggregate_version": 1, "actor_type": "user", "actor_id": actor,
                                "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)})
            self.audit.append({"event_type": "feedback.recommendation.created", "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "recommendation_id": identity, "feedback_item_id": item_id,
                               "target_type": target, "target_id": target_identity, "request_hash": digest,
                               "reasoning_hash": _hash(result["reasoning"]), "production_rules_mutated": False, "created_at": created})
            return deepcopy(result)

    create = recommend
    generate = recommend


FeedbackLoopRecommendationService = FeedbackRecommendationServiceV2

__all__ = ["FeedbackRecommendationServiceV2", "FeedbackLoopRecommendationService"]
