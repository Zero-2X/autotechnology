"""Tenant-scoped FeedbackItem facts for FEEDBACK-CORE-003."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from .contracts import ContractError, FeedbackItem, validate_feedback_item, validate_observation

_ROOT = Path(__file__).resolve().parents[3]
_EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
_EVENT_VALIDATOR = Draft202012Validator(_EVENT_SCHEMA, format_checker=FormatChecker())
_NAMESPACE = UUID("34d17f70-3de9-57e5-b1e8-0c88c9edc598")
_EVENT_NAMESPACE = UUID("7e5d4b37-3c0e-5a1f-8ff8-bd8c2cdd6828")


class FeedbackItemError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _uuid(value: Any, field: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise FeedbackItemError("INVALID_FEEDBACK_INPUT", f"{field} must be a UUID") from exc


def _text(value: Any, field: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeedbackItemError("INVALID_FEEDBACK_INPUT", f"{field} must be non-empty text")
    result = value.strip()
    if len(result) > maximum:
        raise FeedbackItemError("INVALID_FEEDBACK_INPUT", f"{field} exceeds {maximum} characters")
    return result


def _stamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "timestamp must include a timezone")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    raw = _text(value, "timestamp", 64).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(value: Any) -> str:
    from hashlib import sha256
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class InMemoryFeedbackItemStore:
    def __init__(self) -> None:
        self.lock = RLock()
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.versions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []

    def latest(self, org_id: str, identity: str) -> dict[str, Any] | None:
        value = self.items.get((org_id, identity))
        return deepcopy(value) if value is not None else None


class FeedbackItemService:
    """Create and transition immutable FeedbackItem projections."""

    task_id = "FEEDBACK-CORE-003"

    def __init__(self, store: InMemoryFeedbackItemStore | None = None, *, clock: Any | None = None) -> None:
        self.store = store or InMemoryFeedbackItemStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _context(self, context: Mapping[str, Any] | None, org_id: Any, actor_id: Any, trace_id: Any) -> tuple[str, str, str]:
        ctx = dict(context or {})
        tenant = _uuid(org_id if org_id is not None else ctx.get("org_id"), "org_id")
        actor = _uuid(actor_id if actor_id is not None else ctx.get("actor_id", "00000000-0000-4000-8000-000000000001"), "actor_id")
        trace = _text(trace_id if trace_id is not None else ctx.get("trace_id", self.task_id), "trace_id", 256)
        return tenant, actor, trace

    def _validate_observations(self, records: Sequence[Mapping[str, Any]] | None, ids: list[str], tenant: str) -> None:
        if records is None:
            return
        seen: set[str] = set()
        for raw in records:
            try:
                observation = validate_observation(deepcopy(dict(raw)))
            except (ContractError, TypeError) as exc:
                raise FeedbackItemError("INVALID_OBSERVATION", str(exc)) from exc
            if observation["org_id"] != tenant:
                raise FeedbackItemError("TENANT_SCOPE_VIOLATION", "observation belongs to another organization")
            if observation["source"] not in {"fake", "manual", "site", "qa", "geo", "support"}:
                raise FeedbackItemError("SOURCE_NOT_ALLOWED", "M1 feedback accepts account-free observations")
            seen.add(observation["id"])
        if not set(ids).issubset(seen):
            raise FeedbackItemError("OBSERVATION_NOT_FOUND", "every feedback observation must be supplied")

    def create_feedback_item(
        self, *, observation_ids: Sequence[Any], problem: Any, recommendation_type: Any,
        impact: Any, priority: Any, confidence: Any, reasoning_snapshot: Mapping[str, Any],
        context: Mapping[str, Any] | None = None, org_id: Any = None, actor_id: Any = None,
        trace_id: Any = None, idempotency_key: Any, owner_actor_id: Any = None,
        due_at: Any = None, expires_at: Any = None, observations: Sequence[Mapping[str, Any]] | None = None,
        item_id: Any = None, created_at: Any = None,
    ) -> dict[str, Any]:
        tenant, actor, trace = self._context(context, org_id, actor_id, trace_id)
        key = _text(idempotency_key, "idempotency_key", 200)
        ids = [_uuid(item, "observation_id") for item in observation_ids]
        if not ids or len(set(ids)) != len(ids):
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "observation_ids must be unique and non-empty")
        self._validate_observations(observations, ids, tenant)
        created_supplied = created_at is not None
        created = _stamp(created_at if created_supplied else self._clock())
        identity = _uuid(item_id, "id") if item_id is not None else str(uuid5(_NAMESPACE, f"{tenant}:{key}"))
        payload = {"org_id": tenant, "observation_ids": ids, "problem": problem, "recommendation_type": recommendation_type,
                   "impact": impact, "priority": priority, "confidence": confidence, "reasoning_snapshot": dict(reasoning_snapshot),
                   "owner_actor_id": _uuid(owner_actor_id, "owner_actor_id") if owner_actor_id else None,
                   "due_at": _stamp(due_at) if due_at else None, "approver_id": None, "expires_at": _stamp(expires_at) if expires_at else None,
                   "created_action_id": None, "status": "proposed", "created_at": created}
        try:
            item = FeedbackItem.create(id=identity, **payload).as_contract()
            validate_feedback_item(item)
        except (ContractError, TypeError, ValueError) as exc:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", str(exc)) from exc
        digest = _hash({"operation": "create_feedback_item", "item": item if created_supplied else {**item, "created_at": None}})
        with self.store.lock:
            prior = self.store.commands.get((tenant, key))
            if prior is not None:
                if prior["request_hash"] != digest:
                    raise FeedbackItemError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            existing = self.store.latest(tenant, identity)
            if existing is not None and existing != item:
                raise FeedbackItemError("FEEDBACK_ITEM_CONFLICT", "feedback item id has another payload")
            self.store.items[(tenant, identity)] = deepcopy(item)
            self.store.versions[(tenant, identity)] = [deepcopy(item)]
            self.store.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(item)}
            self._record_event("feedback.item.created", tenant, actor, trace, key, identity, item, created)
            self.store.audit.append({"event_type": "feedback.item.created", "org_id": tenant, "actor_id": actor, "trace_id": trace,
                                     "feedback_item_id": identity, "input_hash": digest, "snapshot_hash": _hash(item), "status": item["status"], "created_at": created})
            return deepcopy(item)

    create = create_feedback_item

    def transition_feedback_item(self, item_id: Any, *, status: str, context: Mapping[str, Any] | None = None,
                                 org_id: Any = None, actor_id: Any = None, trace_id: Any = None,
                                 idempotency_key: Any, expected_version: int, approver_id: Any = None,
                                 created_action_id: Any = None, result_reason: Any = None, changed_at: Any = None) -> dict[str, Any]:
        tenant, actor, trace = self._context(context, org_id, actor_id, trace_id)
        identity, key = _uuid(item_id, "item_id"), _text(idempotency_key, "idempotency_key", 200)
        stamp = _stamp(changed_at if changed_at is not None else self._clock())
        allowed = {"proposed": {"approved", "rejected", "expired"}, "approved": {"executed", "expired"}, "rejected": set(), "executed": set(), "expired": set()}
        if status not in {"proposed", "approved", "rejected", "executed", "expired"}:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "unsupported feedback status")
        with self.store.lock:
            current = self.store.latest(tenant, identity)
            if current is None:
                raise FeedbackItemError("FEEDBACK_ITEM_NOT_FOUND", "feedback item does not exist")
            versions = self.store.versions[(tenant, identity)]
            if len(versions) != expected_version:
                raise FeedbackItemError("OPTIMISTIC_LOCK_CONFLICT", "feedback item version changed")
            if status not in allowed[current["status"]]:
                raise FeedbackItemError("INVALID_FEEDBACK_TRANSITION", f"cannot move {current['status']} to {status}")
            next_item = deepcopy(current)
            next_item["status"] = status
            if status == "approved":
                next_item["approver_id"] = _uuid(approver_id if approver_id is not None else actor, "approver_id")
            if created_action_id is not None:
                next_item["created_action_id"] = _uuid(created_action_id, "created_action_id")
            digest = _hash({"operation": "transition_feedback_item", "item_id": identity, "from": current, "to": next_item, "reason": result_reason})
            prior = self.store.commands.get((tenant, key))
            if prior is not None:
                if prior["request_hash"] != digest:
                    raise FeedbackItemError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            next_item["created_at"] = current["created_at"]
            validate_feedback_item(next_item)
            self.store.items[(tenant, identity)] = next_item
            versions.append(deepcopy(next_item))
            self.store.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(next_item)}
            self._record_event("feedback.item.status_changed", tenant, actor, trace, key, identity, next_item, stamp, from_status=current["status"], reason=result_reason)
            self.store.audit.append({"event_type": "feedback.item.status_changed", "org_id": tenant, "actor_id": actor, "trace_id": trace,
                                     "feedback_item_id": identity, "input_version": expected_version, "output_version": len(versions),
                                     "from_status": current["status"], "status": status, "reason": result_reason, "created_at": stamp})
            return deepcopy(next_item)

    transition = transition_feedback_item
    approve = lambda self, item_id, **kwargs: self.transition_feedback_item(item_id, status="approved", **kwargs)
    reject = lambda self, item_id, **kwargs: self.transition_feedback_item(item_id, status="rejected", **kwargs)

    def get_feedback_item(self, item_id: Any, *, context: Mapping[str, Any] | None = None, org_id: Any = None) -> dict[str, Any]:
        tenant, _, _ = self._context(context, org_id, None, None)
        identity = _uuid(item_id, "item_id")
        with self.store.lock:
            value = self.store.latest(tenant, identity)
            if value is None:
                raise FeedbackItemError("FEEDBACK_ITEM_NOT_FOUND", "feedback item does not exist")
            return deepcopy(value)

    get = get_feedback_item

    def _record_event(self, event_type: str, tenant: str, actor: str, trace: str, key: str, identity: str,
                      item: Mapping[str, Any], occurred_at: str, *, from_status: str | None = None, reason: Any = None) -> None:
        payload = {"aggregate_id": identity, "aggregate_version": len(self.store.versions.get((tenant, identity), [])), "status": item["status"], "snapshot_hash": _hash(item)}
        if from_status is not None: payload["from_status"] = from_status
        if reason is not None: payload["reason"] = _text(reason, "reason", 512)
        event = {"event_id": str(uuid5(_EVENT_NAMESPACE, f"{event_type}:{identity}:{payload['aggregate_version']}")), "event_type": event_type,
                 "event_schema_version": 1, "occurred_at": occurred_at, "org_id": tenant, "trace_id": trace,
                 "correlation_id": None, "causation_id": None, "aggregate_type": "FeedbackItem", "aggregate_id": identity,
                 "aggregate_version": payload["aggregate_version"], "actor_type": "user", "actor_id": actor, "idempotency_key": key,
                 "payload": payload, "payload_hash": _hash(payload)}
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise FeedbackItemError("INVALID_FEEDBACK_EVENT", errors[0].message)
        self.store.outbox.append(deepcopy(event))


FeedbackCoreService = FeedbackItemService

__all__ = ["FeedbackItemError", "InMemoryFeedbackItemStore", "FeedbackItemService", "FeedbackCoreService"]
