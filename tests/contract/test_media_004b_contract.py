from __future__ import annotations

import importlib.util
import json
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_retry_contracts_are_closed_and_registry_linked() -> None:
    render = json.loads((ROOT / "packages/contracts/jsonschema/render-job.schema.json").read_text(encoding="utf-8"))
    retry = json.loads((ROOT / "packages/contracts/jsonschema/render-retry.schema.json").read_text(encoding="utf-8"))
    failure = json.loads((ROOT / "packages/contracts/jsonschema/task-failure.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(render)
    Draft202012Validator.check_schema(retry)
    Draft202012Validator.check_schema(failure)
    assert "retry_scheduled" in render["properties"]["status"]["enum"]
    assert render["x-extended-by"] == "MEDIA-004B"
    assert retry["additionalProperties"] is False
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-004B")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_004b.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/render-job.schema.json",
        "packages/contracts/jsonschema/task-failure.schema.json",
        "packages/contracts/jsonschema/render-retry.schema.json",
    }


def test_retry_contract_rejects_sensitive_failure_fields() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/render-retry.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert any(error.validator == "additionalProperties" for error in validator.iter_errors({"operation": "retry", "secret": "x"}))


def test_postgres_retry_migration_emits_and_removes_guards() -> None:
    path = ROOT / "packages/db/migrations/versions/20260920_media_004b.py"
    spec = importlib.util.spec_from_file_location("render_retry_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for table in ("media_render_failures", "media_render_retry_schedules", "media_render_retry_commands", "media_render_rerender_targets"):
        assert f"CREATE TABLE {table}" in sql
    for function, trigger, table in (
        ("media_render_004b_failure_guard", "media_render_failures_validate", "media_render_failures"),
        ("media_render_004b_schedule_guard", "media_render_retry_schedules_validate", "media_render_retry_schedules"),
        ("media_render_004b_command_guard", "media_render_retry_commands_validate", "media_render_retry_commands"),
        ("media_render_004b_shot_guard", "media_render_rerender_targets_validate", "media_render_rerender_targets"),
        ("media_render_004b_schedule_identity_guard", "media_render_retry_schedules_identity_guard", "media_render_retry_schedules"),
    ):
        assert f"CREATE FUNCTION {function}()" in sql
        trigger_drop = sql.index(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        function_drop = sql.index(f"DROP FUNCTION IF EXISTS {function}()")
        assert trigger_drop < function_drop
