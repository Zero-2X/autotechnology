"""Validate V3 task status/evidence synchronization."""

from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/task-registry-langgraph-v3.yaml"
EVIDENCE = ROOT / "docs/foundation/V3-ORCHESTRATION-EVIDENCE.yaml"


def main() -> int:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    evidence = yaml.safe_load(EVIDENCE.read_text(encoding="utf-8"))
    registry_status = {task["id"]: task["status"] for task in registry["tasks"]}
    task_status = evidence.get("task_status", {})
    errors: list[str] = []
    if set(registry_status) != set(task_status):
        errors.append("registry and evidence task sets differ")
    for task_id, status in registry_status.items():
        if task_status.get(task_id) != status:
            errors.append(f"{task_id}: registry={status} evidence={task_status.get(task_id)}")
    grouped: set[str] = set()
    for group_name, group in evidence.get("evidence_groups", {}).items():
        for task_id in group.get("task_ids", []):
            grouped.add(task_id)
            if registry_status.get(task_id) != "done":
                errors.append(f"{group_name}: {task_id} is not done but is in a done evidence group")
        for artifact in group.get("artifacts", []):
            if not (ROOT / artifact).exists():
                errors.append(f"{group_name}: missing artifact {artifact}")
        if not group.get("tests"):
            errors.append(f"{group_name}: no test evidence")
    for task_id, status in registry_status.items():
        if status == "done" and task_id not in grouped:
            errors.append(f"{task_id}: done task has no evidence group")
        if status == "blocked":
            blocked = evidence.get("blocked_tasks", {}).get(task_id, {})
            if not blocked.get("dependency") or not blocked.get("next_action"):
                errors.append(f"{task_id}: blocked task lacks dependency or next_action")
    print(f"checked={len(registry_status)} done={sum(status == 'done' for status in registry_status.values())} "
          f"blocked={sum(status == 'blocked' for status in registry_status.values())} errors={len(errors)}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
