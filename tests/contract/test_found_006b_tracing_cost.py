from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/tracing-cost-baseline-v1.yaml"
BASELINE_SCHEMA = ROOT / "packages/contracts/jsonschema/tracing-cost-baseline.schema.json"
COST_SCHEMA = ROOT / "packages/contracts/jsonschema/cost-record.schema.json"
FOUNDATION = ROOT / "packages/contracts/jsonschema/foundation.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_006b_tracing_cost.py"
REQUIREMENTS = ROOT / "requirements.txt"


def test_tracing_cost_contracts_and_dependencies_are_registered() -> None:
    baseline = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    baseline_schema = json.loads(BASELINE_SCHEMA.read_text(encoding="utf-8"))
    cost_schema = json.loads(COST_SCHEMA.read_text(encoding="utf-8"))
    foundation = json.loads(FOUNDATION.read_text(encoding="utf-8"))
    refs = {item["$ref"] for item in foundation["oneOf"]}

    assert baseline["tracing"]["propagation"] == "w3c-trace-context"
    assert baseline["tracing"]["remote_export"] is False
    assert baseline["costs"]["persistence"] is False
    assert set(baseline) == set(baseline_schema["properties"])
    assert cost_schema["properties"]["cost_cents"]["minimum"] == 0
    assert {"./tracing-cost-baseline.schema.json", "./cost-record.schema.json"} <= refs
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert "opentelemetry-api>=1.27,<2" in requirements
    assert "opentelemetry-sdk>=1.27,<2" in requirements


def test_found_006b_task_and_migration_are_precise() -> None:
    task = (ROOT / "docs/tasks/FOUND-006B.md").read_text(encoding="utf-8")
    source = MIGRATION.read_text(encoding="utf-8")
    assert "状态：`in_progress`" in task or "状态：`done`" in task
    assert "W3C" in task and "CostRecorder" in task and "InMemoryCostSink" in task
    assert 'revision = "20260916_found_006b"' in source
    assert 'down_revision = "20260916_found_006a"' in source
    assert source.count("pass") == 2


def test_correlation_schema_retains_the_existing_public_fields() -> None:
    schema = json.loads(
        (ROOT / "packages/contracts/jsonschema/correlation-context.schema.json").read_text(encoding="utf-8")
    )
    assert schema["required"] == ["trace_id", "request_id", "org_id", "actor_id"]
    assert schema["additionalProperties"] is False
