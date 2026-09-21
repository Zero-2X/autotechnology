"""Deterministic GOV-007 decisions for the synthetic data policy.

This module evaluates a policy; it does not delete records or transfer data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping
import json

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "docs/governance/data-processing-policy-v1.yaml"
SCHEMA_PATH = ROOT / "packages/contracts/jsonschema/data-processing-policy.schema.json"
POLICY_SNAPSHOT = "baseline-synthetic-data/v1"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    policy_snapshot: str = POLICY_SNAPSHOT


def load_policy() -> dict:
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    return policy


def retention_deadline(data_class: str, purpose_completed_at: datetime, *, shorter_limit_at: datetime | None = None) -> datetime:
    """Return the project default deadline, bounded by an earlier applicable limit."""
    if purpose_completed_at.tzinfo is None or purpose_completed_at.utcoffset() is None:
        raise ValueError("purpose_completed_at must have a timezone")
    if shorter_limit_at is not None and (shorter_limit_at.tzinfo is None or shorter_limit_at.utcoffset() is None):
        raise ValueError("shorter_limit_at must have a timezone")
    classes = load_policy()["classification"]
    if data_class not in classes:
        raise ValueError("unknown data class")
    deadline = purpose_completed_at + timedelta(days=classes[data_class]["default_retention_days"])
    return min(deadline, shorter_limit_at) if shorter_limit_at is not None else deadline


def assess_deletion(target_results: Mapping[str, str]) -> Decision:
    """Completion needs evidence for every target, including backups and recipients."""
    expected = set(load_policy()["deletion"]["targets"])
    if set(target_results) != expected:
        return Decision(False, "target_inventory_incomplete")
    for target in sorted(expected):
        result = target_results[target]
        if result != "verified" and not (result.startswith("legal_exception:") and result.split(":", 1)[1].strip()):
            return Decision(False, f"target_unresolved:{target}")
    return Decision(True, "all_targets_accounted_for")


def assess_cross_border(request: Mapping[str, object]) -> Decision:
    """Allow only reviewed synthetic public content under the frozen baseline."""
    policy = load_policy()
    required = policy["cross_border"]["required_evidence"]
    if any(not isinstance(request.get(key), str) or not str(request[key]).strip() for key in required):
        return Decision(False, "missing_transfer_evidence")
    if request["policy_snapshot"] != POLICY_SNAPSHOT:
        return Decision(False, "policy_snapshot_mismatch")
    data_class = request["data_class"]
    if data_class not in policy["classification"]:
        return Decision(False, "unknown_data_class")
    if data_class != "public_content" or request.get("synthetic") is not True:
        return Decision(False, "manual_legal_review_and_new_policy_required")
    source = request["source_region"]
    destination = request["destination_region"]
    allowed_regions = policy["classification"][data_class]["allowed_regions"]
    if source == destination or source not in allowed_regions or destination not in allowed_regions:
        return Decision(False, "invalid_or_disallowed_route")
    return Decision(True, "reviewed_synthetic_public_route")
