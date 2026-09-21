from __future__ import annotations

from pathlib import Path
import json

from alembic import command
from alembic.config import Config
from jsonschema import Draft202012Validator, FormatChecker
import pytest
import sqlalchemy as sa

from infra.policies.vendor_inventory import load_inventory, missing_vendor_evidence


ROOT = Path(__file__).resolve().parents[2]


def test_inventory_covers_four_categories_and_records_missing_evidence() -> None:
    inventory = load_inventory()
    schema = json.loads((ROOT / "packages/contracts/jsonschema/vendor-inventory.schema.json").read_text(encoding="utf-8"))
    union = json.loads((ROOT / "packages/contracts/jsonschema/governance.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(inventory)
    assert {item["$ref"] for item in union["oneOf"]} >= {"./vendor-inventory.schema.json"}
    assert {vendor["category"] for vendor in inventory["vendors"]} == {"model", "media", "storage", "data_processing"}
    assert inventory["real_processing_default"] == "deny"
    for vendor in inventory["vendors"]:
        gaps = missing_vendor_evidence(vendor)
        assert "approved_selection" in gaps
        assert "processing_regions" in gaps
        assert "retention_days" in gaps
        assert "contract_ref" in gaps and "dpa_ref" in gaps
        assert "subprocessors_review_ref" in gaps
        assert "exit_plan_ref" in gaps and "deletion_proof_ref" in gaps


def test_evidence_check_is_only_completeness_not_authorization() -> None:
    vendor = dict(load_inventory()["vendors"][0])
    vendor.update(
        selection_status="approved", processing_regions=["CN"], retention_days=30,
        contract_ref="contract-1", dpa_ref="dpa-1", exit_plan_ref="exit-1",
        deletion_proof_ref="deletion-1", owner_approval_ref="approval-1",
        subprocessors={"status": "none_attested", "names": [], "review_ref": "review-1"},
    )
    assert missing_vendor_evidence(vendor) == ()
    vendor["subprocessors"] = {"status": "unknown", "names": [], "review_ref": None}
    assert missing_vendor_evidence(vendor) == ("subprocessors_review_ref",)


def test_inventory_version_table_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'gov010.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        assert sa.inspect(connection).has_table("vendor_inventory_versions")
        insert = sa.text("INSERT INTO vendor_inventory_versions VALUES ('external-data-processors', 1, 'active', :hash, '{}', '2026-09-18T00:00:00+08:00', 'team/governance')")
        connection.execute(insert, {"hash": "d" * 64})
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(insert, {"hash": "d" * 64})
    command.downgrade(config, "20260918_gov_009")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("vendor_inventory_versions")
