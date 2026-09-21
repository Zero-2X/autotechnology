from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs/foundation/v2-directory-baseline-v1.yaml"
BRANCH_POLICY = ROOT / "docs/governance/branch-protection-baseline-v1.yaml"
BRANCH_SCHEMA = ROOT / "packages/contracts/jsonschema/branch-protection.schema.json"
FOUNDATION_SCHEMA = ROOT / "packages/contracts/jsonschema/foundation.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_001_repository_baseline.sql"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def baseline_paths(baseline: dict) -> list[str]:
    groups = (
        "runtime_entries", "adapter_boundaries", "shared_packages", "test_boundaries",
        "infrastructure_boundaries", "environment_templates", "documentation_boundaries",
    )
    paths = [str(path) for group in groups for path in baseline[group]]
    paths.extend(f"modules/{name}" for name in baseline["logical_modules"])
    return paths


def test_v2_root_files_and_directory_baseline_exist() -> None:
    for path in (ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CODEOWNERS", BASELINE, BRANCH_POLICY):
        assert path.exists(), path
    baseline = load_yaml(BASELINE)
    assert baseline["baseline_key"] == "v2-directory"
    assert baseline["baseline_version"] == 1
    assert baseline["repository_classification"] == "planning-and-contract-baseline"
    assert "FOUND-002" in baseline["runtime_boundary_rule"]
    for relative in baseline_paths(baseline):
        directory = ROOT / relative
        assert directory.is_dir(), relative
        assert (directory / "README.md").exists(), f"missing boundary README: {relative}"


def test_module_readmes_declare_fixed_boundary_sections() -> None:
    baseline = load_yaml(BASELINE)
    required = baseline["module_readme_required_sections"]
    for name in baseline["logical_modules"]:
        module_root = ROOT / "modules" / name
        text = (module_root / "README.md").read_text(encoding="utf-8")
        assert all(section in text for section in required), name
        assert "真实平台" in text
        for layer in ("domain", "application", "ports", "infrastructure", "projections"):
            assert (module_root / layer / ".gitkeep").exists(), f"missing layer: {name}/{layer}"


def test_collaboration_files_and_branch_policy_are_account_free() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    codeowners = (ROOT / "CODEOWNERS").read_text(encoding="utf-8")
    policy = load_yaml(BRANCH_POLICY)
    schema = load_yaml(BRANCH_SCHEMA)
    assert "planning-and-contract-baseline" in readme
    assert "repo_inventory.py --check" in contributing
    assert "adapters/platforms" in contributing
    for path in ("/packages/contracts/", "/packages/db/", "/apps/", "/modules/", "/adapters/"):
        assert path in codeowners
    assert policy["repository_state"] == "not_a_git_worktree"
    assert policy["enforcement_status"] == "documented_not_enforced"
    assert policy["pull_request"]["require_code_owner_reviews"] is True
    assert policy["branch_rules"]["allow_force_pushes"] is False
    assert policy["branch_rules"]["allow_deletions"] is False
    assert set(policy) == set(schema["properties"])
    assert set(policy["pull_request"]) == set(schema["properties"]["pull_request"]["properties"])
    assert set(policy["branch_rules"]) == set(schema["properties"]["branch_rules"]["properties"])
    assert "TOKEN" not in BRANCH_POLICY.read_text(encoding="utf-8").upper()


def test_branch_protection_schema_is_in_foundation_union() -> None:
    schema = load_yaml(BRANCH_SCHEMA)
    foundation = load_yaml(FOUNDATION_SCHEMA)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "baseline_key", "baseline_version", "repository_state", "enforcement_status",
        "provider", "default_branch", "pull_request", "branch_rules", "application_rule",
    }
    refs = {item["$ref"] for item in foundation["oneOf"]}
    assert "./branch-protection.schema.json" in refs


def test_repository_baseline_migration_is_idempotent_and_version_locked() -> None:
    connection = sqlite3.connect(":memory:")
    sql = MIGRATION.read_text(encoding="utf-8")
    connection.executescript(sql)
    connection.executescript(sql)
    row = (
        "repository-branch-protection", 1, "not_a_git_worktree", "documented_not_enforced",
        f"sha256:{'a' * 64}", f"sha256:{'b' * 64}", "2026-09-16T00:00:00+00:00", "team/foundation",
    )
    connection.execute("INSERT INTO repository_branch_protection_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("INSERT INTO repository_branch_protection_baselines VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
    assert connection.execute("SELECT COUNT(*) FROM repository_branch_protection_baselines").fetchone()[0] == 1


def test_foundation_task_does_not_create_forbidden_runtime_boundaries() -> None:
    for forbidden in ("adapters/platforms", "deploy/environments/prod", "secrets"):
        assert not (ROOT / forbidden).exists(), forbidden
