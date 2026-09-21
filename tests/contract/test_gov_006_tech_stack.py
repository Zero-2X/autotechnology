from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/governance/tech-stack-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/tech-stack-baseline.schema.json"
ADR = ROOT / "docs/adr/ADR-001-langchain-langgraph-architecture.md"
MIGRATION = ROOT / "packages/db/migrations/versions/20260915_gov_006_tech_stack_baseline.sql"


def test_tech_stack_baseline_freezes_required_components_and_exclusions() -> None:
    baseline = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    assert set(schema["required"]) <= set(baseline)
    assert baseline["baseline_key"] == "modular-monolith"
    assert baseline["baseline_version"] == 1
    components = {item["component_key"]: item for item in baseline["components"]}
    required = {
        "python_runtime", "api", "worker", "scheduler", "graph_runtime", "langchain_components",
        "database", "orm", "migrations", "object_storage", "tracing", "metrics", "tests",
    }
    assert required <= set(components)
    assert all(components[key]["required"] and components[key]["phase"] == "P0" for key in required)
    assert components["redis"]["required"] is False
    assert components["redis"]["phase"] == "P1"
    assert {"LangGraph Server", "Temporal", "Kafka", "Kubernetes"} <= set(baseline["excluded_initially"])
    assert baseline["upgrade_policy"]["regular_window_days"] == 30
    assert baseline["upgrade_policy"]["security_fix_window_days"] == 7
    datetime.fromisoformat(baseline["effective_at"])


def test_adr_preserves_langgraph_boundaries_and_adds_deployment_baseline() -> None:
    text = ADR.read_text(encoding="utf-8")
    for required in (
        "Modular Monolith", "apps/api", "apps/worker", "apps/scheduler", "PostgreSQL polling",
        "Python 3.12", "FastAPI", "SQLAlchemy 2", "Alembic", "S3", "OpenTelemetry", "pytest",
        "LangGraph Server", "Temporal", "Kafka", "Kubernetes", "GRAPH-GOV-002",
    ):
        assert required in text
    assert "Checkpoint" in text or "checkpoint" in text
    assert "Distribution Adapter" in text
    assert "不得直接写 ORM" in text
    assert "不得要求真实账号或真实平台凭证" in text


def test_tech_stack_migration_is_idempotent_and_versioned() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "modular-monolith", 1, "active", "[]", "[]", "[]", "{}",
        "2026-09-16T00:00:00+08:00", "team/governance",
    )
    connection.execute("INSERT INTO architecture_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO architecture_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert connection.execute("SELECT COUNT(*) FROM architecture_baselines").fetchone()[0] == 1
