"""Synthetic/manual experiment facts for FEEDBACK-EXP-001."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/feedback-experiment.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


class ExperimentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message); self.code = code


def _uuid(value: Any, field: str) -> str:
    try: return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError) as exc: raise ExperimentError("INVALID_EXPERIMENT_INPUT", f"{field} must be a UUID") from exc


def _text(value: Any, field: str, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip(): raise ExperimentError("INVALID_EXPERIMENT_INPUT", f"{field} is required")
    value = value.strip()
    if len(value) > limit: raise ExperimentError("INVALID_EXPERIMENT_INPUT", f"{field} is too long")
    return value


def _stamp(value: Any) -> str:
    if not isinstance(value, datetime):
        try: value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "timestamp is invalid") from exc
    if value.tzinfo is None or value.utcoffset() is None: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "timestamp needs timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str: return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ExperimentService:
    task_id = "FEEDBACK-EXP-001"

    def __init__(self, *, clock: Any | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc)); self.experiments: dict[tuple[str, str], dict[str, Any]] = {}; self.samples: dict[tuple[str, str], list[dict[str, Any]]] = {}; self.commands: dict[tuple[str, str], dict[str, Any]] = {}; self.audit: list[dict[str, Any]] = []; self.outbox: list[dict[str, Any]] = []; self._lock = RLock()

    def _ctx(self, context: Mapping[str, Any]) -> tuple[str, str, str]:
        return _uuid(context.get("org_id"), "org_id"), _uuid(context.get("actor_id", "00000000-0000-4000-8000-000000000001"), "actor_id"), _text(context.get("trace_id", self.task_id), "trace_id", 256)

    def create_experiment(self, *, hypothesis: Any, groups: Sequence[Mapping[str, Any]], metric_keys: Sequence[str], window_start: Any, window_end: Any, sample_target: int, context: Mapping[str, Any], idempotency_key: Any) -> dict[str, Any]:
        tenant, actor, trace = self._ctx(context); key = _text(idempotency_key, "idempotency_key", 200)
        if isinstance(groups, (str, bytes)) or not isinstance(groups, Sequence) or len(groups) < 2: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "at least two groups are required")
        normalized = [{"key": _text(g.get("key"), "group.key", 64).lower(), "label": _text(g.get("label"), "group.label", 256), "allocation_percent": g.get("allocation_percent")} for g in groups]
        if len({g["key"] for g in normalized}) != len(normalized) or sum(g["allocation_percent"] for g in normalized) != 100 or any(type(g["allocation_percent"]) is not int or g["allocation_percent"] < 1 for g in normalized): raise ExperimentError("INVALID_EXPERIMENT_INPUT", "group allocations must be unique positive integers totaling 100")
        start, end = _stamp(window_start), _stamp(window_end)
        if start >= end: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "window_start must precede window_end")
        if type(sample_target) is not int or sample_target < 1: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "sample_target must be positive")
        body = {"hypothesis": _text(hypothesis, "hypothesis", 2000), "groups": normalized, "metric_keys": sorted({_text(k, "metric_key", 128) for k in metric_keys}), "window_start": start, "window_end": end, "sample_target": sample_target}
        if not body["metric_keys"]: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "metric_keys are required")
        digest = _hash(body)
        with self._lock:
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest: raise ExperimentError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            identity = str(uuid4()); result = {"id": identity, "org_id": tenant, **body, "status": "planned", "conclusion": None, "rollback_reason": None, "version": 1, "created_by": actor, "created_at": _stamp(self.clock())}
            _VALIDATOR.validate(result); self.experiments[(tenant, identity)] = deepcopy(result); self.samples[(tenant, identity)] = []; self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(result)}
            self._event("feedback.experiment.created", tenant, actor, trace, key, result, digest); return deepcopy(result)

    create = create_experiment

    def start(self, experiment_id: Any, *, context: Mapping[str, Any], idempotency_key: Any, expected_version: int) -> dict[str, Any]:
        return self._transition(experiment_id, "running", context=context, idempotency_key=idempotency_key, expected_version=expected_version)

    def record_sample(self, experiment_id: Any, *, group_key: str, metrics: Mapping[str, Any], observation_ids: Sequence[Any], source: str, context: Mapping[str, Any], idempotency_key: Any) -> dict[str, Any]:
        tenant, actor, trace = self._ctx(context); identity = _uuid(experiment_id, "experiment_id"); key = _text(idempotency_key, "idempotency_key", 200)
        if source not in {"fake", "manual", "site", "qa", "geo", "support"}: raise ExperimentError("SOURCE_NOT_ALLOWED", "only account-free samples are supported")
        if not isinstance(metrics, Mapping) or not metrics: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "metrics are required")
        sample = {"id": str(uuid4()), "experiment_id": identity, "group_key": _text(group_key, "group_key", 64), "metrics": deepcopy(dict(metrics)), "observation_ids": [_uuid(i, "observation_id") for i in observation_ids], "source": source, "created_at": _stamp(self.clock())}
        digest = _hash(sample | {"id": None})
        with self._lock:
            exp = self.experiments.get((tenant, identity))
            if exp is None: raise ExperimentError("EXPERIMENT_NOT_FOUND", "experiment does not exist")
            if exp["status"] != "running": raise ExperimentError("EXPERIMENT_NOT_RUNNING", "experiment must be running")
            if sample["group_key"] not in {g["key"] for g in exp["groups"]}: raise ExperimentError("INVALID_EXPERIMENT_INPUT", "unknown experiment group")
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest: raise ExperimentError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            self.samples[(tenant, identity)].append(deepcopy(sample)); self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(sample)}; self.audit.append({"event_type": "feedback.experiment.sample_recorded", "org_id": tenant, "actor_id": actor, "trace_id": trace, "experiment_id": identity, "sample_hash": digest, "source": source, "created_at": sample["created_at"]}); return deepcopy(sample)

    sample = record_sample

    def conclude(self, experiment_id: Any, *, winner: str | None, summary: Any, metric_results: Mapping[str, Any], context: Mapping[str, Any], idempotency_key: Any, expected_version: int) -> dict[str, Any]:
        conclusion = {"winner": winner, "summary": _text(summary, "summary", 2000), "metric_results": deepcopy(dict(metric_results))}
        return self._transition(experiment_id, "concluded", context=context, idempotency_key=idempotency_key, expected_version=expected_version, conclusion=conclusion)

    def rollback(self, experiment_id: Any, *, reason: Any, context: Mapping[str, Any], idempotency_key: Any, expected_version: int) -> dict[str, Any]:
        return self._transition(experiment_id, "rolled_back", context=context, idempotency_key=idempotency_key, expected_version=expected_version, reason=_text(reason, "reason", 1000))

    def _transition(self, experiment_id: Any, status: str, *, context: Mapping[str, Any], idempotency_key: Any, expected_version: int, conclusion: Mapping[str, Any] | None = None, reason: str | None = None) -> dict[str, Any]:
        tenant, actor, trace = self._ctx(context); identity = _uuid(experiment_id, "experiment_id"); key = _text(idempotency_key, "idempotency_key", 200)
        with self._lock:
            current = self.experiments.get((tenant, identity))
            if current is None: raise ExperimentError("EXPERIMENT_NOT_FOUND", "experiment does not exist")
            if current["version"] != expected_version: raise ExperimentError("OPTIMISTIC_LOCK_CONFLICT", "experiment version changed")
            allowed = {"planned": {"running", "rolled_back"}, "running": {"concluded", "rolled_back"}, "concluded": {"rolled_back"}, "rolled_back": set()}
            if status not in allowed[current["status"]]: raise ExperimentError("INVALID_EXPERIMENT_TRANSITION", "experiment transition is invalid")
            next_value = deepcopy(current); next_value["status"] = status; next_value["version"] += 1
            if conclusion is not None: next_value["conclusion"] = dict(conclusion)
            if reason is not None: next_value["rollback_reason"] = reason
            digest = _hash({"from": current, "to": next_value})
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest: raise ExperimentError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            _VALIDATOR.validate(next_value); self.experiments[(tenant, identity)] = next_value; self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(next_value)}; self._event("feedback.experiment.status_changed", tenant, actor, trace, key, next_value, digest); return deepcopy(next_value)

    def get(self, experiment_id: Any, *, context: Mapping[str, Any]) -> dict[str, Any]:
        tenant, _, _ = self._ctx(context); identity = _uuid(experiment_id, "experiment_id"); value = self.experiments.get((tenant, identity))
        if value is None: raise ExperimentError("EXPERIMENT_NOT_FOUND", "experiment does not exist")
        return deepcopy(value)

    def list_samples(self, experiment_id: Any, *, context: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        tenant, _, _ = self._ctx(context); identity = _uuid(experiment_id, "experiment_id"); self.get(identity, context=context); return tuple(deepcopy(self.samples[(tenant, identity)]) )

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str, value: Mapping[str, Any], digest: str) -> None:
        payload = {"aggregate_id": value["id"], "aggregate_version": value["version"], "status": value["status"], "snapshot_hash": _hash(value), "sample_count": len(self.samples.get((tenant, value["id"]), []))}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1, "occurred_at": value["created_at"], "org_id": tenant, "trace_id": trace, "correlation_id": None, "causation_id": None, "aggregate_type": "FeedbackExperiment", "aggregate_id": value["id"], "aggregate_version": value["version"], "actor_type": "user", "actor_id": actor, "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
        self.outbox.append(event); self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace, "experiment_id": value["id"], "request_hash": digest, "status": value["status"], "sample_count": payload["sample_count"], "created_at": value["created_at"]})


FeedbackExperimentService = ExperimentService

__all__ = ["ExperimentError", "ExperimentService", "FeedbackExperimentService"]
