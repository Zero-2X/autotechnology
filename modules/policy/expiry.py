"""Policy snapshot expiry and review lifecycle for POLICY-002."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .gate import (
    QAError,
    _DECISION_VALIDATOR,
    _SNAPSHOT_VALIDATOR,
    _hash,
    _stamp,
    _text,
    _time,
    _uuid,
)


_ROOT = Path(__file__).resolve().parents[2]
_HUMAN_TASK_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/human-task.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class PolicyExpiryService:
    """Turn policy snapshot lifecycle transitions into deterministic decisions."""

    rule_version = "policy-002/v1"

    def __init__(self) -> None:
        self.audit: list[dict[str, Any]] = []
        self.human_tasks: list[dict[str, Any]] = []
        self._results: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def check_snapshot(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        subject_type: str, subject_id: UUID | str, policy_snapshot: Mapping[str, Any],
        evaluated_at: datetime | str | None = None, decision_version: int = 1,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        kind, subject = _text(subject_type, "subject_type", 128), _uuid(subject_id, "subject_id")
        if not isinstance(policy_snapshot, Mapping):
            raise QAError("INVALID_POLICY_INPUT", "policy_snapshot must be an object")
        if type(decision_version) is not int or decision_version < 1:
            raise QAError("INVALID_POLICY_INPUT", "decision_version must be a positive integer")
        snapshot = deepcopy(dict(policy_snapshot))
        errors = list(_SNAPSHOT_VALIDATOR.iter_errors(snapshot))
        if errors:
            raise QAError("INVALID_POLICY_SNAPSHOT", errors[0].message)
        if snapshot.get("org_id") is not None and snapshot.get("org_id") != tenant:
            raise QAError("TENANT_SCOPE_VIOLATION", "PolicySnapshot is outside this organization")
        if snapshot.get("subject_type") != kind or (snapshot.get("subject_id") is not None and snapshot.get("subject_id") != subject):
            raise QAError("POLICY_SUBJECT_MISMATCH", "PolicySnapshot subject does not match evaluation")
        snapshot_id = _uuid(snapshot["id"], "policy_snapshot_id")
        checked_at = _time(evaluated_at, "evaluated_at") if evaluated_at is not None else datetime.now(timezone.utc)
        if checked_at is None:
            raise QAError("INVALID_POLICY_INPUT", "evaluated_at must be timezone-aware ISO-8601")
        request_hash = _hash({"snapshot": snapshot, "subject_type": kind, "subject_id": subject,
                              "evaluated_at": _stamp(checked_at), "decision_version": decision_version})
        with self._lock:
            prior = self._results.get((tenant, key))
            if prior is not None:
                if prior[0] != request_hash:
                    raise QAError("IDEMPOTENCY_KEY_REUSED", "Policy lifecycle request differs from prior request")
                return deepcopy(prior[1])
            effective_at = _time(snapshot.get("effective_at"), "snapshot.effective_at")
            expires_at = _time(snapshot.get("expires_at"), "snapshot.expires_at")
            review_due_at = _time(snapshot.get("review_due_at"), "snapshot.review_due_at")
            status = snapshot.get("status")
            if status in {"expired", "revoked"} or (expires_at is not None and checked_at >= expires_at):
                final, reason = "deny", "POLICY_SNAPSHOT_EXPIRED" if status != "revoked" else "POLICY_SNAPSHOT_REVOKED"
                side_effect_blocked = True
            elif effective_at is not None and checked_at < effective_at:
                final, reason, side_effect_blocked = "deny", "POLICY_SNAPSHOT_NOT_EFFECTIVE", True
            elif status != "active":
                final, reason, side_effect_blocked = "deny", f"POLICY_SNAPSHOT_{str(status).upper()}", True
            elif review_due_at is not None and checked_at >= review_due_at:
                final, reason, side_effect_blocked = "manual_review", "POLICY_SNAPSHOT_REVIEW_DUE", True
            else:
                final, reason, side_effect_blocked = "allow", "POLICY_SNAPSHOT_CURRENT", False
            policy_value = "deny" if final == "deny" else "manual_review" if final == "manual_review" else "allow"
            decision_payload = {
                "org_id": tenant, "subject_type": kind, "subject_id": subject,
                "content_policy": policy_value, "region_policy": policy_value,
                "distribution_policy": policy_value, "account_policy": policy_value,
                "data_processing_policy": policy_value, "model_policy": policy_value,
                "final_decision": final, "reasons": [reason], "policy_snapshot_id": snapshot_id,
                "decision_version": decision_version, "evaluated_at": _stamp(checked_at),
                "expires_at": snapshot.get("expires_at"),
            }
            decision = {"id": str(uuid4()), **decision_payload,
                        "decision_hash": _hash(decision_payload), "created_at": _stamp(checked_at)}
            decision_errors = list(_DECISION_VALIDATOR.iter_errors(decision))
            if decision_errors:
                raise QAError("INVALID_POLICY_DECISION", decision_errors[0].message)
            human_task: dict[str, Any] | None = None
            if final == "manual_review":
                human_task = {
                    "id": str(uuid4()), "org_id": tenant, "task_type": "policy_review",
                    "aggregate_type": kind, "aggregate_id": subject, "input_version": decision_version,
                    "workflow_run_id": None, "approval_id": None, "status": "queued", "assigned_to": None,
                    "claim_lease_until": None, "priority": "high", "sla_policy_id": None,
                    "due_at": snapshot.get("review_due_at"), "input_snapshot": {
                        "policy_snapshot_id": snapshot_id, "reason": reason,
                    }, "result": {}, "completed_by": None, "override_expires_at": None,
                    "created_at": _stamp(checked_at), "completed_at": None,
                }
                task_errors = list(_HUMAN_TASK_VALIDATOR.iter_errors(human_task))
                if task_errors:
                    raise QAError("INVALID_POLICY_REVIEW_TASK", task_errors[0].message)
                self.human_tasks.append(deepcopy(human_task))
            self.audit.append({"event_type": "policy.lifecycle.checked", "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "idempotency_key": key, "input_hash": request_hash,
                               "output_hash": _hash(decision), "policy_snapshot_id": snapshot_id,
                               "final_decision": final, "side_effect_blocked": side_effect_blocked,
                               "human_task_id": human_task["id"] if human_task else None})
            self._results[(tenant, key)] = (request_hash, deepcopy(decision))
            return deepcopy(decision)


__all__ = ["PolicyExpiryService"]
