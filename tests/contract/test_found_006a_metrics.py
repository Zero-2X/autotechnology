from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/metrics-health-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/metrics-baseline.schema.json"
FOUNDATION = ROOT / "packages/contracts/jsonschema/foundation.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_006a_health_metrics.py"
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"


def test_metrics_baseline_schema_and_openapi_are_registered() -> None:
    baseline = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    foundation = json.loads(FOUNDATION.read_text(encoding="utf-8"))
    openapi = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))

    assert baseline["baseline_key"] == "metrics-health"
    assert baseline["metrics"]["format"] == "prometheus-0.0.4"
    assert baseline["security"] == {
        "tenant_labels": False,
        "correlation_labels": False,
        "payload_labels": False,
        "credential_labels": False,
        "external_export": False,
    }
    assert set(baseline) == set(schema["properties"])
    assert "./metrics-baseline.schema.json" in {item["$ref"] for item in foundation["oneOf"]}
    assert openapi["paths"]["/metrics"]["get"]["x-task-ids"] == ["FOUND-006A"]
    assert "FOUND-006A" in openapi["paths"]["/health/ready"]["get"]["x-task-ids"]


@pytest.mark.parametrize(
    "label",
    ["org_id", "actor_id", "trace_id", "request_id", "subject_id", "token", "payload", "prompt"],
)
def test_metric_definitions_reject_identity_and_sensitive_labels(label: str) -> None:
    from infra.foundation.metrics import MetricDefinition, MetricValidationError

    with pytest.raises(MetricValidationError):
        MetricDefinition("unsafe_total", "unsafe metric", "counter", label_names=(label,))


def test_metric_definitions_reject_invalid_names_buckets_and_conflicts() -> None:
    from infra.foundation.metrics import (
        MetricDefinition,
        MetricDefinitionConflictError,
        MetricRegistry,
        MetricValidationError,
    )

    with pytest.raises(MetricValidationError):
        MetricDefinition("invalid-name", "invalid", "counter")
    with pytest.raises(MetricValidationError):
        MetricDefinition("invalid_histogram", "invalid", "histogram", buckets=(1.0, 0.5))
    with pytest.raises(MetricValidationError):
        MetricDefinition("invalid_histogram", "invalid", "histogram", label_names=("le",), buckets=(1.0,))
    registry = MetricRegistry()
    assert registry.counter("safe_total", "safe counter") is registry.counter("safe_total", "safe counter")
    with pytest.raises(MetricDefinitionConflictError):
        registry.gauge("safe_total", "conflicting gauge")


def test_found_006a_migration_is_reversible_noop_checkpoint() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20260916_found_006a"' in source
    assert 'down_revision = "20260916_found_004f"' in source
    assert "def upgrade()" in source and "def downgrade()" in source
    assert source.count("pass") == 2
