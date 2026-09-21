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


def test_media_qa_contract_is_closed_and_task_linked() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert schema["x-extended-by"] == "MEDIA-005A"
    assert set(schema["properties"]["checks"]["properties"]) >= {"visual", "audio", "subtitle", "file_hash"}
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-005A")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_005a.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/qa-report.schema.json",
        "packages/contracts/jsonschema/render-job.schema.json",
    }


def test_media_qa_contract_rejects_sensitive_fields() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    report = {
        "id": "00000000-0000-4000-8000-000000000001", "org_id": "00000000-0000-4000-8000-000000000002",
        "subject_type": "media_render_job", "subject_id": "00000000-0000-4000-8000-000000000003",
        "rule_version": "media-005a/v1", "status": "passed", "findings": [],
        "created_at": "2026-09-20T12:00:00Z", "unexpected": "secret",
    }
    assert any(error.validator == "additionalProperties" for error in validator.iter_errors(report))


def test_postgres_media_qa_migration_emits_and_removes_guards_in_order() -> None:
    path = ROOT / "packages/db/migrations/versions/20260920_media_005a.py"
    spec = importlib.util.spec_from_file_location("media_qa_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for table in ("media_qa_reports", "media_qa_findings", "media_qa_commands"):
        assert f"CREATE TABLE {table}" in sql
    for function, trigger, table in (
        ("media_qa_005a_report_guard", "media_qa_reports_validate", "media_qa_reports"),
        ("media_qa_005a_finding_guard", "media_qa_findings_validate", "media_qa_findings"),
        ("media_qa_005a_command_guard", "media_qa_commands_validate", "media_qa_commands"),
        ("media_qa_005a_append_only_guard", "media_qa_reports_no_mutation", "media_qa_reports"),
    ):
        assert f"CREATE FUNCTION {function}()" in sql
        assert sql.index(f"DROP TRIGGER IF EXISTS {trigger} ON {table}") < sql.index(f"DROP FUNCTION IF EXISTS {function}()")
