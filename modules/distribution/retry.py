"""Quota, Retry-After and deterministic delivery error classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid


class RetryPolicyError(DistributionError):
    pass


@dataclass(frozen=True)
class RetryDecision:
    classification: str
    retryable: bool
    retry_after_seconds: int | None
    manual_task_required: bool
    terminal_status: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification, "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds, "manual_task_required": self.manual_task_required,
            "terminal_status": self.terminal_status, "reason": self.reason,
        }


class RetryPolicyService:
    """Enforce tenant quotas and classify errors without performing retries."""

    _RETRYABLE = {"PLATFORM_RATE_LIMITED", "PLATFORM_UNAVAILABLE", "TIMEOUT", "OUTBOX_PUBLISH_RETRYABLE"}
    _UNKNOWN = {"PLATFORM_UNKNOWN", "OUTBOX_PUBLISH_UNKNOWN", "NETWORK_UNKNOWN"}

    def __init__(self, *, quota_limit: int = 10, window_seconds: int = 60) -> None:
        if type(quota_limit) is not int or quota_limit <= 0 or type(window_seconds) is not int or window_seconds <= 0:
            raise RetryPolicyError("INVALID_RETRY_POLICY", "quota_limit and window_seconds must be positive integers")
        self.quota_limit, self.window_seconds = quota_limit, window_seconds
        self._usage: dict[tuple[str, int], int] = {}
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._lock = RLock()

    def reserve(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                now: datetime | str | None = None, units: int = 1) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if type(units) is not int or units < 1:
            raise RetryPolicyError("INVALID_RETRY_POLICY", "units must be positive")
        at = _time(now, "now") or datetime.now(timezone.utc)
        bucket = int(at.timestamp()) // self.window_seconds
        digest = _hash({"operation": "reserve", "bucket": bucket, "units": units})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise RetryPolicyError("IDEMPOTENCY_KEY_REUSED", "quota reservation differs from prior request")
                return dict(prior[1])
            used = self._usage.get((tenant, bucket), 0)
            if used + units > self.quota_limit:
                next_window = (bucket + 1) * self.window_seconds
                retry_after = max(1, next_window - int(at.timestamp()))
                result = {"allowed": False, "remaining": max(0, self.quota_limit - used), "retry_after_seconds": retry_after,
                          "window_ends_at": _stamp(datetime.fromtimestamp(next_window, timezone.utc)), "units": units}
                self._commands[(tenant, key)] = (digest, result)
                self._audit("distribution.quota.exceeded", tenant, actor, trace, key, digest, result)
                return dict(result)
            self._usage[(tenant, bucket)] = used + units
            result = {"allowed": True, "remaining": self.quota_limit - used - units, "retry_after_seconds": None,
                      "window_ends_at": _stamp(datetime.fromtimestamp((bucket + 1) * self.window_seconds, timezone.utc)), "units": units}
            self._commands[(tenant, key)] = (digest, result)
            self._audit("distribution.quota.reserved", tenant, actor, trace, key, digest, result)
            return dict(result)

    def classify(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                 error_code: str, attempt_no: int, max_attempts: int, retry_after_seconds: int | None = None,
                 now: datetime | str | None = None) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(error_code, str) or not error_code.strip() or type(attempt_no) is not int or attempt_no < 1 or type(max_attempts) is not int or max_attempts < 1:
            raise RetryPolicyError("INVALID_RETRY_POLICY", "error_code and attempt bounds are invalid")
        if retry_after_seconds is not None and (type(retry_after_seconds) is not int or retry_after_seconds < 0):
            raise RetryPolicyError("INVALID_RETRY_POLICY", "retry_after_seconds must be nonnegative")
        at = _time(now, "now") or datetime.now(timezone.utc)
        code = error_code.strip()
        digest = _hash({"operation": "classify", "error_code": code, "attempt_no": attempt_no,
                        "max_attempts": max_attempts, "retry_after_seconds": retry_after_seconds})
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise RetryPolicyError("IDEMPOTENCY_KEY_REUSED", "classification differs from prior request")
                return dict(prior[1])
            if code in self._UNKNOWN:
                decision = RetryDecision("unknown", False, None, True, "unknown", "external result is unknown; manual verification required")
            elif code in self._RETRYABLE and attempt_no < max_attempts:
                wait = max(1, retry_after_seconds or 1) if code == "PLATFORM_RATE_LIMITED" else retry_after_seconds
                decision = RetryDecision("transient", True, wait, False, "pending", "transient delivery failure may be retried by an external scheduler")
            elif code in self._RETRYABLE:
                decision = RetryDecision("exhausted", False, None, True, "dead_letter", "retry limit reached; manual escalation required")
            else:
                decision = RetryDecision("deterministic", False, None, False, "failed", "deterministic delivery failure is not retryable")
            result = {**decision.as_dict(), "error_code": code, "attempt_no": attempt_no, "max_attempts": max_attempts, "classified_at": _stamp(at)}
            self._commands[(tenant, key)] = (digest, result)
            self._audit("distribution.delivery.error_classified", tenant, actor, trace, key, digest, result)
            if decision.manual_task_required:
                self._event("distribution.delivery.manual_escalation", tenant, actor, trace, key, result, at)
            return dict(result)

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str, digest: str, output: Mapping[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                           "idempotency_key": key, "input_hash": digest, "output_hash": _hash(output)})

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               payload: Mapping[str, Any], occurred_at: datetime) -> None:
        aggregate_id = str(uuid4())
        event_payload = {"aggregate_id": aggregate_id, "aggregate_version": 1, **dict(payload)}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "delivery_attempt", "aggregate_id": aggregate_id, "aggregate_version": 1,
                 "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                 "payload": event_payload, "payload_hash": _hash(event_payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise RetryPolicyError("INVALID_RETRY_EVENT", errors[0].message)
        self.events.append(event)


__all__ = ["RetryDecision", "RetryPolicyError", "RetryPolicyService"]
