"""Tenant-scoped model budget policies, reservations, and cost facts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,199}$")
_SCOPES = frozenset({"org", "task", "model"})
_PERIODS = frozenset({"task", "day", "month"})
_GOVERNANCE_CAPS = {"task": 200, "day": 2500, "month": 30000}
_SETTLEMENT_STATUSES = frozenset({"succeeded", "failed", "timed_out", "budget_exceeded"})


class BudgetError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BudgetLimit:
    scope: str
    period: str
    limit_cents: int
    key: str | None = None


@dataclass(frozen=True)
class BudgetPolicy:
    id: str
    org_id: str
    policy_key: str
    version_no: int
    limits: tuple[BudgetLimit, ...]
    content_hash: str
    created_by: str
    created_at: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org_id": self.org_id,
            "policy_key": self.policy_key,
            "version_no": self.version_no,
            "status": "registered",
            "limits": [
                {"scope": item.scope, "period": item.period, "key": item.key, "limit_cents": item.limit_cents}
                for item in self.limits
            ],
            "content_hash": self.content_hash,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class BudgetReservation:
    id: str
    org_id: str
    policy_id: str
    task_id: str
    model: str
    requested_cents: int
    idempotency_key: str
    trace_id: str
    created_at: str


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str
    policy_id: str | None = None
    scope: str | None = None
    period: str | None = None
    limit_cents: int | None = None
    used_cents: int = 0
    requested_cents: int = 0

    def as_contract(self, *, org_id: str, task_id: str, model: str, trace_id: str, occurred_at: str) -> dict[str, Any]:
        return {
            "id": str(uuid4()),
            "org_id": org_id,
            "policy_id": self.policy_id,
            "task_id": task_id,
            "model": model,
            "decision": "allow" if self.allowed else "deny",
            "reason": self.reason,
            "scope": self.scope,
            "period": self.period,
            "limit_cents": self.limit_cents,
            "used_cents": self.used_cents,
            "requested_cents": self.requested_cents,
            "trace_id": trace_id,
            "occurred_at": occurred_at,
        }


class BudgetService:
    """Reserve request budgets before provider work and settle actual costs after it."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.policies: dict[str, BudgetPolicy] = {}
        self._latest: dict[tuple[str, str], int] = {}
        self._commands: dict[tuple[str, str], tuple[str, str]] = {}
        self.reservations: dict[str, BudgetReservation] = {}
        self._reservations_by_key: dict[tuple[str, str], tuple[str, str]] = {}
        self.usage: list[dict[str, Any]] = []
        self._settled: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self._lock = RLock()

    def register_policy(
        self,
        *,
        org_id: str,
        actor_id: str,
        trace_id: str,
        idempotency_key: str,
        policy_key: str,
        version_no: int,
        expected_previous_version: int,
        limits: Sequence[Mapping[str, Any]],
    ) -> BudgetPolicy:
        tenant = self._text(org_id, "org_id")
        actor = self._text(actor_id, "actor_id")
        trace = self._text(trace_id, "trace_id")
        command_key = self._text(idempotency_key, "idempotency_key", maximum=200)
        if len(command_key) < 8:
            raise BudgetError("INVALID_BUDGET_CONTEXT", "idempotency_key must be 8..200 characters")
        name = self._text(policy_key, "policy_key")
        if not isinstance(version_no, int) or isinstance(version_no, bool) or version_no < 1:
            raise BudgetError("INVALID_BUDGET_POLICY", "version_no must be positive")
        if not isinstance(expected_previous_version, int) or isinstance(expected_previous_version, bool) or expected_previous_version < 0:
            raise BudgetError("INVALID_BUDGET_POLICY", "expected_previous_version must be non-negative")
        normalized = self._limits(limits)
        body = {
            "policy_key": name,
            "version_no": version_no,
            "expected_previous_version": expected_previous_version,
            "limits": [item.__dict__ for item in normalized],
        }
        payload_hash = self._hash(body)
        with self._lock:
            cached = self._commands.get((tenant, command_key))
            if cached is not None:
                if cached[0] != payload_hash:
                    raise BudgetError("IDEMPOTENCY_KEY_REUSED", "budget policy command payload differs")
                return deepcopy(self.policies[cached[1]])
            current = self._latest.get((tenant, name), 0)
            if expected_previous_version != current or version_no != current + 1:
                raise BudgetError("BUDGET_VERSION_CONFLICT", "budget policy version is stale")
            stamp = self._now()
            policy = BudgetPolicy(
                id=str(uuid4()),
                org_id=tenant,
                policy_key=name,
                version_no=version_no,
                limits=normalized,
                content_hash=self._hash({**body, "expected_previous_version": None}),
                created_by=actor,
                created_at=stamp,
            )
            self.policies[policy.id] = policy
            self._latest[(tenant, name)] = version_no
            self._commands[(tenant, command_key)] = (payload_hash, policy.id)
            self.events.append({
                "type": "model.budget.policy.registered",
                "org_id": tenant,
                "actor_id": actor,
                "trace_id": trace,
                "policy_id": policy.id,
                "content_hash": policy.content_hash,
                "version_no": version_no,
            })
            return deepcopy(policy)

    def reserve(
        self,
        *,
        org_id: str,
        task_id: str,
        model: str,
        requested_cents: int,
        idempotency_key: str,
        trace_id: str,
    ) -> tuple[BudgetReservation | None, BudgetDecision]:
        tenant = self._text(org_id, "org_id")
        task = self._text(task_id, "task_id")
        model_name = self._text(model, "model")
        key = self._text(idempotency_key, "idempotency_key", maximum=200)
        trace = self._text(trace_id, "trace_id")
        if isinstance(requested_cents, bool) or not isinstance(requested_cents, int) or requested_cents < 0:
            raise BudgetError("INVALID_BUDGET_REQUEST", "requested_cents must be non-negative")
        with self._lock:
            existing = self._reservations_by_key.get((tenant, key))
            if existing is not None:
                reservation = self.reservations[existing[1]]
                fingerprint = self._hash({"requested_cents": requested_cents, "task_id": task, "model": model_name})
                if existing[0] != fingerprint:
                    raise BudgetError("IDEMPOTENCY_KEY_REUSED", "budget reservation payload differs")
                return deepcopy(reservation), BudgetDecision(True, "idempotent_replay", reservation.policy_id, used_cents=0, requested_cents=reservation.requested_cents)
            policy = self._active_policy(tenant)
            if policy is None:
                decision = BudgetDecision(False, "budget_policy_missing", requested_cents=requested_cents)
                self.events.append({
                    "type": "model.budget.policy_missing",
                    "org_id": tenant,
                    "task_id": task,
                    "model": model_name,
                    "trace_id": trace,
                    "requested_cents": requested_cents,
                    "reason": decision.reason,
                })
                return None, decision
            now = self._now_dt()
            for limit in self._applicable_limits(policy.limits, task, model_name):
                used = self._used_for(limit, tenant, task, model_name, now)
                reserved = self._reserved_for(limit, tenant, task, model_name, now)
                if used + reserved + requested_cents > limit.limit_cents:
                    decision = BudgetDecision(
                        False,
                        "budget_exceeded",
                        policy.id,
                        limit.scope,
                        limit.period,
                        limit.limit_cents,
                        used + reserved,
                        requested_cents,
                    )
                    self.events.append({
                        "type": "model.budget.exceeded",
                        "org_id": tenant,
                        "task_id": task,
                        "model": model_name,
                        "trace_id": trace,
                        "policy_id": policy.id,
                        "scope": limit.scope,
                        "period": limit.period,
                        "limit_cents": limit.limit_cents,
                        "used_cents": used + reserved,
                        "requested_cents": requested_cents,
                        "reason": decision.reason,
                    })
                    return None, decision
            reservation = BudgetReservation(
                id=str(uuid4()),
                org_id=tenant,
                policy_id=policy.id,
                task_id=task,
                model=model_name,
                requested_cents=requested_cents,
                idempotency_key=key,
                trace_id=trace,
                created_at=now.isoformat(),
            )
            self.reservations[reservation.id] = reservation
            self._reservations_by_key[(tenant, key)] = (self._hash({"requested_cents": requested_cents, "task_id": task, "model": model_name}), reservation.id)
            self.events.append({
                "type": "model.budget.reserved",
                "org_id": tenant,
                "task_id": task,
                "model": model_name,
                "trace_id": trace,
                "policy_id": policy.id,
                "reservation_id": reservation.id,
                "requested_cents": requested_cents,
            })
            return deepcopy(reservation), BudgetDecision(True, "within_budget", policy.id, requested_cents=requested_cents)

    def settle(self, *, reservation_id: str, call_id: str, actual_cost_cents: int, status: str, occurred_at: datetime | None = None) -> dict[str, Any]:
        if isinstance(actual_cost_cents, bool) or not isinstance(actual_cost_cents, int) or actual_cost_cents < 0:
            raise BudgetError("INVALID_BUDGET_SETTLEMENT", "actual_cost_cents must be non-negative")
        with self._lock:
            existing = self._settled.get(reservation_id)
            if existing is not None:
                return deepcopy(existing)
            reservation = self.reservations.pop(reservation_id, None)
            if reservation is None:
                raise BudgetError("BUDGET_RESERVATION_NOT_FOUND", "budget reservation does not exist")
            self._reservations_by_key.pop((reservation.org_id, reservation.idempotency_key), None)
            stamp = occurred_at or self._now_dt()
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise BudgetError("INVALID_BUDGET_SETTLEMENT", "occurred_at must include a timezone")
            normalized_status = self._text(status, "status")
            if normalized_status not in _SETTLEMENT_STATUSES:
                raise BudgetError("INVALID_BUDGET_SETTLEMENT", "status is invalid")
            fact = {
                "id": str(uuid4()),
                "org_id": reservation.org_id,
                "policy_id": reservation.policy_id,
                "task_id": reservation.task_id,
                "model": reservation.model,
                "call_id": self._text(call_id, "call_id"),
                "requested_cents": reservation.requested_cents,
                "cost_cents": actual_cost_cents,
                "status": normalized_status,
                "occurred_at": stamp.isoformat(),
            }
            self.usage.append(fact)
            self._settled[reservation_id] = fact
            self.events.append({
                "type": "model.budget.settled",
                "org_id": reservation.org_id,
                "task_id": reservation.task_id,
                "model": reservation.model,
                "policy_id": reservation.policy_id,
                "reservation_id": reservation.id,
                "call_id": fact["call_id"],
                "cost_cents": actual_cost_cents,
                "status": fact["status"],
            })
            return deepcopy(fact)

    def usage_for(self, *, org_id: str, task_id: str | None = None, model: str | None = None) -> dict[str, int]:
        tenant = self._text(org_id, "org_id")
        with self._lock:
            records = [fact for fact in self.usage if fact["org_id"] == tenant]
            if task_id is not None:
                records = [fact for fact in records if fact["task_id"] == task_id]
            if model is not None:
                records = [fact for fact in records if fact["model"] == model]
            return {
                "total_cost_cents": sum(int(fact["cost_cents"]) for fact in records),
                "successful_calls": sum(fact["status"] == "succeeded" for fact in records),
                "failed_calls": sum(fact["status"] != "succeeded" for fact in records),
            }

    def _active_policy(self, tenant: str) -> BudgetPolicy | None:
        candidates = [policy for policy in self.policies.values() if policy.org_id == tenant]
        return max(candidates, key=lambda policy: policy.version_no) if candidates else None

    @staticmethod
    def _applicable_limits(limits: Sequence[BudgetLimit], task: str, model: str) -> tuple[BudgetLimit, ...]:
        selected: list[BudgetLimit] = []
        for scope in ("org", "task", "model"):
            for period in sorted(_PERIODS):
                candidates = [item for item in limits if item.scope == scope and item.period == period]
                if scope == "org":
                    selected.extend(candidates[:1])
                    continue
                exact = [item for item in candidates if item.key == (task if scope == "task" else model)]
                wildcard = [item for item in candidates if item.key == "*"]
                selected.extend((exact or wildcard)[:1])
        return tuple(selected)

    def _used_for(self, limit: BudgetLimit, tenant: str, task: str, model: str, now: datetime) -> int:
        return sum(
            int(fact["cost_cents"])
            for fact in self.usage
            if fact["org_id"] == tenant and self._matches(limit, fact["task_id"], fact["model"], fact["occurred_at"], task, model, now)
        )

    def _reserved_for(self, limit: BudgetLimit, tenant: str, task: str, model: str, now: datetime) -> int:
        return sum(
            reservation.requested_cents
            for reservation in self.reservations.values()
            if reservation.org_id == tenant and self._matches(limit, reservation.task_id, reservation.model, reservation.created_at, task, model, now)
        )

    @staticmethod
    def _matches(limit: BudgetLimit, task_value: str, model_value: str, stamp: str, task: str, model: str, now: datetime) -> bool:
        if limit.scope == "task" and limit.key not in {"*", task_value}:
            return False
        if limit.scope == "model" and limit.key not in {"*", model_value}:
            return False
        if limit.period == "task" and task_value != task:
            return False
        try:
            timestamp = datetime.fromisoformat(stamp)
        except ValueError:
            return False
        if limit.period == "day":
            return timestamp.astimezone(timezone.utc).date() == now.astimezone(timezone.utc).date()
        if limit.period == "month":
            current = now.astimezone(timezone.utc)
            value = timestamp.astimezone(timezone.utc)
            return (value.year, value.month) == (current.year, current.month)
        return True

    def _limits(self, values: Sequence[Mapping[str, Any]]) -> tuple[BudgetLimit, ...]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
            raise BudgetError("INVALID_BUDGET_POLICY", "at least one budget limit is required")
        result: list[BudgetLimit] = []
        seen: set[tuple[str, str, str | None]] = set()
        for value in values:
            if not isinstance(value, Mapping):
                raise BudgetError("INVALID_BUDGET_POLICY", "budget limit must be an object")
            scope = value.get("scope")
            period = value.get("period")
            key = value.get("key")
            if scope not in _SCOPES or period not in _PERIODS:
                raise BudgetError("INVALID_BUDGET_POLICY", "scope or period is invalid")
            if scope == "org":
                if key is not None:
                    raise BudgetError("INVALID_BUDGET_POLICY", "organization limit cannot have a key")
            else:
                if not isinstance(key, str) or not key.strip() or len(key.strip()) > 200:
                    raise BudgetError("INVALID_BUDGET_POLICY", "limit.key is invalid")
                key = key.strip()
                if key != "*" and not _KEY.fullmatch(key):
                    raise BudgetError("INVALID_BUDGET_POLICY", "limit.key is invalid")
            amount = value.get("limit_cents")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise BudgetError("INVALID_BUDGET_POLICY", "limit_cents must be positive")
            if amount > _GOVERNANCE_CAPS[period]:
                raise BudgetError("BUDGET_LIMIT_EXCEEDS_GOVERNANCE", "limit exceeds the GOV-008 period cap")
            identity = (scope, period, key)
            if identity in seen:
                raise BudgetError("INVALID_BUDGET_POLICY", "budget limits must be unique")
            seen.add(identity)
            result.append(BudgetLimit(scope, period, amount, key))
        if not {item.scope for item in result} >= _SCOPES:
            raise BudgetError("INVALID_BUDGET_POLICY", "org, task, and model limits are required")
        return tuple(sorted(result, key=lambda item: (item.scope, item.period, item.key or "")))

    def _now_dt(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise BudgetError("INVALID_BUDGET_CLOCK", "clock must return a timezone-aware datetime")
        return value

    def _now(self) -> str:
        return self._now_dt().isoformat()

    @staticmethod
    def _text(value: object, field: str, *, maximum: int = 256) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum or not _KEY.fullmatch(value.strip()):
            raise BudgetError("INVALID_BUDGET_CONTEXT", f"{field} is invalid")
        return value.strip()

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


__all__ = ["BudgetDecision", "BudgetError", "BudgetLimit", "BudgetPolicy", "BudgetReservation", "BudgetService"]
