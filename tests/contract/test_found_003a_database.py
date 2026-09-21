from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/postgresql-foundation-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/database-config.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_003a_database_baseline.sql"
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_postgresql_baseline_is_non_secret_and_schema_aligned() -> None:
    baseline = load_yaml(BASELINE)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert baseline["baseline_key"] == "postgresql-foundation"
    assert baseline["engine"] == "postgresql"
    assert baseline["configuration"]["url_env"] == "DATABASE_URL"
    assert baseline["configuration"]["credentials_in_repository"] is False
    assert baseline["health_check"] == {
        "path": "/health/ready",
        "probe_default": "not_attempted",
        "not_configured_status": "not_configured",
    }
    assert baseline["fixture"] == {
        "kind": "synthetic",
        "database_name": "foundation_fixture",
        "network_access": False,
    }
    assert schema["properties"]["engine"]["const"] == "postgresql"


def test_database_settings_are_deterministic_and_redact_passwords() -> None:
    from infra.foundation.database import DatabaseSettings

    settings = DatabaseSettings.from_env(
        {
            "DATABASE_URL": "postgresql://fixture:do-not-log@example.test:5433/workflow?sslmode=require",
            "DATABASE_CONNECT_TIMEOUT_SECONDS": "7",
            "DATABASE_APPLICATION_NAME": "test-run",
        }
    )
    assert settings.configured is True
    assert settings.host == "example.test"
    assert settings.port == 5433
    assert settings.database_name == "workflow"
    assert settings.ssl_mode == "require"
    assert settings.redacted_url == "postgresql://fixture@example.test:5433/workflow?sslmode=require"
    assert "do-not-log" not in json.dumps(settings.as_contract())
    assert settings.config_hash.startswith("sha256:")


def test_database_settings_reject_invalid_urls_and_accept_missing_configuration() -> None:
    from infra.foundation.database import DatabaseConfigurationError, DatabaseSettings

    assert DatabaseSettings.from_env({}).configured is False
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_env({"DATABASE_URL": "mysql://localhost/workflow"})
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_env({"DATABASE_URL": "postgresql://localhost"})
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_env({"DATABASE_CONNECT_TIMEOUT_SECONDS": "0"})


def test_database_health_does_not_probe_real_network_by_default() -> None:
    from infra.foundation.database import DatabaseSettings, database_health

    not_configured = database_health(DatabaseSettings.from_env({}))
    configured = database_health(DatabaseSettings.synthetic_fixture())
    assert not_configured["status"] == "not_configured"
    assert configured["status"] == "configured"
    assert configured["probe"] == "not_attempted"
    assert configured["database_name"] == "foundation_fixture"


def test_api_readiness_uses_configuration_health_without_network_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://fixture:do-not-log@127.0.0.1:5432/foundation_fixture",
    )
    payload = TestClient(app).get("/health/ready").json()
    assert payload["status"] == "configured"
    assert payload["dependencies"]["database_health"]["probe"] == "not_attempted"
    assert "do-not-log" not in json.dumps(payload)
    openapi = load_yaml(OPENAPI)
    assert "FOUND-003A" in openapi["paths"]["/health/ready"]["get"]["x-task-ids"]

    monkeypatch.setenv("DATABASE_URL", "mysql://fixture:do-not-log@127.0.0.1/workflow")
    invalid = TestClient(app).get("/health/ready").json()
    assert invalid["status"] == "invalid_configuration"
    assert invalid["dependencies"]["database_health"]["probe"] == "skipped"
    assert "do-not-log" not in json.dumps(invalid)


def test_synthetic_connection_fixture_is_connection_shaped_without_network_access() -> None:
    from infra.foundation.database import create_connection_fixture

    with create_connection_fixture() as fixture:
        assert fixture.settings.source == "synthetic_fixture"
        assert fixture.settings.host == "127.0.0.1"
        assert fixture.connection.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(sqlite3.ProgrammingError):
        fixture.connection.execute("SELECT 1")


def test_database_baseline_migration_is_idempotent_and_version_locked() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "postgresql-foundation", 1, "active", "postgresql", "127.0.0.1", 5432,
        "foundation_fixture", "prefer", "synthetic", f"sha256:{'b' * 64}",
        "2026-09-16T00:00:00+00:00", "team/foundation",
    )
    connection.execute(
        "INSERT INTO database_connection_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        row,
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO database_connection_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    assert connection.execute("SELECT COUNT(*) FROM database_connection_baselines").fetchone()[0] == 1
