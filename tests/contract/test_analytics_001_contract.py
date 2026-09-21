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
CATEGORIES = {"content", "asset", "publication", "interaction", "geo", "support", "qa", "cost", "risk"}


def test_canonical_event_catalog_and_metric_contract_are_closed_and_registered() -> None:
    metric_schema = json.loads((ROOT / "packages/contracts/jsonschema/metric-definition.schema.json").read_text(encoding="utf-8"))
    catalog_schema = json.loads((ROOT / "packages/contracts/jsonschema/analytics-event-catalog.schema.json").read_text(encoding="utf-8"))
    catalog = yaml.safe_load((ROOT / "docs/contracts/analytics-event-catalog-v1.yaml").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(metric_schema)
    Draft202012Validator.check_schema(catalog_schema)
    Draft202012Validator(catalog_schema).validate(catalog)
    assert metric_schema["additionalProperties"] is False
    assert set(metric_schema["required"]) == set(metric_schema["properties"])
    assert catalog_schema["additionalProperties"] is False
    assert {item["category"] for item in catalog["categories"]} == CATEGORIES
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "ANALYTICS-001")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_analytics_001.py"]
    assert set(task["contract_refs"]) == {
        "packages/contracts/jsonschema/metric-definition.schema.json",
        "packages/contracts/jsonschema/analytics-event-catalog.schema.json",
    }
    assert task["external_dependencies"] == []


def test_all_canonical_analytics_events_have_strict_versioned_schemas() -> None:
    event_registry = yaml.safe_load((ROOT / "docs/contracts/event-registry.yaml").read_text(encoding="utf-8"))
    by_type = {item["event_type"]: item for item in event_registry["events"]}
    for category in CATEGORIES:
        event_type = f"analytics.{category}.observed"
        entry = by_type[event_type]
        assert entry["aggregate_type"] == "Observation"
        assert entry["side_effect_scope"] == "none"
        schema = json.loads((ROOT / entry["schema_ref"]).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        payload = schema["allOf"][1]["properties"]["payload"]
        assert payload["additionalProperties"] is False
        assert payload["properties"]["category"]["const"] == category
        assert payload["required"] == ["aggregate_id", "aggregate_version"]
        assert {"observation_id", "metric_definition_id", "source", "subject_id", "snapshot_hash"} <= set(payload["properties"])


def test_account_free_phase_nine_registry_does_not_claim_real_account_dependency() -> None:
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    tasks = {item["id"]: item for item in registry["tasks"]}
    account_free = {
        "ANALYTICS-001", "ANALYTICS-002", "ANALYTICS-003", "ANALYTICS-004",
        "FEEDBACK-CORE-003", "FEEDBACK-CORE-004", "FEEDBACK-CORE-005",
        "FEEDBACK-EXP-001", "SUP-001", "SUP-002",
    }
    for task_id in account_free:
        assert "EXT-ACCOUNT-001" not in tasks[task_id]["external_dependencies"]
    assert tasks["ACCOUNT-001A"]["external_dependencies"] == ["EXT-ACCOUNT-001"]
    assert tasks["FEEDBACK-LIVE-001"]["external_dependencies"] == ["EXT-ACCOUNT-001"]
    assert tasks["PILOT-001"]["external_dependencies"] == ["EXT-ACCOUNT-001"]


def test_postgres_analytics_migration_emits_and_removes_guards() -> None:
    path = ROOT / "packages/db/migrations/versions/20260920_analytics_001.py"
    spec = importlib.util.spec_from_file_location("analytics_001_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for table in ("metric_definitions", "metric_definition_state_events", "analytics_metric_definition_commands"):
        assert f"CREATE TABLE {table}" in sql
    for function in (
        "analytics_001_definition_guard", "analytics_001_state_guard",
        "analytics_001_command_guard", "analytics_001_append_only_guard",
    ):
        assert f"CREATE FUNCTION {function}()" in sql
        assert f"DROP FUNCTION IF EXISTS {function}()" in sql
    assert sql.index("DROP TRIGGER IF EXISTS metric_definitions_no_mutation ON metric_definitions") < sql.index(
        "DROP FUNCTION IF EXISTS analytics_001_append_only_guard()"
    )
