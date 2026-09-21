"""Pure GOV-008 budget, response, and recovery target checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "docs/governance/operational-targets-v1.yaml"
SCHEMA_PATH = ROOT / "packages/contracts/jsonschema/operational-targets.schema.json"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def load_targets() -> dict:
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    return policy


def _money(value: str | Decimal | None) -> Decimal | None:
    if value is None or isinstance(value, (float, bool)):
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return amount


def assess_budget(
    proposed: str | Decimal | None,
    workflow_spent: str | Decimal | None,
    daily_spent: str | Decimal | None,
    monthly_spent: str | Decimal | None,
) -> Decision:
    """Reject unknown cost and any projected cap breach before new work."""
    amounts = [_money(value) for value in (proposed, workflow_spent, daily_spent, monthly_spent)]
    if any(value is None for value in amounts):
        return Decision(False, "unknown_or_invalid_cost")
    proposed_amount, workflow, daily, monthly = amounts
    caps = load_targets()["cost_budget"]
    for name, spent, limit in (
        ("workflow", workflow, caps["per_workflow_limit"]),
        ("daily", daily, caps["daily_limit"]),
        ("monthly", monthly, caps["monthly_limit"]),
    ):
        if spent + proposed_amount > Decimal(limit):
            return Decision(False, f"{name}_budget_exceeded")
    return Decision(True, "within_budget")


def approval_deadline(risk_level: str, created_at: datetime) -> datetime:
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must have a timezone")
    levels = load_targets()["human_approval"]["risk_levels"]
    if risk_level not in levels:
        raise ValueError("unknown risk level")
    return created_at + timedelta(minutes=levels[risk_level]["first_response_minutes"])


def assess_recovery(failure_started_at: datetime, restored_at: datetime, latest_recovered_event_at: datetime) -> Decision:
    if any(value.tzinfo is None or value.utcoffset() is None for value in (failure_started_at, restored_at, latest_recovered_event_at)):
        return Decision(False, "missing_timezone")
    if restored_at < failure_started_at or latest_recovered_event_at > failure_started_at:
        return Decision(False, "invalid_recovery_timeline")
    targets = load_targets()["recovery"]
    if restored_at - failure_started_at > timedelta(minutes=targets["rto_minutes_maximum"]):
        return Decision(False, "rto_exceeded")
    if failure_started_at - latest_recovered_event_at > timedelta(minutes=targets["rpo_minutes_maximum"]):
        return Decision(False, "rpo_exceeded")
    return Decision(True, "recovery_targets_met")
