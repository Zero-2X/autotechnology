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

from infra.policies.operational_targets import approval_deadline, assess_budget, assess_recovery, load_targets


ROOT = Path(__file__).resolve().parents[2]


def test_operational_policy_schema_and_existing_risk_sla_agree() -> None:
    targets = load_targets()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/operational-targets.schema.json").read_text(encoding="utf-8"))
    union = json.loads((ROOT / "packages/contracts/jsonschema/governance.schema.json").read_text(encoding="utf-8"))
    risk = yaml.safe_load((ROOT / "docs/governance/risk-policy-v1.yaml").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(targets)
    assert {item["$ref"] for item in union["oneOf"]} >= {"./operational-targets.schema.json"}
    for level in risk["levels"]:
        approved = targets["human_approval"]["risk_levels"][level["risk_level"]]
        assert approved == {
            "first_response_minutes": level["response_sla_minutes"],
            "minimum_quorum": level["minimum_approval_quorum"],
        }
    assert targets["measurement"]["synthetic_results_are_not_production_slo_evidence"] is True
    assert targets["go_no_go"]["missing_or_failed_metric_action"] == "no_go"


def test_budget_guard_denies_unknown_and_projected_overrun() -> None:
    assert assess_budget("0.50", "1.50", "24.50", "299.50").allowed
    assert assess_budget("0.51", "1.50", "24.50", "299.50").reason == "workflow_budget_exceeded"
    assert assess_budget("1.00", "0.00", "24.50", "0.00").reason == "daily_budget_exceeded"
    assert assess_budget("1.00", "0.00", "0.00", "299.50").reason == "monthly_budget_exceeded"
    for unknown in (None, "?", "NaN", -1, True, 0.1):
        assert assess_budget(unknown, "0.00", "0.00", "0.00").reason == "unknown_or_invalid_cost"


def test_approval_deadline_and_recovery_targets() -> None:
    started = datetime(2026, 9, 18, tzinfo=timezone.utc)
    assert approval_deadline("R4", started) == started + timedelta(minutes=15)
    with pytest.raises(ValueError, match="unknown risk"):
        approval_deadline("R5", started)
    with pytest.raises(ValueError, match="timezone"):
        approval_deadline("R1", datetime(2026, 9, 18))
    assert assess_recovery(started, started + timedelta(minutes=240), started - timedelta(minutes=60)).allowed
    assert assess_recovery(started, started + timedelta(minutes=241), started).reason == "rto_exceeded"
    assert assess_recovery(started, started, started - timedelta(minutes=61)).reason == "rpo_exceeded"
    assert assess_recovery(started, started, started + timedelta(minutes=1)).reason == "invalid_recovery_timeline"


def test_version_table_upgrade_and_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'gov008.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        assert sa.inspect(connection).has_table("operational_target_versions")
        row = {"key": "operational-targets", "version": 1, "hash": "b" * 64}
        insert = sa.text("INSERT INTO operational_target_versions VALUES (:key, :version, 'active', 'architecture_mvp', :hash, '{}', '2026-09-18T00:00:00+08:00', 'team/governance')")
        connection.execute(insert, row)
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(insert, row)
    command.downgrade(config, "20260918_gov_007")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("operational_target_versions")
