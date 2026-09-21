from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sqlite3

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/repo_inventory.py"
REPORT = ROOT / "docs/repo-inventory.md"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_000_repository_inventory.sql"

SPEC = importlib.util.spec_from_file_location("found_000_repo_inventory", SCRIPT)
assert SPEC and SPEC.loader
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def configure_temp_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    output = tmp_path / "docs/repo-inventory.md"
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "OUTPUT", output)
    (tmp_path / "apps/demo").mkdir(parents=True)
    (tmp_path / "deploy").mkdir()
    (tmp_path / "tests/contract").mkdir(parents=True)
    (tmp_path / "apps/demo/main.py").write_text(
        'import os\nAPI_KEY = os.getenv("DEMO_API_KEY")\n', encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (tmp_path / "deploy/start.ps1").write_text("Write-Output demo\n", encoding="utf-8")
    (tmp_path / "tests/contract/test_demo.py").write_text("def test_demo(): assert True\n", encoding="utf-8")
    return output


def test_report_has_required_sections_and_never_reads_sensitive_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = configure_temp_repository(tmp_path, monkeypatch)
    secret_value = "must-not-appear-in-inventory"
    sensitive_path = tmp_path / ".env.production"
    sensitive_path.write_text(f"REAL_TOKEN={secret_value}\n", encoding="utf-8")
    original_hash = inventory.sha256_file

    def guarded_hash(path: Path) -> str:
        assert inventory.sensitive_category(path) is None, f"sensitive file was opened for hashing: {path}"
        return original_hash(path)

    monkeypatch.setattr(inventory, "sha256_file", guarded_hash)
    report = inventory.build_report()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    assert not inventory.validate_report(report)
    assert all(section in report for section in inventory.REQUIRED_SECTIONS)
    assert "DEMO_API_KEY" in report
    assert ".env.production" in report
    assert "environment-file" in report
    assert secret_value not in report
    assert "runtime-implementation-detected" in report


def test_check_fails_when_repository_fingerprint_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_temp_repository(tmp_path, monkeypatch)
    report = inventory.build_report()
    (tmp_path / "apps/demo/main.py").write_text("CHANGED = True\n", encoding="utf-8")
    errors = inventory.validate_report(report)
    assert any("source fingerprint mismatch" in error for error in errors)


def test_inventory_ignores_transient_test_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_temp_repository(tmp_path, monkeypatch)
    transient = tmp_path / ".tmp" / "active-test-artifact"
    transient.parent.mkdir()
    transient.write_text("ephemeral", encoding="utf-8")

    assert transient not in inventory.iter_files()


def test_check_fails_for_missing_section_and_expired_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_temp_repository(tmp_path, monkeypatch)
    report = inventory.build_report(generated_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    report = report.replace("## Deployment scripts", "## Removed section", 1)
    errors = inventory.validate_report(report, now=datetime(2026, 9, 16, tzinfo=timezone.utc))
    assert "missing required section: ## Deployment scripts" in errors
    assert any("inventory is stale" in error for error in errors)


def test_inventory_migration_is_idempotent_and_snapshots_are_immutable() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "FOUND-000", "found-000-v1", f"sha256:{'a' * 64}", "docs/repo-inventory.md",
        "2026-09-16T00:00:00+00:00", "planning-and-contract-baseline", 0, "team/foundation",
    )
    connection.execute("INSERT INTO repository_inventory_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO repository_inventory_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert connection.execute("SELECT COUNT(*) FROM repository_inventory_snapshots").fetchone()[0] == 1


def test_checked_in_inventory_matches_current_repository() -> None:
    assert REPORT.exists()
    assert inventory.validate_report(REPORT.read_text(encoding="utf-8")) == []
