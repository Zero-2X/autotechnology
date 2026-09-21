"""Account-free feedback contracts with schema-backed validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "packages" / "contracts" / "jsonschema"


class ContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _validate(value: Mapping[str, Any], schema_name: str) -> dict[str, Any]:
    candidate = dict(value)
    errors = sorted(Draft202012Validator(_schema(schema_name), format_checker=FormatChecker()).iter_errors(candidate), key=lambda item: list(item.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "contract"
        raise ContractError("INVALID_CONTRACT", f"{location}: {errors[0].message}")
    return candidate


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(value))
    except (TypeError, ValueError) as exc:
        raise ContractError("INVALID_CONTRACT", f"{name} must be a UUID") from exc


def _timestamp(value: datetime | str, name: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ContractError("INVALID_CONTRACT", f"{name} must include a timezone")
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ContractError("INVALID_CONTRACT", f"{name} is required")
    return value


@dataclass(frozen=True)
class Observation:
    id: UUID
    org_id: UUID
    source: str
    subject_type: str
    subject_id: UUID
    metric_definition_id: UUID
    metric_definition_version_no: int
    metric_name: str
    metric_type: str
    metric_value: Any
    observed_at: str
    locale: str | None
    region: str | None
    data_quality: str
    dedupe_key: str
    source_snapshot_ref: str | None
    observation_version: int

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "source": self.source,
                "subject_type": self.subject_type, "subject_id": str(self.subject_id),
                "metric_definition_id": str(self.metric_definition_id),
                "metric_definition_version_no": self.metric_definition_version_no,
                "metric_name": self.metric_name, "metric_type": self.metric_type,
                "metric_value": self.metric_value, "observed_at": self.observed_at,
                "locale": self.locale, "region": self.region, "data_quality": self.data_quality,
                "dedupe_key": self.dedupe_key, "source_snapshot_ref": self.source_snapshot_ref,
                "observation_version": self.observation_version}

    @classmethod
    def create(cls, *, id: UUID | str, org_id: UUID | str, source: str, subject_type: str,
               subject_id: UUID | str, metric_definition_id: UUID | str,
               metric_definition_version_no: int, metric_name: str, metric_type: str,
               metric_value: Any, observed_at: datetime | str, locale: str | None,
               region: str | None, data_quality: str, dedupe_key: str,
               source_snapshot_ref: str | None, observation_version: int = 1) -> "Observation":
        value = {"id": _uuid(id, "id"), "org_id": _uuid(org_id, "org_id"), "source": source,
                 "subject_type": subject_type, "subject_id": _uuid(subject_id, "subject_id"),
                 "metric_definition_id": _uuid(metric_definition_id, "metric_definition_id"),
                 "metric_definition_version_no": metric_definition_version_no, "metric_name": metric_name,
                 "metric_type": metric_type, "metric_value": metric_value,
                 "observed_at": _timestamp(observed_at, "observed_at"), "locale": locale, "region": region,
                 "data_quality": data_quality, "dedupe_key": dedupe_key,
                 "source_snapshot_ref": source_snapshot_ref, "observation_version": observation_version}
        _validate(value, "observation.schema.json")
        return cls(id=UUID(value["id"]), org_id=UUID(value["org_id"]), source=source,
                   subject_type=subject_type, subject_id=UUID(value["subject_id"]),
                   metric_definition_id=UUID(value["metric_definition_id"]),
                   metric_definition_version_no=metric_definition_version_no, metric_name=metric_name,
                   metric_type=metric_type, metric_value=metric_value, observed_at=value["observed_at"],
                   locale=locale, region=region, data_quality=data_quality, dedupe_key=dedupe_key,
                   source_snapshot_ref=source_snapshot_ref, observation_version=observation_version)


@dataclass(frozen=True)
class FeedbackItem:
    id: UUID
    org_id: UUID
    observation_ids: tuple[UUID, ...]
    problem: str
    recommendation_type: str
    impact: str
    priority: str
    confidence: float
    reasoning_snapshot: dict[str, Any]
    owner_actor_id: UUID | None
    due_at: str | None
    approver_id: UUID | None
    expires_at: str | None
    created_action_id: UUID | None
    status: str
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "observation_ids": [str(item) for item in self.observation_ids],
                "problem": self.problem, "recommendation_type": self.recommendation_type, "impact": self.impact,
                "priority": self.priority, "confidence": self.confidence, "reasoning_snapshot": self.reasoning_snapshot,
                "owner_actor_id": str(self.owner_actor_id) if self.owner_actor_id else None,
                "due_at": self.due_at, "approver_id": str(self.approver_id) if self.approver_id else None,
                "expires_at": self.expires_at, "created_action_id": str(self.created_action_id) if self.created_action_id else None,
                "status": self.status, "created_at": self.created_at}

    @classmethod
    def create(cls, *, id: UUID | str, org_id: UUID | str, observation_ids: list[UUID | str], problem: str,
               recommendation_type: str, impact: str, priority: str, confidence: float,
               reasoning_snapshot: dict[str, Any], owner_actor_id: UUID | str | None,
               due_at: datetime | str | None, approver_id: UUID | str | None,
               expires_at: datetime | str | None, created_action_id: UUID | str | None,
               status: str, created_at: datetime | str) -> "FeedbackItem":
        value = {"id": _uuid(id, "id"), "org_id": _uuid(org_id, "org_id"),
                 "observation_ids": [_uuid(item, "observation_id") for item in observation_ids],
                 "problem": problem, "recommendation_type": recommendation_type, "impact": impact,
                 "priority": priority, "confidence": confidence, "reasoning_snapshot": reasoning_snapshot,
                 "owner_actor_id": _uuid(owner_actor_id, "owner_actor_id") if owner_actor_id else None,
                 "due_at": _timestamp(due_at, "due_at") if due_at else None,
                 "approver_id": _uuid(approver_id, "approver_id") if approver_id else None,
                 "expires_at": _timestamp(expires_at, "expires_at") if expires_at else None,
                 "created_action_id": _uuid(created_action_id, "created_action_id") if created_action_id else None,
                 "status": status, "created_at": _timestamp(created_at, "created_at")}
        if not 0 <= float(confidence) <= 1:
            raise ContractError("INVALID_CONTRACT", "confidence must be between zero and one")
        _validate(value, "feedback-item.schema.json")
        return cls(UUID(value["id"]), UUID(value["org_id"]), tuple(UUID(item) for item in value["observation_ids"]),
                   problem, recommendation_type, impact, priority, float(confidence), dict(reasoning_snapshot),
                   UUID(value["owner_actor_id"]) if value["owner_actor_id"] else None, value["due_at"],
                   UUID(value["approver_id"]) if value["approver_id"] else None, value["expires_at"],
                   UUID(value["created_action_id"]) if value["created_action_id"] else None, status, value["created_at"])


@dataclass(frozen=True)
class RefreshRecommendation:
    id: UUID
    org_id: UUID
    feedback_item_id: UUID
    recommendation_type: str
    target_id: UUID
    confidence: float
    status: str
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "feedback_item_id": str(self.feedback_item_id),
                "recommendation_type": self.recommendation_type, "target_id": str(self.target_id),
                "confidence": self.confidence, "status": self.status, "created_at": self.created_at}

    @classmethod
    def create(cls, *, id: UUID | str, org_id: UUID | str, feedback_item_id: UUID | str,
               recommendation_type: str, target_id: UUID | str, confidence: float,
               status: str, created_at: datetime | str) -> "RefreshRecommendation":
        value = {"id": _uuid(id, "id"), "org_id": _uuid(org_id, "org_id"),
                 "feedback_item_id": _uuid(feedback_item_id, "feedback_item_id"),
                 "recommendation_type": recommendation_type, "target_id": _uuid(target_id, "target_id"),
                 "confidence": confidence, "status": status, "created_at": _timestamp(created_at, "created_at")}
        _validate(value, "refresh-recommendation.schema.json")
        return cls(UUID(value["id"]), UUID(value["org_id"]), UUID(value["feedback_item_id"]),
                   recommendation_type, UUID(value["target_id"]), float(confidence), status, value["created_at"])


@dataclass(frozen=True)
class FeedbackScoringVersion:
    id: UUID
    org_id: UUID
    version: int
    algorithm: str
    weights: dict[str, float]
    active: bool
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "version": self.version,
                "algorithm": self.algorithm, "weights": self.weights, "active": self.active,
                "created_at": self.created_at}


def validate_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate(value, "observation.schema.json")


def validate_feedback_item(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate(value, "feedback-item.schema.json")


def validate_scoring_version(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate(value, "feedback-scoring-version.schema.json")


def validate_refresh_recommendation(value: Mapping[str, Any]) -> dict[str, Any]:
    return _validate(value, "refresh-recommendation.schema.json")
