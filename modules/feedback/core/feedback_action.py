"""Append-only FeedbackAction lifecycle for FEEDBACK-CORE-005."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from .feedback_item import FeedbackItemError, _stamp, _text, _uuid

_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/feedback-action.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_SENSITIVE = {"token", "secret", "password", "cookie", "authorization", "email", "phone", "raw_content"}


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class FeedbackActionService:
    """Record approved internal refresh/reorder commands without executing providers."""

    task_id = "FEEDBACK-CORE-005"
    _TRANSITIONS = {
        "proposed": {"approved", "cancelled"}, "approved": {"executing", "cancelled"},
        "executing": {"executed", "failed", "cancelled"}, "executed": set(), "failed": {"executing"}, "cancelled": set(),
    }
    _TARGETS = {"topic_opportunity", "canonical_content", "variant", "prompt"}
    _ACTIONS = {"refresh", "revise", "retire", "reprioritize", "channel_change", "prompt_eval"}

    def __init__(self, *, clock: Any | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.actions: dict[tuple[str, str], dict[str, Any]] = {}
        self.versions: dict[tuple[str, str], int] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []
        self._lock = RLock()

    def _context(self, context: Mapping[str, Any] | None) -> tuple[str, str, str]:
        ctx = dict(context or {})
        return (_uuid(ctx.get("org_id"), "org_id"), _uuid(ctx.get("actor_id", "00000000-0000-4000-8000-000000000001"), "actor_id"), _text(ctx.get("trace_id", self.task_id), "trace_id", 256))

    def _safe_snapshot(self, value: Mapping[str, Any] | None) -> dict[str, Any]:
        result = dict(value or {})
        if set(result) & _SENSITIVE:
            raise FeedbackItemError("SENSITIVE_FEEDBACK_ACTION", "result snapshot contains a forbidden field")
        try:
            json.dumps(result, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise FeedbackItemError("INVALID_ACTION_RESULT", "result snapshot must be finite JSON") from exc
        return result

    def create_action(self, *, feedback_item_id: Any, action_type: str, target_type: str, target_id: Any,
                      target_version: int, context: Mapping[str, Any], idempotency_key: Any,
                      policy_decision: Mapping[str, Any], approval: Mapping[str, Any] | None = None,
                      created_at: Any = None) -> dict[str, Any]:
        tenant, actor, trace = self._context(context)
        item = _uuid(feedback_item_id, "feedback_item_id")
        target = _uuid(target_id, "target_id")
        key = _text(idempotency_key, "idempotency_key", 200)
        if action_type not in self._ACTIONS or target_type not in self._TARGETS:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "unsupported action or target type")
        if type(target_version) is not int or target_version < 1:
            raise FeedbackItemError("INVALID_FEEDBACK_INPUT", "target_version must be positive")
        if not isinstance(policy_decision, Mapping) or policy_decision.get("decision") not in {"allow", "approved"}:
            raise FeedbackItemError("POLICY_BLOCKED", "policy decision does not allow this action")
        if policy_decision.get("side_effect_blocked") is True:
            raise FeedbackItemError("POLICY_BLOCKED", "policy explicitly blocks side effects")
        if approval is not None and approval.get("status") != "approved":
            raise FeedbackItemError("APPROVAL_REQUIRED", "an action requires an approved approval record")
        stamp = _stamp(created_at if created_at is not None else self.clock())
        identity = str(uuid4())
        result = {"id": identity, "org_id": tenant, "feedback_item_id": item, "action_type": action_type, "target_type": target_type,
                  "target_id": target, "target_version": target_version, "status": "proposed", "approved_by": None,
                  "approved_at": None, "executed_at": None, "result_snapshot": {"side_effect_blocked": True}, "created_at": stamp}
        _VALIDATOR.validate(result)
        digest = _hash({"operation": "create", "feedback_item_id": item, "action_type": action_type, "target_type": target_type, "target_id": target, "target_version": target_version, "policy": dict(policy_decision), "approval": dict(approval or {})})
        with self._lock:
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest: raise FeedbackItemError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            self.actions[(tenant, identity)] = deepcopy(result); self.versions[(tenant, identity)] = 1
            self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(result)}
            self._record("feedback.action.created", tenant, actor, trace, key, result, digest)
            return deepcopy(result)

    create = create_action

    def transition_action(self, action_id: Any, *, status: str, context: Mapping[str, Any], idempotency_key: Any,
                          expected_version: int, approval: Mapping[str, Any] | None = None,
                          result_snapshot: Mapping[str, Any] | None = None, reason: Any = None,
                          policy_decision: Mapping[str, Any] | None = None, changed_at: Any = None) -> dict[str, Any]:
        tenant, actor, trace = self._context(context); identity = _uuid(action_id, "action_id"); key = _text(idempotency_key, "idempotency_key", 200)
        stamp = _stamp(changed_at if changed_at is not None else self.clock())
        with self._lock:
            current = self.actions.get((tenant, identity))
            if current is None: raise FeedbackItemError("FEEDBACK_ACTION_NOT_FOUND", "feedback action does not exist")
            previous_status = current["status"]
            version = self.versions[(tenant, identity)]
            if version != expected_version: raise FeedbackItemError("OPTIMISTIC_LOCK_CONFLICT", "action version changed")
            if status not in self._TRANSITIONS.get(current["status"], set()): raise FeedbackItemError("INVALID_ACTION_TRANSITION", f"cannot move {current['status']} to {status}")
            if status == "approved":
                if approval is None or approval.get("status") != "approved": raise FeedbackItemError("APPROVAL_REQUIRED", "approved approval evidence is required")
                current["approved_by"] = _uuid(approval.get("approved_by"), "approval.approved_by"); current["approved_at"] = _stamp(approval.get("approved_at", stamp))
            if status == "executing" and policy_decision is not None and (policy_decision.get("decision") not in {"allow", "approved"} or policy_decision.get("side_effect_blocked") is True):
                raise FeedbackItemError("POLICY_BLOCKED", "policy does not allow execution")
            safe = self._safe_snapshot(result_snapshot)
            if reason is not None: safe["reason"] = _text(reason, "reason", 512)
            safe.setdefault("side_effect_blocked", status != "executed")
            current["status"] = status; current["result_snapshot"] = safe
            if status == "executed": current["executed_at"] = stamp
            _VALIDATOR.validate(current)
            digest = _hash({"operation": "transition", "action": identity, "from": self.actions[(tenant, identity)], "to": current, "expected_version": expected_version})
            prior = self.commands.get((tenant, key))
            if prior:
                if prior["request_hash"] != digest: raise FeedbackItemError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            self.versions[(tenant, identity)] = version + 1; self.actions[(tenant, identity)] = deepcopy(current)
            self.commands[(tenant, key)] = {"request_hash": digest, "response": deepcopy(current)}
            self._record("feedback.action.status_changed", tenant, actor, trace, key, current, digest, from_status=previous_status, at=stamp)
            return deepcopy(current)

    approve = lambda self, action_id, **kwargs: self.transition_action(action_id, status="approved", **kwargs)
    start = lambda self, action_id, **kwargs: self.transition_action(action_id, status="executing", **kwargs)
    complete = lambda self, action_id, **kwargs: self.transition_action(action_id, status="executed", **kwargs)
    fail = lambda self, action_id, **kwargs: self.transition_action(action_id, status="failed", **kwargs)
    cancel = lambda self, action_id, **kwargs: self.transition_action(action_id, status="cancelled", **kwargs)

    def get_action(self, action_id: Any, *, context: Mapping[str, Any]) -> dict[str, Any]:
        tenant, _, _ = self._context(context); identity = _uuid(action_id, "action_id")
        with self._lock:
            value = self.actions.get((tenant, identity))
            if value is None: raise FeedbackItemError("FEEDBACK_ACTION_NOT_FOUND", "feedback action does not exist")
            return deepcopy(value)

    get = get_action

    def _record(self, event_type: str, tenant: str, actor: str, trace: str, key: str, action: Mapping[str, Any], digest: str, *, from_status: str | None = None, at: str | None = None) -> None:
        payload = {"aggregate_id": action["id"], "aggregate_version": self.versions[(tenant, action["id"])], "status": action["status"], "snapshot_hash": _hash(action), "side_effect_triggered": False}
        if from_status is not None: payload["from_status"] = from_status
        when = at or action["created_at"]
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1, "occurred_at": when, "org_id": tenant, "trace_id": trace, "correlation_id": None, "causation_id": None, "aggregate_type": "FeedbackAction", "aggregate_id": action["id"], "aggregate_version": payload["aggregate_version"], "actor_type": "user", "actor_id": actor, "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
        self.outbox.append(event); self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace, "action_id": action["id"], "request_hash": digest, "status": action["status"], "side_effect_triggered": False, "created_at": when})


FeedbackCoreActionService = FeedbackActionService

__all__ = ["FeedbackActionService", "FeedbackCoreActionService"]
