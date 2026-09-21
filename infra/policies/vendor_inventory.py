"""GOV-010 evidence completeness checks; no vendor is authorized here."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import json

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "docs/governance/vendor-inventory-v1.yaml"
SCHEMA_PATH = ROOT / "packages/contracts/jsonschema/vendor-inventory.schema.json"


def load_inventory() -> dict:
    inventory = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(inventory)
    ids = [vendor["vendor_id"] for vendor in inventory["vendors"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate vendor_id")
    return inventory


def missing_vendor_evidence(vendor: Mapping[str, object]) -> tuple[str, ...]:
    """Report gaps only. Complete references still require independent review."""
    missing: list[str] = []
    if vendor.get("selection_status") != "approved":
        missing.append("approved_selection")
    if not vendor.get("processing_regions"):
        missing.append("processing_regions")
    if vendor.get("retention_days") is None:
        missing.append("retention_days")
    for field in ("contract_ref", "dpa_ref", "exit_plan_ref", "deletion_proof_ref", "owner_approval_ref"):
        if not vendor.get(field):
            missing.append(field)
    subprocessors = vendor.get("subprocessors")
    if not isinstance(subprocessors, Mapping) or subprocessors.get("status") not in {"none_attested", "listed"} or not subprocessors.get("review_ref"):
        missing.append("subprocessors_review_ref")
    return tuple(missing)
