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


def test_media_content_qa_contract_and_registry_links() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert set(schema["properties"]["checks"]["properties"]) >= {"numbers", "code", "versions", "ai_label", "rights"}
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-005B")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_005b.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/qa-report.schema.json",
        "packages/contracts/jsonschema/asset-version.schema.json",
    }


def test_postgres_media_content_qa_migration_emits_and_removes_guards() -> None:
    path = ROOT / "packages/db/migrations/versions/20260920_media_005b.py"
    spec = importlib.util.spec_from_file_location("media_content_qa_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE media_qa_content_evaluations" in sql
    assert "CREATE FUNCTION media_qa_005b_evaluation_guard()" in sql
    assert sql.index("DROP TRIGGER IF EXISTS media_qa_content_evaluations_validate ON media_qa_content_evaluations") < sql.index("DROP FUNCTION IF EXISTS media_qa_005b_evaluation_guard()")
