"""Validate the LangGraph V3 task registry and cards.

This is intentionally separate from the V2.4 registry checker because V3 is an
orchestration overlay and must not alter the business-task baseline.
"""
from __future__ import annotations

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "task-registry-langgraph-v3.yaml"
REQUIRED = (
    "## 目标",
    "## 输入",
    "## 实现规格",
    "## Given–When–Then 验收场景",
    "## 验证命令",
    "## 交付证据",
)


def main() -> int:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    tasks = registry.get("tasks", [])
    errors: list[str] = []
    ids = [task.get("id") for task in tasks]
    if len(ids) != len(set(ids)):
        errors.append("duplicate task id")
    if registry.get("task_count") != len(tasks):
        errors.append("task_count does not match tasks length")
    known = set(ids)
    for task in tasks:
        task_id = task.get("id", "<missing>")
        if not task_id.startswith(("GRAPH-", "LC-")):
            errors.append(f"{task_id}: invalid V3 prefix")
        for dep in task.get("depends_on", []):
            if dep not in known and not dep.startswith(("GOV-", "FOUND-", "MODEL-", "TOPIC-", "PROV-", "RIGHTS-", "KNOW-", "CANON-", "PROD-", "QA-", "POLICY-", "APPROVAL-", "DIST-", "FEEDBACK-", "ACCOUNT-", "OAUTH-", "PLAT-", "EVAL-")):
                errors.append(f"{task_id}: unknown dependency {dep}")
        card = ROOT / task["task_spec_ref"]
        if not card.exists():
            errors.append(f"{task_id}: missing card {card}")
            continue
        text = card.read_text(encoding="utf-8")
        for section in REQUIRED:
            if section not in text:
                errors.append(f"{task_id}: missing {section}")
    print(f"checked={len(tasks)} errors={len(errors)}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

