from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/runtime-entry-baseline-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/runtime-entry.schema.json"
FOUNDATION_SCHEMA = ROOT / "packages/contracts/jsonschema/foundation.schema.json"
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_002_runtime_entry_baseline.sql"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_runtime_baseline_matches_all_five_entries() -> None:
    baseline = load_yaml(BASELINE)
    schema = load_yaml(SCHEMA)
    foundation = load_yaml(FOUNDATION_SCHEMA)
    assert baseline["baseline_key"] == "runtime-entrypoints"
    assert baseline["baseline_version"] == 1
    assert len(baseline["entries"]) == 5
    assert {entry["entry_key"] for entry in baseline["entries"]} == {
        "api", "worker", "scheduler", "web-console", "knowledge-site",
    }
    assert all(entry["external_side_effects"] is False for entry in baseline["entries"])
    assert set(baseline) == set(schema["properties"])
    entry_properties = set(schema["properties"]["entries"]["items"]["properties"])
    assert all(set(entry) == entry_properties for entry in baseline["entries"])
    assert baseline["global_constraints"] == {
        "business_logic_in_entries": False,
        "real_credentials": False,
        "real_platform_calls": False,
        "database_required_for_dry_run": False,
    }
    assert set(schema["required"]) == {"baseline_key", "baseline_version", "status", "entries", "global_constraints"}
    assert "./runtime-entry.schema.json" in {item["$ref"] for item in foundation["oneOf"]}


def test_api_health_routes_are_the_only_routes_and_readiness_is_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = TestClient(app)
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == 200
    assert live.json()["service"] == "api"
    assert live.json()["runtime"] == "modular-monolith"
    assert ready.status_code == 200
    assert ready.json()["status"] == "not_configured"
    assert ready.json()["dependencies"]["business_routes_registered"] is False
    assert set(app.openapi()["paths"]) == {"/health/live", "/health/ready", "/metrics"}
    openapi = load_yaml(OPENAPI)
    assert openapi["paths"]["/health/live"]["get"]["x-task-ids"] == ["FOUND-002", "FOUND-006A"]
    assert "FOUND-002" in openapi["paths"]["/health/ready"]["get"]["x-task-ids"]


def test_worker_and_scheduler_dry_run_commands_are_deterministic() -> None:
    for module, service, field, reason in (
        ("apps.worker", "worker", "leased_jobs", "no_jobs"),
        ("apps.scheduler", "scheduler", "created_jobs", "no_due_jobs"),
    ):
        result = subprocess.run(
            [sys.executable, "-m", module, "--once", "--dry-run"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["service"] == service
        assert payload["dry_run"] is True
        assert payload[field] == 0
        assert reason in payload["reason"]


def test_worker_and_scheduler_reject_non_dry_run_execution() -> None:
    for module in ("apps.worker", "apps.scheduler"):
        result = subprocess.run(
            [sys.executable, "-m", module, "--once"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert "--dry-run is required" in result.stderr


@pytest.mark.parametrize("entry", ["web-console", "knowledge-site"])
def test_frontend_build_writes_only_static_artifacts(tmp_path: Path, entry: str) -> None:
    pnpm = shutil.which("pnpm") or shutil.which("pnpm.cmd")
    if not pnpm:
        pytest.skip("pnpm is required for the static entry build test")
    output = tmp_path / entry
    result = subprocess.run(
        [pnpm, "--dir", f"apps/{entry}", "build", "--", "--out-dir", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    assert "built" in result.stdout
    assert (output / "index.html").exists()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entry"] == entry
    assert manifest["business_runtime"] is False
    assert not (ROOT / f"apps/{entry}/dist").exists()


def test_runtime_entry_migration_is_idempotent_and_version_locked() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "runtime-entrypoints", 1, "active", "[]", "{}", f"sha256:{'a' * 64}",
        "2026-09-16T00:00:00+00:00", "team/foundation",
    )
    connection.execute("INSERT INTO runtime_entry_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO runtime_entry_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert connection.execute("SELECT COUNT(*) FROM runtime_entry_baselines").fetchone()[0] == 1


def test_entrypoints_do_not_import_forbidden_implementation_layers() -> None:
    forbidden = ("sqlalchemy", "langgraph", "langchain", "boto3", "requests")
    for path in (ROOT / "apps/api/main.py", ROOT / "apps/worker/main.py", ROOT / "apps/scheduler/main.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert not any(name in text for name in forbidden), path
