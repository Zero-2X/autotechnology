from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "docs/governance/release-levels-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/release-levels.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260915_gov_002_release_levels.sql"


def test_release_levels_define_ordered_gates_and_account_boundaries() -> None:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) <= set(policy)
    levels = policy["levels"]
    assert [level["level_key"] for level in levels] == ["architecture_mvp", "distribution_pilot", "scale"]
    assert levels[0]["requires_real_account"] is False
    assert levels[0]["allowed_distribution_modes"] == ["manual_export", "simulation"]
    assert levels[1]["requires_real_account"] is True
    assert levels[1]["allowed_distribution_modes"] == ["manual_export", "simulation", "draft_only"]
    assert levels[2]["allowed_distribution_modes"][-1] == "authorized_api"
    for level in levels:
        assert level["entry_gates"]
        assert level["exit_gates"]
        assert level["rollback_rule"]
    datetime.fromisoformat(policy["effective_at"])
    assert any("真实 Token" in item for item in levels[0]["forbidden_capabilities"])
    assert any("旧 synthetic Intent" in item for item in levels[1]["forbidden_capabilities"])


def test_release_level_migration_is_idempotent() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    connection.execute(
        "INSERT INTO release_level_policies VALUES (?, ?, ?, ?, ?, ?)",
        ("release-levels", 1, "active", "[]", "2026-09-15T00:00:00+08:00", "team/governance"),
    )
    assert connection.execute("SELECT COUNT(*) FROM release_level_policies").fetchone()[0] == 1
