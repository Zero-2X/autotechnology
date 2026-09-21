from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/task-job-polling-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/task-queue-config.schema.json"
TASK_SCHEMA = ROOT / "packages/contracts/jsonschema/task-job.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003d_task_jobs.sql"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_polling_baseline_is_postgresql_only_and_schema_aligned() -> None:
    baseline = load_yaml(BASELINE)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    task_schema = json.loads(TASK_SCHEMA.read_text(encoding="utf-8"))
    assert baseline["baseline_key"] == "task-job-polling"
    assert baseline["backend"] == "postgresql"
    assert baseline["configuration"]["redis_required"] is False
    assert baseline["polling"]["ordering"] == ["available_at", "created_at", "id"]
    assert baseline["fixture"]["network_access"] is False
    assert schema["properties"]["backend"]["const"] == "postgresql"
    assert "payload_hash" in task_schema["required"]
    assert task_schema["properties"]["aggregate_version"] == {"type": "integer", "minimum": 1}
    assert task_schema["properties"]["attempt_count"] == {"type": "integer", "minimum": 0}
    assert task_schema["properties"]["max_attempts"] == {"type": "integer", "minimum": 1}


def test_polling_settings_are_deterministic_and_non_secret() -> None:
    from infra.foundation.task_queue import PollingSettings

    settings = PollingSettings.from_env(
        {
            "TASK_QUEUE_NAME": "content-render",
            "TASK_QUEUE_POLL_INTERVAL_SECONDS": "7",
            "TASK_QUEUE_POLL_BATCH_SIZE": "25",
        }
    )
    assert settings.as_contract() == {
        "backend": "postgresql",
        "queue_name": "content-render",
        "poll_interval_seconds": 7,
        "batch_size": 25,
        "eligible_status": "queued",
        "ordering": ["available_at", "created_at", "id"],
        "redis_required": False,
        "credentials_in_repository": False,
        "source": "environment",
    }
    assert settings.config_hash.startswith("sha256:")


def test_polling_settings_use_safe_defaults_and_reject_invalid_values() -> None:
    from infra.foundation.task_queue import PollingSettings, TaskQueueConfigurationError

    assert PollingSettings.from_env({}).as_contract()["queue_name"] == "default"
    assert PollingSettings.from_env({}).poll_interval_seconds == 5
    assert PollingSettings.from_env({}).batch_size == 10
    with pytest.raises(TaskQueueConfigurationError):
        PollingSettings.from_env({"TASK_QUEUE_POLL_INTERVAL_SECONDS": "0"})
    with pytest.raises(TaskQueueConfigurationError):
        PollingSettings.from_env({"TASK_QUEUE_POLL_BATCH_SIZE": "not-an-int"})
    with pytest.raises(TaskQueueConfigurationError):
        PollingSettings.from_env({"TASK_QUEUE_NAME": "with spaces"})


def test_task_jobs_migration_is_idempotent_and_enforces_queue_invariants() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(task_jobs)")}
    assert {
        "id", "org_id", "job_type", "queue_name", "payload_ref", "payload_hash",
        "status", "available_at", "idempotency_key", "trace_id",
    } <= columns
    indexes = {
        row[1]
        for row in connection.execute("PRAGMA index_list(task_jobs)").fetchall()
    }
    assert "idx_task_jobs_poll_ready" in indexes
    row = (
        "job-1", "org-a", "render", "default", "Content", "aggregate-1", 1,
        "private://fixture/tenant/org-a/input", "a" * 64, "queued", 0, 3,
        "2026-09-16T00:00:00+00:00", None, None, None, None, None, None,
        "key-1", "trace-1", "2026-09-16T00:00:00+00:00", "2026-09-16T00:00:00+00:00",
    )
    connection.execute(
        "INSERT INTO task_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        row,
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO task_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
