from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _artifact_refs(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if "/" in value and not value.startswith("python ") else []
    if isinstance(value, dict):
        return [ref for item in value.values() for ref in _artifact_refs(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in _artifact_refs(item)]
    return []


def test_every_completed_task_has_parseable_evidence_and_existing_artifacts() -> None:
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    completed = [task for task in registry["tasks"] if task["status"] == "done"]

    for task in completed:
        task_id = task["id"]
        candidates = (
            ROOT / "docs/foundation" / f"{task_id}-EVIDENCE.yaml",
            ROOT / "docs/governance" / f"{task_id}-EVIDENCE.yaml",
        )
        evidence_path = next((path for path in candidates if path.exists()), None)
        assert evidence_path is not None, f"{task_id} has no evidence file"
        evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8"))
        assert evidence["task_id"] == task_id
        assert evidence["status"] == "done"
        for ref in _artifact_refs(evidence.get("artifacts", {})):
            assert (ROOT / ref).exists(), f"{task_id} evidence references missing artifact: {ref}"
