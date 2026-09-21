import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
ID = "00000000-0000-4000-8000-000000000001"
SECOND = "00000000-0000-4000-8000-000000000002"
SCHEMA = json.loads((ROOT / "packages/contracts/jsonschema/approval.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def approved():
    return {
        "id": ID, "org_id": ID, "aggregate_type": "variant", "aggregate_id": ID,
        "aggregate_version": 1, "approval_type": "content", "status": "approved",
        "requested_by": ID, "reviewer_id": SECOND, "decision": "approved",
        "policy_snapshot_id": ID, "evidence_refs": [], "input_snapshot_hash": "a" * 64,
        "quorum_required": 2, "quorum_reached": 2, "decision_ids": [ID, SECOND],
        "reason": None, "expires_at": None, "created_at": "2026-09-16T00:00:00Z",
        "decided_at": "2026-09-16T00:01:00Z",
    }


def test_pending_and_approved_are_distinct_valid_shapes():
    VALIDATOR.validate(approved())
    pending = {**approved(), "status": "pending", "decision": None, "reviewer_id": None,
               "quorum_reached": 0, "decision_ids": [], "decided_at": None}
    VALIDATOR.validate(pending)


@pytest.mark.parametrize("field,value", [
    ("quorum_reached", 1), ("quorum_reached", -1), ("quorum_required", 3),
    ("decision_ids", [ID]), ("decision_ids", [ID, ID]), ("decision_ids", [ID, "invalid"]),
    ("decision", "rejected"), ("reviewer_id", None), ("decided_at", None),
    ("policy_snapshot_id", None), ("aggregate_version", 0),
])
def test_approved_without_quorum_or_decision_evidence_is_rejected(field, value):
    assert not VALIDATOR.is_valid({**approved(), field: value})
