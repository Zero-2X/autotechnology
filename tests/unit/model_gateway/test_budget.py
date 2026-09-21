from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest

from modules.model_gateway import (
    BudgetError,
    BudgetService,
    FakeModelProvider,
    ModelError,
    ModelGateway,
    ModelRequest,
)


ORG = "org-budget"
OTHER_ORG = "org-other"
ACTOR = "actor-budget"
STAMP = datetime(2026, 9, 19, 10, 0, tzinfo=timezone.utc)


def request(*, task_id: str = "task-a", budget_cents: int = 3) -> ModelRequest:
    return ModelRequest(
        "fake-model", "prompt/v1", {"topic": "synthetic"}, None, 100, budget_cents,
        "trace-budget", ORG, task_id,
    )


def policy_values(*, key: str = "budget-policy") -> dict:
    return {
        "org_id": ORG,
        "actor_id": ACTOR,
        "trace_id": "trace-budget",
        "idempotency_key": key,
        "policy_key": "model.budget",
        "version_no": 1,
        "expected_previous_version": 0,
        "limits": [
            {"scope": "org", "period": "day", "key": None, "limit_cents": 5},
            {"scope": "org", "period": "month", "key": None, "limit_cents": 10},
            {"scope": "task", "period": "task", "key": "task-a", "limit_cents": 3},
            {"scope": "model", "period": "month", "key": "fake-model", "limit_cents": 4},
        ],
    }


def setup_gateway(*, cost_cents: int = 2) -> tuple[ModelGateway, BudgetService, str]:
    budget = BudgetService(clock=lambda: STAMP)
    gateway = ModelGateway({"fake": FakeModelProvider(cost_cents=cost_cents)}, budget_service=budget)
    config = gateway.register_config(
        org_id=ORG, provider="fake", model="fake-model", data_region="local", retention_policy="synthetic"
    )
    gateway.register_budget_policy(**policy_values())
    return gateway, budget, config.id


def test_budget_reserves_before_provider_and_denies_task_overrun_with_audit() -> None:
    gateway, budget, config_id = setup_gateway()
    first = gateway.call(org_id=ORG, config_id=config_id, request=request(), idempotency_key="call-budget-1")
    assert first.cost_cents == 2
    assert gateway.providers["fake"].call_count == 1
    assert budget.usage_for(org_id=ORG, task_id="task-a")["total_cost_cents"] == 2

    with pytest.raises(ModelError) as denied:
        gateway.call(org_id=ORG, config_id=config_id, request=request(), idempotency_key="call-budget-2")
    assert denied.value.code == "BUDGET_EXCEEDED"
    assert gateway.providers["fake"].call_count == 1
    failed_id = gateway.idempotency[(ORG, "call-budget-2")][1]
    assert gateway.calls[failed_id].status == "budget_exceeded"
    assert any(event["type"] == "model.budget.exceeded" and event["task_id"] == "task-a" for event in budget.events)


def test_budget_idempotency_replays_policy_and_denied_call_without_new_reservation() -> None:
    gateway, budget, config_id = setup_gateway()
    first = gateway.register_budget_policy(**policy_values())
    replay = gateway.register_budget_policy(**policy_values())
    assert replay == first
    gateway.call(org_id=ORG, config_id=config_id, request=request(), idempotency_key="call-budget-1")
    with pytest.raises(ModelError) as denied:
        gateway.call(org_id=ORG, config_id=config_id, request=request(), idempotency_key="call-budget-2")
    assert denied.value.code == "BUDGET_EXCEEDED"
    replayed_denial = gateway.call(
        org_id=ORG, config_id=config_id, request=request(), idempotency_key="call-budget-2"
    )
    assert replayed_denial.status == "budget_exceeded"
    with pytest.raises(ModelError) as conflict:
        gateway.call(org_id=ORG, config_id=config_id, request=request(budget_cents=2), idempotency_key="call-budget-2")
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert len(budget.reservations) == 0


