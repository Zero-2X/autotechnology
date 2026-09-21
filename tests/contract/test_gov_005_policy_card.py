from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "docs/governance/policy-card-baseline-v1.yaml"
SNAPSHOT = ROOT / "docs/governance/policy-snapshot-synthetic-v1.yaml"
CARD_SCHEMA = ROOT / "packages/contracts/jsonschema/policy-card.schema.json"
SNAPSHOT_SCHEMA = ROOT / "packages/contracts/jsonschema/policy-snapshot.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260915_gov_005_policy_card.sql"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_baseline_policy_card_has_owner_review_evidence_and_expiry() -> None:
    card = _load(CARD)
    schema = _load(CARD_SCHEMA)
    assert set(schema["required"]) <= set(card)
    assert card["policy_key"] == "baseline-synthetic"
    assert card["policy_version"] == 1
    assert card["status"] == "active"
    assert card["policy_domain"] == "composite"
    assert card["owner_role"] == "governance_owner"
    assert card["reviewer_roles"] == ["policy_reviewer", "data_protection_owner"]
    assert len(card["evidence_refs"]) >= 3
    assert all(item["uri"] for item in card["evidence_refs"])
    assert len(card["rules"]) >= 3
    assert card["allowed_release_levels"] == ["architecture_mvp"]
    assert card["synthetic_only"] is True
    effective = datetime.fromisoformat(card["effective_at"])
    review_due = datetime.fromisoformat(card["review_due_at"])
    assert review_due > effective
    for forbidden in ("access_token", "refresh_token", "client_secret", "BEGIN PRIVATE KEY", "https://"):
        assert forbidden not in CARD.read_text(encoding="utf-8")


def test_synthetic_snapshot_is_account_free_and_matches_snapshot_contract() -> None:
    snapshot = _load(SNAPSHOT)
    schema = _load(SNAPSHOT_SCHEMA)
    assert set(schema["required"]) <= set(snapshot)
    assert snapshot["org_id"] is None
    assert snapshot["subject_id"] is None
    assert snapshot["account_policy_version"] is None
    assert snapshot["subject_ref"] == "synthetic:baseline-policy"
    assert snapshot["status"] == "active"
    assert snapshot["expires_at"] == snapshot["review_due_at"]
    assert snapshot["input_hash"] != snapshot["rules_hash"]
    assert snapshot["rules_hash"] != snapshot["snapshot_hash"]
    assert "manual_export" in _load(CARD)["rules"][1]["requirement"]
    text = SNAPSHOT.read_text(encoding="utf-8")
    for forbidden in ("access_token", "refresh_token", "client_secret", "BEGIN PRIVATE KEY", "http://", "https://"):
        assert forbidden not in text


def test_policy_card_migration_is_idempotent_and_versions_are_immutable() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    card_row = (
        "baseline-synthetic", 1, "active", "composite", "Baseline", "purpose", "governance_owner",
        "[]", "[]", "[]", "[\"architecture_mvp\"]", 1,
        "2026-09-16T00:00:00+08:00", "2026-10-16T00:00:00+08:00", "team/governance",
    )
    connection.execute("INSERT INTO policy_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", card_row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO policy_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", card_row)
    snapshot_row = (
        "snapshot-1", "baseline-synthetic", 1, None, "variant", "synthetic:baseline-policy",
        "[]", "a" * 64, "b" * 64, "c" * 64, "active", "2026-09-16T00:00:00+08:00",
        "2026-10-16T00:00:00+08:00", "2026-10-16T00:00:00+08:00",
    )
    connection.execute("INSERT INTO policy_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", snapshot_row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO policy_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", snapshot_row)
    assert connection.execute("SELECT COUNT(*) FROM policy_versions").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM policy_snapshots").fetchone()[0] == 1
