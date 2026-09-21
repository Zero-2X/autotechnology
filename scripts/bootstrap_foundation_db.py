"""Apply the accepted legacy SQL baseline, then Alembic, on one connection.

Explicit database URL required; never reads DATABASE_URL implicitly. Run once
under exclusive maintenance access. This does not seed business data.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "packages/db/migrations/versions"
LEGACY_FILES = (
    "20260915_gov_001_governance_scope.sql",
    "20260915_gov_002_release_levels.sql",
    "20260915_gov_003_raci_policy.sql",
    "20260915_gov_004_risk_policy.sql",
    "20260915_gov_005_policy_card.sql",
    "20260915_gov_006_tech_stack_baseline.sql",
    "20260916_found_000_repository_inventory.sql",
    "20260916_found_001_repository_baseline.sql",
    "20260916_found_002_runtime_entry_baseline.sql",
    "20260916_found_003a_database_baseline.sql",
    "20260916_found_003b_storage_baseline.sql",
    "20260916_found_003d_task_jobs.sql",
)


def legacy_statements() -> list[str]:
    """Only the frozen plain SQL subset, not arbitrary future migration SQL."""
    statements = []
    for filename in LEGACY_FILES:
        pending = ""
        for line in (VERSIONS / filename).read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("--"):
                continue
            pending += line + "\n"
            if sqlite3.complete_statement(pending):
                statement = pending.strip()
                if not statement.startswith(("CREATE TABLE IF NOT EXISTS ", "CREATE INDEX IF NOT EXISTS ")):
                    raise ValueError(f"unapproved legacy SQL statement in {filename}")
                statements.append(statement)
                pending = ""
        if pending.strip():
            raise ValueError(f"incomplete legacy SQL in {filename}")
    return statements


def bootstrap(connection: sa.Connection) -> None:
    """Caller owns connection/transaction; existing tables and rows are retained."""
    if connection.dialect.name not in {"sqlite", "postgresql"}:
        raise ValueError("only SQLite fixtures and PostgreSQL are supported")
    statements = legacy_statements()  # Validate all files before any write.
    for statement in statements:
        connection.exec_driver_sql(statement)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "packages/db/migrations"))
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Explicit target; prefer local SQLite for verification")
    args = parser.parse_args()
    engine = sa.create_engine(args.database_url)
    try:
        with engine.begin() as connection:
            bootstrap(connection)
    finally:
        engine.dispose()
    print("Foundation baseline and Alembic upgrade completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
