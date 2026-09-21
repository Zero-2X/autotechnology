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


def test_observation_contract_stays_closed_and_task_uses_real_migration() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/observation.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["source"]["enum"] == ["site", "fake", "manual", "platform", "geo", "support", "qa"]
    assert schema["properties"]["data_quality"]["enum"] == ["raw", "validated", "estimated"]
    assert schema["properties"]["observation_version"]["minimum"] == 1
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "ANALYTICS-002")
    assert task["contract_refs"] == ["packages/contracts/jsonschema/observation.schema.json"]
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_analytics_002.py"]
    assert task["external_dependencies"] == []


def test_postgres_observation_migration_emits_and_removes_guards() -> None:
    path = ROOT / "packages/db/migrations/versions/20260920_analytics_002.py"
    spec = importlib.util.spec_from_file_location("analytics_002_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for table in ("observations", "analytics_observation_commands"):
        assert f"CREATE TABLE {table}" in sql
    for function in ("analytics_002_observation_guard", "analytics_002_command_guard", "analytics_002_append_only_guard"):
        assert f"CREATE FUNCTION {function}()" in sql
        assert f"DROP FUNCTION IF EXISTS {function}()" in sql
    assert sql.index("DROP TRIGGER IF EXISTS observations_no_mutation ON observations") < sql.index(
        "DROP FUNCTION IF EXISTS analytics_002_append_only_guard()"
    )
