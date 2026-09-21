"""Manual resolution, dead-letter and single-task replay boundaries for DIST-006C.

This module deliberately stops at a projection boundary.  It records a delivery
outcome, a HumanTask and an auditable replay plan, but it never calls a publisher
or a platform adapter.  A later worker may consume the replay plan only after an
explicit manual action and must still use the original provider idempotency key.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .service import (
    DistributionError,
    _EVENT_VALIDATOR,
    _hash,
    _stamp,
    _text,
    _time,
    _uuid,
    _validate,
)


_ROOT = Path(__file__).resolve().parents[2]
_HUMAN_TASK_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/human-task.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class DeadLetterError(DistributionError):
    """Stable error codes for unknown, dead-letter and replay commands."""


class DeliveryDeadLetterService:
    """Keep delivery failures tenant-scoped and side-effect free.

    ``mark_unknown`` and ``dead_letter`` change local projections only.  The
    service creates at most one HumanTask per delivery/command type and uses an
    idempotency record for every write command.  ``replay_one`` creates a new
    attempt-shaped plan with the original idempotency keys; it does not invoke a
    publisher.
    """

    rule_version = "dist-006c/v1"

    def __init__(self) -> None:
        self.attempts: dict[tuple[str, str], dict[str, Any]] = {}
        self.publication_records: dict[tuple[str, str], dict[str, Any]] = {}
        self.human_tasks: dict[tuple[str, str], dict[str, Any]] = {}
        self.replay_plans: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._versions: dict[tuple[str, str], int] = {}
        self._lock = RLock()

    def mark_unknown(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, delivery_attempt: Mapping[str, Any],
        reason: str, publication_record: Mapping[str, Any] | None = None,
        observed_at: datetime | str | None = None, expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Move one attempt to ``unknown`` and create one review HumanTask."""

        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        attempt = self._attempt(tenant, delivery_attempt)
        reason_text = _text(reason, "reason", 512)
        at = _time(observed_at, "observed_at") or datetime.now(timezone.utc)
        current = self.attempts.get((tenant, attempt["id"]))
        self._check_expected(tenant, attempt["id"], expected_version, current)
        record = self._record(tenant, attempt, publication_record, status="unknown", reason=reason_text, at=at)
        digest = _hash({"operation": "mark_unknown", "attempt": attempt, "record": record,
                        "reason": reason_text, "observed_at": _stamp(at), "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if current is not None and current["status"] not in {"created", "running", "failed", "unknown"}:
                raise DeadLetterError("INVALID_UNKNOWN_TRANSITION", "delivery attempt cannot become unknown from its current state")
            if current is not None and current["status"] == "unknown":
                # A second command with a different key is a projection read, not
                # a second task or a second external observation.
                existing = self._result_for(tenant, attempt["id"])
                self._commands[(tenant, key)] = (digest, deepcopy(existing))
                return deepcopy(existing)
            updated = self._unknown_attempt(attempt, reason_text, at)
            task = self._get_or_create_task(tenant, attempt, "unknown_result", reason_text, at)
            _validate("delivery-attempt", updated)
            self._validate_task(task)
            self.attempts[(tenant, attempt["id"])] = deepcopy(updated)
            self.publication_records[(tenant, attempt["id"])] = deepcopy(record)
            version = self._bump(tenant, attempt["id"])
            event = self._event("delivery.unknown", tenant, actor, trace, key, attempt["id"],
                                version, "unknown", reason_text, at)
            result = {"delivery_attempt": deepcopy(updated), "publication_record": deepcopy(record),
                      "human_task": deepcopy(task), "event": deepcopy(event), "version": version,
                      "side_effect_triggered": False}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("distribution.delivery.unknown", tenant, actor, trace, key, digest, result,
                        attempt_id=attempt["id"], version=version, reason=reason_text)
            return deepcopy(result)

    def dead_letter(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, delivery_attempt: Mapping[str, Any],
        reason: str = "retry limit reached", publication_record: Mapping[str, Any] | None = None,
        occurred_at: datetime | str | None = None, expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Enter the dead-letter terminal state after a bounded retry policy."""

        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        attempt = self._attempt(tenant, delivery_attempt)
        reason_text = _text(reason, "reason", 512)
        at = _time(occurred_at, "occurred_at") or datetime.now(timezone.utc)
        current = self.attempts.get((tenant, attempt["id"]))
        self._check_expected(tenant, attempt["id"], expected_version, current)
        source = current or attempt
        if source["retryable"] and source["attempt_no"] < source["max_attempts"]:
            raise DeadLetterError("RETRY_LIMIT_NOT_REACHED", "retryable delivery has attempts remaining")
        record = self._record(tenant, attempt, publication_record, status="failed", reason=None, at=at)
        digest = _hash({"operation": "dead_letter", "attempt": attempt, "record": record,
                        "reason": reason_text, "occurred_at": _stamp(at), "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if current is not None and current["status"] == "dead_letter":
                existing = self._result_for(tenant, attempt["id"])
                self._commands[(tenant, key)] = (digest, deepcopy(existing))
                return deepcopy(existing)
            if current is not None and current["status"] in {"succeeded"}:
                raise DeadLetterError("INVALID_DEAD_LETTER_TRANSITION", "successful delivery cannot be dead-lettered")
            updated = self._dead_attempt(attempt, reason_text, at)
            task = self._get_or_create_task(tenant, attempt, "support_escalation", reason_text, at)
            _validate("delivery-attempt", updated)
            self._validate_task(task)
            self.attempts[(tenant, attempt["id"])] = deepcopy(updated)
            self.publication_records[(tenant, attempt["id"])] = deepcopy(record)
            version = self._bump(tenant, attempt["id"])
            event = self._event("delivery.dead_lettered", tenant, actor, trace, key, attempt["id"],
                                version, "dead_letter", reason_text, at)
            result = {"delivery_attempt": deepcopy(updated), "publication_record": deepcopy(record),
                      "human_task": deepcopy(task), "event": deepcopy(event), "version": version,
                      "side_effect_triggered": False}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("distribution.delivery.dead_lettered", tenant, actor, trace, key, digest, result,
                        attempt_id=attempt["id"], version=version, reason=reason_text)
            return deepcopy(result)

    def resolve_unknown(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, delivery_attempt: Mapping[str, Any], outcome: str,
        resolution_reason: str, evidence_ref: str, publication_record: Mapping[str, Any] | None = None,
        resolved_at: datetime | str | None = None, expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Apply a manual outcome to an unknown attempt and close its task."""

        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        attempt = self._attempt(tenant, delivery_attempt)
        if outcome not in {"succeeded", "failed"}:
            raise DeadLetterError("INVALID_UNKNOWN_RESOLUTION", "outcome must be succeeded or failed")
        reason = _text(resolution_reason, "resolution_reason", 512)
        evidence = _text(evidence_ref, "evidence_ref", 1024)
        at = _time(resolved_at, "resolved_at") or datetime.now(timezone.utc)
        current = self.attempts.get((tenant, attempt["id"])) or attempt
        self._check_expected(tenant, attempt["id"], expected_version, self.attempts.get((tenant, attempt["id"])))
        if current["status"] != "unknown":
            raise DeadLetterError("UNKNOWN_RESOLUTION_REQUIRED", "delivery attempt is not awaiting unknown resolution")
        record = self._record(tenant, attempt, publication_record, status="published" if outcome == "succeeded" else "failed", reason=None, at=at)
        digest = _hash({"operation": "resolve_unknown", "attempt": attempt, "outcome": outcome,
                        "reason": reason, "evidence_ref": evidence, "record": record, "resolved_at": _stamp(at),
                        "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            task = self._find_task(tenant, attempt["id"], "unknown_result")
            if task is None:
                raise DeadLetterError("UNKNOWN_TASK_NOT_FOUND", "unknown result has no review task")
            updated = deepcopy(current)
            updated.update({"status": outcome, "retryable": False, "completed_at": _stamp(at),
                            "last_error_code": None if outcome == "succeeded" else current.get("last_error_code"),
                            "last_error_at": None if outcome == "succeeded" else current.get("last_error_at"),
                            "resolution_reason": reason, "resolved_by": actor, "resolved_at": _stamp(at),
                            "next_attempt_at": None})
            closed = deepcopy(task)
            closed.update({"status": "completed", "completed_by": actor, "completed_at": _stamp(at),
                           "result": {"outcome": outcome, "resolution_reason": reason, "evidence_ref": evidence}})
            record["resolution_reason"], record["resolved_by"], record["resolved_at"] = reason, actor, _stamp(at)
            record["resolution_evidence_ref"] = evidence
            _validate("delivery-attempt", updated)
            self._validate_task(closed)
            _validate("publication-record", record)
            self.attempts[(tenant, attempt["id"])] = deepcopy(updated)
            self.publication_records[(tenant, attempt["id"])] = deepcopy(record)
            self.human_tasks[(tenant, attempt["id"] + ":unknown_result")] = deepcopy(closed)
            version = self._bump(tenant, attempt["id"])
            event = self._event("delivery.unknown_resolved", tenant, actor, trace, key, attempt["id"],
                                version, outcome, reason, at)
            result = {"delivery_attempt": deepcopy(updated), "publication_record": deepcopy(record),
                      "human_task": deepcopy(closed), "event": deepcopy(event), "version": version,
                      "side_effect_triggered": False}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("distribution.delivery.unknown_resolved", tenant, actor, trace, key, digest, result,
                        attempt_id=attempt["id"], version=version, evidence_ref=evidence)
            return deepcopy(result)

    def replay_one(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, delivery_attempt: Mapping[str, Any], manual_confirmation: bool,
        expected_version: int | None = None, requested_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Create one manual replay plan without invoking any external adapter."""

        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        attempt = self._attempt(tenant, delivery_attempt)
        if not manual_confirmation:
            raise DeadLetterError("MANUAL_CONFIRMATION_REQUIRED", "replay requires explicit manual confirmation")
        if key != attempt["idempotency_key"]:
            raise DeadLetterError("ORIGINAL_IDEMPOTENCY_KEY_REQUIRED", "replay must use the original idempotency key")
        current = self.attempts.get((tenant, attempt["id"])) or attempt
        self._check_expected(tenant, attempt["id"], expected_version, self.attempts.get((tenant, attempt["id"])))
        if current["status"] not in {"unknown", "dead_letter", "failed"}:
            raise DeadLetterError("INVALID_REPLAY_STATE", "only failed, unknown or dead-letter attempts can be replayed")
        at = _time(requested_at, "requested_at") or datetime.now(timezone.utc)
        command_key = f"replay:{attempt['id']}:{key}"
        digest = _hash({"operation": "replay_one", "attempt": current, "manual_confirmation": manual_confirmation,
                        "requested_at": _stamp(at), "expected_version": expected_version})
        with self._lock:
            prior = self._prior(tenant, command_key, digest)
            if prior is not None:
                return prior
            replay_id = str(uuid4())
            replay = deepcopy(current)
            replay.update({"id": replay_id, "attempt_no": current["attempt_no"] + 1,
                           "parent_attempt_id": current["id"], "status": "created", "retryable": False,
                           "next_attempt_at": None, "started_at": None, "completed_at": None,
                           "external_request_id": None, "external_object_id": None, "error_class": None,
                           "last_error_code": None, "last_error_at": None, "resolution_reason": None,
                           "resolved_by": None, "resolved_at": None, "created_at": _stamp(at),
                           "idempotency_key": current["idempotency_key"],
                           "provider_idempotency_key": current["provider_idempotency_key"]})
            _validate("delivery-attempt", replay)
            self.attempts[(tenant, replay_id)] = deepcopy(replay)
            self._versions[(tenant, replay_id)] = 1
            plan = {"id": str(uuid4()), "org_id": tenant, "original_attempt_id": current["id"],
                    "replay_attempt": deepcopy(replay), "idempotency_key": current["idempotency_key"],
                    "provider_idempotency_key": current["provider_idempotency_key"],
                    "manual_confirmation": True, "requires_manual_trigger": True,
                    "side_effect_triggered": False, "created_at": _stamp(at)}
            self.replay_plans[(tenant, plan["id"])] = deepcopy(plan)
            result = {"replay_plan": deepcopy(plan), "delivery_attempt": deepcopy(replay),
                      "side_effect_triggered": False, "requires_manual_trigger": True}
            self._commands[(tenant, command_key)] = (digest, deepcopy(result))
            self._audit("distribution.delivery.replay_requested", tenant, actor, trace, key, digest, result,
                        attempt_id=current["id"], replay_attempt_id=replay_id, original_idempotency_key=key)
            return deepcopy(result)

    # Clear aliases make the boundary convenient for callers that name the
    # operation after the task card rather than the aggregate transition.
    mark_dead_letter = dead_letter
    resolve = resolve_unknown
    replay = replay_one
    replay_task = replay_one

    def _context(self, org_id: UUID | str, actor_id: UUID | str, trace_id: str, key: str) -> tuple[str, str, str, str]:
        return _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id"), _text(trace_id, "trace_id"), _text(key, "idempotency_key", 200)

    def _attempt(self, tenant: str, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise DeadLetterError("INVALID_DELIVERY_ATTEMPT", "delivery_attempt must be an object")
        attempt = deepcopy(dict(value))
        if attempt.get("org_id") != tenant:
            raise DeadLetterError("TENANT_SCOPE_VIOLATION", "delivery attempt is outside this organization")
        try:
            _validate("delivery-attempt", attempt)
        except DistributionError as exc:
            raise DeadLetterError(exc.code, str(exc)) from exc
        return attempt

    def _record(self, tenant: str, attempt: Mapping[str, Any], provided: Mapping[str, Any] | None,
                *, status: str, reason: str | None, at: datetime) -> dict[str, Any]:
        if provided is not None:
            if not isinstance(provided, Mapping) or provided.get("org_id") != tenant or provided.get("delivery_attempt_id") != attempt["id"]:
                raise DeadLetterError("TENANT_SCOPE_VIOLATION", "publication record is outside this delivery attempt")
            record = deepcopy(dict(provided))
            try:
                _validate("publication-record", record)
            except DistributionError as exc:
                raise DeadLetterError(exc.code, str(exc)) from exc
            if record["status"] in {"published", "removed"} and status in {"unknown", "failed"}:
                raise DeadLetterError("INVALID_PUBLICATION_TRANSITION", "successful publication cannot regress")
            record["status"] = status
            record["unknown_reason"] = reason if status == "unknown" else None
            record["last_observed_at"] = _stamp(at)
            record["observation_source"] = "manual"
            return record
        return {
            "id": str(uuid5(NAMESPACE_URL, f"publication-record:{tenant}:{attempt['id']}")), "org_id": tenant, "publication_intent_id": attempt["publication_intent_id"],
            "delivery_attempt_id": attempt["id"], "provider_mode": attempt["provider_mode"],
            "external_request_id": attempt["external_request_id"], "external_object_id": attempt["external_object_id"],
            "external_url": None, "status": status,
            "result_snapshot": {"simulated": attempt["provider_mode"] == "fake",
                                 "replay_input_hash": _hash({"attempt": attempt, "reason": reason}),
                                 "attempt_no": attempt["attempt_no"]},
            "observed_at": _stamp(at), "last_observed_at": _stamp(at), "observation_source": "manual",
            "unknown_reason": reason if status == "unknown" else None, "resolution_reason": None,
            "resolved_by": None, "resolved_at": None, "resolution_evidence_ref": None,
        }

    @staticmethod
    def _unknown_attempt(attempt: Mapping[str, Any], reason: str, at: datetime) -> dict[str, Any]:
        updated = deepcopy(dict(attempt))
        updated.update({"status": "unknown", "retryable": False, "next_attempt_at": None,
                        "completed_at": _stamp(at), "last_error_code": reason,
                        "last_error_at": _stamp(at), "resolution_reason": None,
                        "resolved_by": None, "resolved_at": None})
        return updated

    @staticmethod
    def _dead_attempt(attempt: Mapping[str, Any], reason: str, at: datetime) -> dict[str, Any]:
        updated = deepcopy(dict(attempt))
        updated.update({"status": "dead_letter", "retryable": False, "next_attempt_at": None,
                        "completed_at": _stamp(at), "last_error_code": reason,
                        "last_error_at": _stamp(at), "resolution_reason": None,
                        "resolved_by": None, "resolved_at": None})
        return updated

    def _get_or_create_task(self, tenant: str, attempt: Mapping[str, Any], task_type: str,
                            reason: str, at: datetime) -> dict[str, Any]:
        task_key = (tenant, attempt["id"] + ":" + task_type)
        existing = self.human_tasks.get(task_key)
        if existing is not None:
            return deepcopy(existing)
        task = {
            "id": str(uuid4()), "org_id": tenant, "task_type": task_type,
            "aggregate_type": "DeliveryAttempt", "aggregate_id": attempt["id"], "input_version": attempt["attempt_no"],
            "workflow_run_id": None, "approval_id": None, "status": "queued", "assigned_to": None,
            "claim_lease_until": None, "priority": "urgent" if task_type == "unknown_result" else "high",
            "sla_policy_id": None, "due_at": None,
            "input_snapshot": {"delivery_attempt_id": attempt["id"], "publication_intent_id": attempt["publication_intent_id"],
                               "attempt_no": attempt["attempt_no"], "idempotency_key": attempt["idempotency_key"],
                               "reason": reason, "side_effect_blocked": True},
            "result": {}, "completed_by": None, "override_expires_at": None,
            "created_at": _stamp(at), "completed_at": None,
        }
        self.human_tasks[task_key] = deepcopy(task)
        return task

    def _find_task(self, tenant: str, attempt_id: str, task_type: str) -> dict[str, Any] | None:
        task = self.human_tasks.get((tenant, attempt_id + ":" + task_type))
        return deepcopy(task) if task is not None else None

    @staticmethod
    def _validate_task(task: Mapping[str, Any]) -> None:
        errors = sorted(_HUMAN_TASK_VALIDATOR.iter_errors(dict(task)), key=lambda error: list(error.path))
        if errors:
            raise DeadLetterError("INVALID_HUMAN_TASK", errors[0].message)

    def _check_expected(self, tenant: str, attempt_id: str, expected: int | None,
                        current: Mapping[str, Any] | None) -> None:
        if expected is not None and (type(expected) is not int or expected < 1):
            raise DeadLetterError("INVALID_EXPECTED_VERSION", "expected_version must be a positive integer")
        if expected is not None and expected != self._versions.get((tenant, attempt_id), 1):
            raise DeadLetterError("VERSION_CONFLICT", "delivery attempt version does not match expected_version")
        if current is not None and current.get("org_id") != tenant:
            raise DeadLetterError("TENANT_SCOPE_VIOLATION", "delivery attempt is outside this organization")

    def _bump(self, tenant: str, attempt_id: str) -> int:
        version = self._versions.get((tenant, attempt_id), 0) + 1
        self._versions[(tenant, attempt_id)] = version
        return version

    def _result_for(self, tenant: str, attempt_id: str) -> dict[str, Any]:
        attempt = deepcopy(self.attempts[(tenant, attempt_id)])
        record = deepcopy(self.publication_records.get((tenant, attempt_id)))
        task = next((deepcopy(value) for (org, key), value in self.human_tasks.items()
                     if org == tenant and key.startswith(attempt_id + ":") and value["status"] != "completed"), None)
        return {"delivery_attempt": attempt, "publication_record": record, "human_task": task,
                "version": self._versions.get((tenant, attempt_id), 1), "side_effect_triggered": False}

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise DeadLetterError("IDEMPOTENCY_KEY_REUSED", "command differs from prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               digest: str, output: Mapping[str, Any], **extra: Any) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                           "idempotency_key": key, "input_hash": digest, "output_hash": _hash(output), **extra})

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               aggregate_id: str, version: int, to_state: str, reason: str, occurred_at: datetime) -> dict[str, Any]:
        command = {
            "delivery.unknown": "unknown",
            "delivery.dead_lettered": "dead_letter",
            "delivery.unknown_resolved": "resolve_unknown",
        }[event_type]
        from_state = {
            "delivery.unknown": "running",
            "delivery.dead_lettered": "failed",
            "delivery.unknown_resolved": "unknown",
        }[event_type]
        payload = {"aggregate_id": aggregate_id, "aggregate_version": version,
                   "from_state": from_state, "to_state": to_state, "command": command,
                   "snapshot_hash": _hash({"aggregate_id": aggregate_id, "version": version, "reason": reason}),
                   "reason": reason}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "DeliveryAttempt", "aggregate_id": aggregate_id, "aggregate_version": version,
                 "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                 "payload": payload, "payload_hash": _hash(payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise DeadLetterError("INVALID_DELIVERY_EVENT", errors[0].message)
        self.events.append(deepcopy(event))
        return event


UnknownDeliveryService = DeliveryDeadLetterService
DeliveryUnknownService = DeliveryDeadLetterService
DeadLetterService = DeliveryDeadLetterService


__all__ = ["DeadLetterError", "DeliveryDeadLetterService", "DeliveryUnknownService", "DeadLetterService", "UnknownDeliveryService"]
