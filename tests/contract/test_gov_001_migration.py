from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "packages/db/migrations/versions/20260915_gov_001_governance_scope.sql"


def test_gov_001_migration_creates_versioned_scope_table() -> None:
    connection = sqlite3.connect(":memory:")
    connection.executescript(MIGRATION.read_text(encoding="utf-8"))
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(governance_scopes)").fetchall()
    }
    assert {"scope_key", "scope_version", "status", "vertical_name", "locked_at"} <= columns
    connection.execute(
        "INSERT INTO governance_scopes "
        "(scope_key, scope_version, status, vertical_name, vertical_definition, "
        "primary_topics, product_capabilities, languages, content_types, knowledge_site, "
        "distribution_modes, account_strategy, initial_in_scope, initial_out_of_scope, locked_at, locked_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ai-technology-engineering", 1, "locked", "AI 技术与应用工程", "definition", "[]", "[]", "[]", "[]", "first_party", "[]", "deferred_to_M2", "[]", "[]", "2026-09-15T00:00:00+08:00", "team/governance"),
    )
    assert connection.execute("SELECT COUNT(*) FROM governance_scopes").fetchone()[0] == 1