def test_budget_policy_rejects_missing_dimension_duplicate_limits_and_stale_versions() -> None:
    service = BudgetService(clock=lambda: STAMP)
    values = policy_values()
    with pytest.raises(BudgetError) as missing:
        service.register_policy(**{**values, "limits": values["limits"][:2]})
    assert missing.value.code == "INVALID_BUDGET_POLICY"
    duplicate = values["limits"] + [values["limits"][0]]
    with pytest.raises(BudgetError) as repeated:
        service.register_policy(**{**values, "limits": duplicate})
    assert repeated.value.code == "INVALID_BUDGET_POLICY"
    over_cap = [dict(item) for item in values["limits"]]
    over_cap[0]["limit_cents"] = 2501
    with pytest.raises(BudgetError) as governance:
        service.register_policy(**{**values, "idempotency_key": "policy-over-cap", "limits": over_cap})
    assert governance.value.code == "BUDGET_LIMIT_EXCEEDS_GOVERNANCE"
    service.register_policy(**values)
    with pytest.raises(BudgetError) as stale:
        service.register_policy(**{**values, "idempotency_key": "policy-stale", "version_no": 3, "expected_previous_version": 1})
    assert stale.value.code == "BUDGET_VERSION_CONFLICT"


def test_budget_periods_roll_over_but_month_usage_remains_and_tenant_isolation_holds() -> None:
    current = [STAMP]
    budget = BudgetService(clock=lambda: current[0])
    values = policy_values()
    values["limits"] = [
        {"scope": "org", "period": "day", "key": None, "limit_cents": 2},
        {"scope": "org", "period": "month", "key": None, "limit_cents": 3},
        {"scope": "task", "period": "task", "key": "task-a", "limit_cents": 5},
        {"scope": "model", "period": "month", "key": "fake-model", "limit_cents": 5},
    ]
    budget.register_policy(**values)
    reservation, decision = budget.reserve(
        org_id=ORG, task_id="task-a", model="fake-model", requested_cents=2,
        idempotency_key="rollover-1", trace_id="trace-budget",
    )
    assert decision.allowed and reservation is not None
    budget.settle(reservation_id=reservation.id, call_id="call-rollover", actual_cost_cents=2, status="succeeded")
    current[0] = STAMP + timedelta(days=1)
    reservation, decision = budget.reserve(
        org_id=ORG, task_id="task-b", model="fake-model", requested_cents=2,
        idempotency_key="rollover-2", trace_id="trace-budget",
    )
    assert not decision.allowed
    assert decision.period == "month"
    foreign, foreign_decision = budget.reserve(
        org_id=OTHER_ORG, task_id="task-a", model="fake-model", requested_cents=1,
        idempotency_key="rollover-foreign", trace_id="trace-budget",
    )
    assert foreign is None
    assert not foreign_decision.allowed
    assert foreign_decision.reason == "budget_policy_missing"


def test_concurrent_idempotent_calls_invoke_provider_once() -> None:
    gateway, _, config_id = setup_gateway()

    def invoke():
        return gateway.call(
            org_id=ORG, config_id=config_id, request=request(), idempotency_key="concurrent-budget-call"
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: invoke(), range(2)))
    assert results[0].id == results[1].id
    assert gateway.providers["fake"].call_count == 1


def test_budget_decision_contract_contains_no_request_body() -> None:
    budget = BudgetService(clock=lambda: STAMP)
    values = policy_values()
    budget.register_policy(**values)
    _, decision = budget.reserve(
        org_id=ORG, task_id="task-a", model="fake-model", requested_cents=10,
        idempotency_key="decision-contract", trace_id="trace-budget",
    )
    event = decision.as_contract(
        org_id=ORG, task_id="task-a", model="fake-model", trace_id="trace-budget", occurred_at=STAMP.isoformat()
    )
    assert event["decision"] == "deny"
    assert "topic" not in json.dumps(event)
