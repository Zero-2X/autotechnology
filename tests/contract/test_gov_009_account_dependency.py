from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

from alembic import command
from alembic.config import Config
from jsonschema import Draft202012Validator, FormatChecker
import pytest
import sqlalchemy as sa
import yaml

from infra.policies.real_account_dependency import allowed_distribution_modes, load_dependency, milestone_state


ROOT = Path(__file__).resolve().parents[2]


def test_account_dependency_is_explicit_and_fallback_matches_release_levels() -> None:
    policy = load_dependency()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/real-account-dependency.schema.json").read_text(encoding="utf-8"))
    union = json.loads((ROOT / "packages/contracts/jsonschema/governance.schema.json").read_text(encoding="utf-8"))
    release = yaml.safe_load((ROOT / "docs/governance/release-levels-v1.yaml").read_text(encoding="utf-8"))
    raci = yaml.safe_load((ROOT / "docs/governance/raci-v1.yaml").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    assert {item["$ref"] for item in union["oneOf"]} >= {"./real-account-dependency.schema.json"}
    assert policy["status"] == "unavailable"
    assert policy["owner"]["responsible_role"] == "platform_operator"
    assert policy["owner"]["accountable_role"] == "governance_owner"
    roles = {role["role_key"] for role in raci["roles"]}
    assert set(policy["owner"]["consulted_roles"] + [policy["owner"]["responsible_role"], policy["owner"]["accountable_role"]]) <= roles
    mvp = next(level for level in release["levels"] if level["level_key"] == "architecture_mvp")
    assert set(allowed_distribution_modes()) == set(mvp["allowed_distribution_modes"])
    assert not set(policy["unavailable_fallback"]["blocked_modes"]) & set(allowed_distribution_modes())


def test_deadline_escalates_without_unblocking_real_platform() -> None:
    policy = load_dependency()
    due = datetime.fromisoformat(policy["latest_evidence_due_at"])
    assert milestone_state(due - timedelta(days=31)) == "pending_no_go"
    assert milestone_state(due - timedelta(days=30)) == "escalation_window_no_go"
    assert milestone_state(due + timedelta(seconds=1)) == "overdue_escalate_no_go"
    assert allowed_distribution_modes() == ("manual_export", "simulation")
    with pytest.raises(ValueError, match="timezone"):
        milestone_state(datetime(2026, 12, 1))


def test_account_dependency_migration_is_versioned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'gov009.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        assert sa.inspect(connection).has_table("account_dependency_versions")
        insert = sa.text("INSERT INTO account_dependency_versions VALUES ('first-official-platform-account', 1, 'unavailable', :hash, '{}', '2026-09-18T00:00:00+08:00', 'team/governance')")
        connection.execute(insert, {"hash": "c" * 64})
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(insert, {"hash": "c" * 64})
    command.downgrade(config, "20260918_gov_008")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("account_dependency_versions")
