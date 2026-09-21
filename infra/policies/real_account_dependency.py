"""GOV-009 account dependency status without accessing any real account."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import json

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "docs/governance/real-account-dependency-v1.yaml"
SCHEMA_PATH = ROOT / "packages/contracts/jsonschema/real-account-dependency.schema.json"


def load_dependency() -> dict:
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    return policy


def milestone_state(now: datetime) -> str:
    """A missed deadline escalates; it never silently unlocks real delivery."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must have a timezone")
    policy = load_dependency()
    due = datetime.fromisoformat(policy["latest_evidence_due_at"])
    if policy["status"] == "verified":
        return "evidence_verified_pending_go_no_go"
    if now > due:
        return "overdue_escalate_no_go"
    if now >= due - timedelta(days=policy["escalation_days_before_due"]):
        return "escalation_window_no_go"
    return "pending_no_go"


def allowed_distribution_modes() -> tuple[str, ...]:
    """Current baseline has no verified account or real-platform capability."""
    policy = load_dependency()
    if policy["status"] != "unavailable":
        raise ValueError("updated account status requires a new policy version and Go/No-Go")
    return tuple(policy["unavailable_fallback"]["allowed_modes"])
