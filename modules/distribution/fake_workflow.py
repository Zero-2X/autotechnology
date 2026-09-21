"""Deterministic Fake Adapter delivery workflow for DIST-010.

The workflow composes the credential-free adapter with the retry, idempotency,
reconciliation and dead-letter boundaries.  It never contacts a platform and
keeps replay as an explicit, side-effect-free manual plan.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from .deadletter import DeliveryDeadLetterService
from .fake import FakeOfficialAdapter, FakeOfficialError
from .idempotency import DeliveryIdempotencyService
from .reconcile import PublicationReconciler
from .retry import RetryPolicyService
from .service import DistributionError, _hash, _stamp, _time, _uuid, _validate


class FakeWorkflowError(DistributionError):
    """Stable errors for invalid fake workflow inputs."""


class FakeDeliveryWorkflowService:
    """Run a complete fake delivery without credentials or external effects."""

    def __init__(
        self,
        *,
        adapter: FakeOfficialAdapter | None = None,
        retry_policy: RetryPolicyService | None = None,
        dead_letter: DeliveryDeadLetterService | None = None,
        idempotency: DeliveryIdempotencyService | None = None,
        reconciler: PublicationReconciler | None = None,
    ) -> None:
        self.adapter = adapter or FakeOfficialAdapter()
        self.retry_policy = retry_policy or RetryPolicyService()
        self.dead_letter = dead_letter or DeliveryDeadLetterService()
        self.idempotency = idempotency or DeliveryIdempotencyService()
        self.reconciler = reconciler or PublicationReconciler()
        self._drafts: dict[tuple[str, str], dict[str, Any]] = {}

    def publish(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        publication_intent: Mapping[str, Any],
        policy_snapshot_id: UUID | str,
        execution_policy_decision_id: UUID | str,
        environment: str = "dev",
        max_attempts: int = 3,
        attempt_no: int = 1,
        now: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Create a fake draft and publish it, classifying failures locally."""

        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        if not isinstance(publication_intent, Mapping) or publication_intent.get("org_id") != tenant:
            raise FakeWorkflowError("TENANT_SCOPE_VIOLATION", "publication intent is outside this organization")
        if type(max_attempts) is not int or max_attempts < 1 or type(attempt_no) is not int or not 1 <= attempt_no <= max_attempts:
            raise FakeWorkflowError("INVALID_ATTEMPT_BOUNDS", "attempt_no must be within max_attempts")
        at = _time(now, "now") or datetime.now(timezone.utc)
        intent = deepcopy(dict(publication_intent))
        self.idempotency.accept_intent(
            org_id=tenant, actor_id=actor, trace_id=trace_id,
            idempotency_key=f"intent:{idempotency_key}", intent=intent,
        )
        draft_key = (tenant, intent["id"])
        draft = self._drafts.get(draft_key)
        if draft is None:
            draft = self.adapter.create_draft(
                org_id=tenant, actor_id=actor, trace_id=trace_id,
                idempotency_key=f"draft:{idempotency_key}", publication_intent=intent,
                policy_snapshot_id=policy_snapshot_id,
                execution_policy_decision_id=execution_policy_decision_id,
                environment=environment, created_at=at,
            )
            self._drafts[draft_key] = deepcopy(draft)
        try:
            published = self.adapter.publish(
                org_id=tenant, actor_id=actor, trace_id=trace_id,
                idempotency_key=f"publish:{idempotency_key}:{attempt_no}",
                draft_id=draft["id"], expected_version=draft["version"], published_at=at,
            )
        except FakeOfficialError as exc:
            return self._failed(
                tenant=tenant, actor=actor, trace_id=trace_id, original_key=idempotency_key,
                intent=intent, policy_snapshot_id=policy_snapshot_id,
                execution_policy_decision_id=execution_policy_decision_id,
                environment=environment, max_attempts=max_attempts, attempt_no=attempt_no,
                error=exc, at=at,
            )

        self._drafts[draft_key] = deepcopy(published["draft"])
        accepted_attempt = self.idempotency.accept_attempt(
            org_id=tenant, actor_id=actor, trace_id=trace_id,
            idempotency_key=f"attempt:{idempotency_key}:{attempt_no}",
            attempt=published["delivery_attempt"],
        )
        observed = self.reconciler.observe(
            org_id=tenant, actor_id=actor, trace_id=trace_id,
            idempotency_key=f"observe:{idempotency_key}:{attempt_no}",
            delivery_attempt=accepted_attempt, observed_status="published", observed_at=at,
            external_request_id=published["publication_record"]["external_request_id"],
            external_object_id=published["publication_record"]["external_object_id"],
            external_url=published["publication_record"]["external_url"], observation_source="adapter",
        )
        event = self.adapter.events[-1]
        handler_calls: list[str] = []
        first_event = self.idempotency.consume_event(
            org_id=tenant, actor_id=actor, trace_id=trace_id, envelope=event,
            handler=lambda value: handler_calls.append(value["event_id"]) or {"recorded": True},
        )
        replay_event = self.idempotency.consume_event(
            org_id=tenant, actor_id=actor, trace_id=f"{trace_id}:replay", envelope=event,
            handler=lambda value: handler_calls.append("duplicate") or {"recorded": False},
        )
        return {
            "status": "succeeded", "draft": deepcopy(published["draft"]),
            "delivery_attempt": deepcopy(accepted_attempt),
            "publication_record": deepcopy(observed["publication_record"]),
            "event_consumption": {"first": first_event, "replay": replay_event, "handler_calls": len(handler_calls)},
            "side_effect_triggered": True,
        }

    def replay(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        delivery_attempt: Mapping[str, Any], manual_confirmation: bool,
        requested_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Create the manual replay plan; the adapter is never called here."""

        return self.dead_letter.replay_one(
            org_id=org_id, actor_id=actor_id, trace_id=trace_id,
            idempotency_key=str(delivery_attempt.get("idempotency_key", "")),
            delivery_attempt=delivery_attempt, manual_confirmation=manual_confirmation,
            requested_at=requested_at,
        )

    def _failed(
        self, *, tenant: str, actor: str, trace_id: str, original_key: str,
        intent: Mapping[str, Any], policy_snapshot_id: UUID | str,
        execution_policy_decision_id: UUID | str, environment: str,
        max_attempts: int, attempt_no: int, error: FakeOfficialError, at: datetime,
    ) -> dict[str, Any]:
        classification = self.retry_policy.classify(
            org_id=tenant, actor_id=actor, trace_id=trace_id,
            idempotency_key=f"classify:{original_key}:{attempt_no}", error_code=error.code,
            attempt_no=attempt_no, max_attempts=max_attempts, now=at,
        )
        attempt_id = str(uuid5(NAMESPACE_URL, f"fake-delivery:{tenant}:{intent['id']}:{attempt_no}"))
        attempt = {
            "id": attempt_id, "org_id": tenant, "publication_intent_id": intent["id"],
            "account_connection_id": None, "adapter_ref": self.adapter.adapter_ref,
            "provider_mode": "fake", "environment": environment,
            "policy_snapshot_id": _uuid(policy_snapshot_id, "policy_snapshot_id"),
            "execution_policy_decision_id": _uuid(execution_policy_decision_id, "execution_policy_decision_id"),
            "adapter_version": "v1", "capability_snapshot": {},
            "idempotency_key": original_key,
            "provider_idempotency_key": f"fake-provider-{_hash({'intent': intent['id'], 'attempt': attempt_no})[:24]}",
            "attempt_no": attempt_no, "parent_attempt_id": None, "status": "failed",
            "retryable": bool(classification["retryable"]),
            "next_attempt_at": _stamp(at + timedelta(seconds=classification["retry_after_seconds"])) if classification["retry_after_seconds"] else None,
            "max_attempts": max_attempts, "started_at": _stamp(at), "completed_at": _stamp(at),
            "external_request_id": None, "external_object_id": None,
            "account_connection_snapshot": {}, "error_class": classification["classification"],
            "last_error_code": error.code, "last_error_at": _stamp(at),
            "resolution_reason": None, "resolved_by": None, "resolved_at": None, "created_at": _stamp(at),
        }
        _validate("delivery-attempt", attempt)
        accepted = self.idempotency.accept_attempt(
            org_id=tenant, actor_id=actor, trace_id=trace_id,
            idempotency_key=f"attempt:{original_key}:{attempt_no}", attempt=attempt,
        )
        if classification["terminal_status"] == "dead_letter":
            dead = self.dead_letter.dead_letter(
                org_id=tenant, actor_id=actor, trace_id=trace_id,
                idempotency_key=f"dead-letter:{original_key}:{attempt_no}",
                delivery_attempt=accepted, reason=classification["reason"], occurred_at=at,
            )
            return {"status": "dead_letter", "delivery_attempt": dead["delivery_attempt"],
                    "publication_record": dead["publication_record"], "human_task": dead["human_task"],
                    "classification": classification, "side_effect_triggered": False}
        return {
            "status": "retry_pending" if classification["retryable"] else "failed",
            "delivery_attempt": accepted, "classification": classification,
            "side_effect_triggered": False,
        }


__all__ = ["FakeDeliveryWorkflowService", "FakeWorkflowError"]
