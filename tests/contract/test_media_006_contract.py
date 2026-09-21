from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_asset_version_lineage_contract_and_registry_links() -> None:
    asset = json.loads((ROOT / "packages/contracts/jsonschema/asset-version.schema.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "packages/contracts/jsonschema/media-asset-lineage.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(asset)
    Draft202012Validator.check_schema(schema)
    assert asset["additionalProperties"] is False
    assert set(asset["required"]) == set(asset["properties"])
    assert schema["additionalProperties"] is False
    assert schema["x-source"] == "MEDIA-006"
    assert set(schema["required"]) == set(schema["properties"])
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-006")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_006.py"]
    assert set(task["contract_refs"]) == {
        "packages/contracts/jsonschema/asset-version.schema.json",
        "packages/contracts/jsonschema/media-asset-lineage.schema.json",
    }


def test_postgres_asset_lineage_migration_emits_and_removes_guards() -> None:
    path = ROOT / "packages/db/migrations/versions/20260920_media_006.py"
    spec = importlib.util.spec_from_file_location("media_lineage_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for table in ("media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"):
        assert f"CREATE TABLE {table}" in sql
    for function, trigger, table in (
        ("media_asset_lineage_006_edge_guard", "media_asset_lineage_edges_validate", "media_asset_lineage_edges"),
        ("media_asset_lineage_006_check_guard", "media_asset_lineage_checks_validate", "media_asset_lineage_checks"),
        ("media_asset_lineage_006_command_guard", "media_asset_lineage_commands_validate", "media_asset_lineage_commands"),
        ("media_asset_lineage_006_append_only_guard", "media_asset_lineage_edges_no_mutation", "media_asset_lineage_edges"),
    ):
        assert f"CREATE FUNCTION {function}()" in sql
        assert sql.index(f"DROP TRIGGER IF EXISTS {trigger} ON {table}") < sql.index(f"DROP FUNCTION IF EXISTS {function}()")
