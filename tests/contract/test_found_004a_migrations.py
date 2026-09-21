from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/migration-framework-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/migration-baseline.schema.json"
FOUNDATION_SCHEMA = ROOT / "packages/contracts/jsonschema/foundation.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_004a_migration_baseline.py"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_migration_baseline_contract_and_foundation_union_are_aligned() -> None:
    baseline = load_yaml(BASELINE)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    foundation = json.loads(FOUNDATION_SCHEMA.read_text(encoding="utf-8"))

    assert baseline["baseline_key"] == "migration-framework"
    assert baseline["tool"] == "alembic"
    assert baseline["expand_contract_policy"] == "expand_then_contract"
    assert baseline["legacy_sql_baseline"]["rewrite_existing_revisions"] is False
    assert baseline["checks"] == {
        "single_head": True,
        "reversible_upgrade_downgrade": True,
        "destructive_upgrade_sql": False,
        "production_secrets": False,
        "external_network_calls": False,
    }
    assert schema["properties"]["baseline_key"]["const"] == "migration-framework"
    assert schema["properties"]["fixture"]["properties"]["default_url"]["const"] == "sqlite:///:memory:"
    assert {item["$ref"] for item in foundation["oneOf"]} >= {"./migration-baseline.schema.json"}


def test_checker_accepts_current_revision_and_reports_single_head() -> None:
    from scripts.check_migrations import analyze_migrations

    report = analyze_migrations(ROOT / "packages/db/migrations/versions")
    assert report["ok"] is True
    assert len(report["heads"]) == 1
    # The migration graph now includes task-owned revisions in addition to
    # the original FOUND/GOV baselines.
    assert re.fullmatch(r"\d{8}_[a-z0-9]+_[a-z0-9_]+", report["heads"][0])
    assert report["revision_count"] >= 2


def test_alembic_upgrade_is_idempotent_and_downgrade_restores_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic import command
    from alembic.config import Config
    import sqlalchemy as sa

    database = tmp_path / "migration.db"
    database_url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    from scripts.check_migrations import analyze_migrations

    expected_head = analyze_migrations(ROOT / "packages/db/migrations/versions")["heads"][0]

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM migration_framework_baselines")
        ).scalar_one() == 1
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == expected_head

    command.downgrade(config, "base")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("migration_framework_baselines")
        assert connection.execute(sa.text("SELECT COUNT(*) FROM alembic_version")).scalar_one() == 0


def _write_revision(directory: Path, filename: str, revision: str, down_revision: str | None, body: str = "") -> None:
    down = repr(down_revision)
    directory.joinpath(filename).write_text(
        "revision = " + repr(revision) + "\n"
        "down_revision = " + down + "\n"
        "branch_labels = None\n"
        "depends_on = None\n\n"
        "def upgrade():\n"
        + (body or "    pass\n")
        + "\n"
        "def downgrade():\n"
        "    pass\n",
        encoding="utf-8",
    )


def test_checker_rejects_multiple_heads_and_invalid_names(tmp_path: Path) -> None:
    from scripts.check_migrations import analyze_migrations

    _write_revision(tmp_path, "20260916_found_004a_first.py", "first", None)
    _write_revision(tmp_path, "20260916_found_004a_second.py", "second", None)
    _write_revision(tmp_path, "bad-name.py", "third", "first")
    report = analyze_migrations(tmp_path)
    assert any(error.startswith("MIGRATION_HEAD_INVALID") for error in report["errors"])
    assert any(error.startswith("MIGRATION_NAME_INVALID") for error in report["errors"])


def test_checker_rejects_missing_reversible_functions(tmp_path: Path) -> None:
    tmp_path.joinpath("20260916_found_004a_missing.py").write_text(
        "revision = 'missing'\n"
        "down_revision = None\n"
        "def upgrade():\n"
        "    pass\n",
        encoding="utf-8",
    )
    from scripts.check_migrations import analyze_migrations

    report = analyze_migrations(tmp_path)
    assert any(error.startswith("MIGRATION_NOT_REVERSIBLE") for error in report["errors"])


@pytest.mark.parametrize(
    "body, expected",
    [
        ("    op.drop_table('unsafe')\n", "DESTRUCTIVE_MIGRATION_BLOCKED"),
        ("    op.drop_column('unsafe', 'column')\n", "DESTRUCTIVE_MIGRATION_BLOCKED"),
        ("    import requests\n", "MIGRATION_EXTERNAL_NETWORK_BLOCKED"),
        ("    secret = 'token=not-a-secret'\n", "MIGRATION_SECRET_BLOCKED"),
    ],
)
def test_checker_rejects_destructive_network_and_secret_patterns(
    tmp_path: Path, body: str, expected: str
) -> None:
    _write_revision(tmp_path, "20260916_found_004a_invalid.py", "invalid", None, body)
    from scripts.check_migrations import analyze_migrations

    report = analyze_migrations(tmp_path)
    assert any(error.startswith(expected) for error in report["errors"])
