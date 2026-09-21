from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from alembic import command
from alembic.config import Config
from jsonschema import Draft202012Validator, FormatChecker
import pytest
import sqlalchemy as sa

from infra.policies.data_processing import assess_cross_border, assess_deletion, load_policy, retention_deadline


ROOT = Path(__file__).resolve().parents[2]


def test_policy_contract_and_governance_union() -> None:
    policy = load_policy()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/data-processing-policy.schema.json").read_text(encoding="utf-8"))
    union = json.loads((ROOT / "packages/contracts/jsonschema/governance.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    assert {item["$ref"] for item in union["oneOf"]} >= {"./data-processing-policy.schema.json"}
    assert policy["classification"]["audit_evidence"]["default_retention_days"] == 730
    assert policy["cross_border"]["default"] == "deny"
    assert policy["deletion"]["targets"][-2:] == ["backup", "external_recipient"]
    assert policy["retention"]["shorter_legal_or_contractual_limit_wins"] is True
    assert "data_protection_owner" in (ROOT / "docs/governance/raci-v1.yaml").read_text(encoding="utf-8")


def test_retention_is_bounded_and_unknown_class_fails_closed() -> None:
    completed = datetime(2026, 9, 18, tzinfo=timezone.utc)
    assert (retention_deadline("personal_data", completed) - completed).days == 30
    earlier = datetime(2026, 9, 19, tzinfo=timezone.utc)
    assert retention_deadline("personal_data", completed, shorter_limit_at=earlier) == earlier
    with pytest.raises(ValueError, match="unknown data class"):
        retention_deadline("mystery", completed)
    with pytest.raises(ValueError, match="timezone"):
        retention_deadline("personal_data", datetime(2026, 9, 18))


def test_deletion_requires_full_lineage_and_verification() -> None:
    targets = load_policy()["deletion"]["targets"]
    verified = {target: "verified" for target in targets}
    assert assess_deletion(verified).allowed
    assert not assess_deletion({key: value for key, value in verified.items() if key != "backup"}).allowed
    assert assess_deletion({**verified, "external_recipient": "pending"}).reason == "target_unresolved:external_recipient"
    assert assess_deletion({**verified, "backup": "legal_exception:hold-42"}).allowed
    assert not assess_deletion({**verified, "backup": "legal_exception:"}).allowed


def test_cross_border_defaults_to_denial_for_personal_unknown_and_missing_evidence() -> None:
    request = {
        "source_region": "CN", "destination_region": "EU", "recipient_id": "synthetic-recipient",
        "purpose": "test", "data_class": "public_content", "policy_snapshot": "baseline-synthetic-data/v1",
        "transfer_review_ref": "review-1", "rights_review_ref": "rights-1", "synthetic": True,
    }
    assert assess_cross_border(request).allowed
    assert not assess_cross_border({**request, "synthetic": False}).allowed
    assert not assess_cross_border({**request, "data_class": "personal_data"}).allowed
    assert not assess_cross_border({**request, "data_class": "unknown"}).allowed
    assert assess_cross_border({**request, "recipient_id": ""}).reason == "missing_transfer_evidence"
    assert not assess_cross_border({**request, "destination_region": "US"}).allowed
    assert not assess_cross_border({**request, "policy_snapshot": "other/v1"}).allowed


def test_version_table_upgrades_and_downgrades_on_disposable_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'gov007.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        assert sa.inspect(connection).has_table("data_processing_policy_versions")
        row = {"key": "baseline-synthetic-data", "version": 1, "hash": "a" * 64}
        insert = sa.text("INSERT INTO data_processing_policy_versions VALUES (:key, :version, 'active', 'first_party_synthetic', :hash, '{}', '2026-09-18T00:00:00+08:00', 'team/governance')")
        connection.execute(insert, row)
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(insert, row)
    command.downgrade(config, "20260918_found_010")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("data_processing_policy_versions")
