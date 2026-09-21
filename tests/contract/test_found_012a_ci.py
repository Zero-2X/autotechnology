from __future__ import annotations

from pathlib import Path

from scripts.check_ci_configuration import check_ci_configuration
from scripts.check_lockfiles import check_lockfiles
from scripts.check_secrets import scan


ROOT = Path(__file__).resolve().parents[2]


def test_ci_workflow_has_all_required_gates_and_no_secret_access() -> None:
    assert check_ci_configuration() == []
    assert check_lockfiles() == []
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "pull_request_target" not in workflow
    assert "secrets." not in workflow.replace("scripts/check_secrets.py", "")
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow


def test_secret_scanner_rejects_known_secret_shapes(tmp_path: Path) -> None:
    clean = tmp_path / "clean.py"
    clean.write_text("token = uuid4().hex\n", encoding="utf-8")
    assert scan(tmp_path) == []
    leaked = tmp_path / "leaked.py"
    fake_key = "AKIA" + "1234567890ABCDEF"
    leaked.write_text(f"AWS_ACCESS_KEY_ID='{fake_key}'\n", encoding="utf-8")
    findings = scan(tmp_path)
    assert any("aws_access_key" in finding for finding in findings)


def test_secret_scanner_ignores_transient_test_workspace(tmp_path: Path) -> None:
    leaked = tmp_path / ".tmp" / "pytest-of-runner" / "leaked.py"
    leaked.parent.mkdir(parents=True)
    fake_key = "AKIA" + "1234567890ABCDEF"
    leaked.write_text(f"AWS_ACCESS_KEY_ID='{fake_key}'\n", encoding="utf-8")
    assert scan(tmp_path) == []


def test_ci_files_are_present_and_runtime_lock_is_exactly_pinned() -> None:
    assert (ROOT / "requirements.lock").exists()
    assert (ROOT / "ci/tooling.lock").exists()
    assert (ROOT / ".github/workflows/ci.yml").exists()
    assert "jsonschema==4.26.0" in (ROOT / "requirements.lock").read_text(encoding="utf-8")
