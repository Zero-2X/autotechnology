from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_plan_consistency import check, path_overlap, transitive_dependencies


ROOT = Path(__file__).resolve().parents[2]


def test_committed_registry_passes_strict_dependency_and_path_gate() -> None:
    report = check(
        ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md",
        ROOT / "docs/task-registry.yaml",
        strict_contracts=True,
    )
    assert report["errors"] == []
    assert any("validated 157 registry tasks" in message for message in report["ok"])


def test_cycle_is_rejected_and_path_overlap_is_conservative() -> None:
    tasks = {
        "A-001": {"depends_on": ["B-001"]},
        "B-001": {"depends_on": ["A-001"]},
    }
    with pytest.raises(ValueError, match="dependency cycle"):
        transitive_dependencies(tasks)
    assert path_overlap("modules/foundation", "modules/foundation/worker.py")
    assert path_overlap("deploy/**/secrets", "deploy/environments/prod/secrets")
    assert not path_overlap("modules/governance", "modules/foundation")
