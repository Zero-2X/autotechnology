"""Verify contract and migration references in task cards match the registry."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def section_refs(text: str, prefix: str) -> list[str]:
    try:
        section = text.split("## 契约与迁移", 1)[1].split("## 目录边界", 1)[0]
    except IndexError:
        return []
    return re.findall(rf"`({re.escape(prefix)}[^`]+)`", section)


def main() -> int:
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    errors: list[str] = []
    for task in registry["tasks"]:
        path = ROOT / task["task_spec_ref"]
        if not path.exists():
            errors.append(f"{task['id']}: missing task card {path}")
            continue
        text = path.read_text(encoding="utf-8")
        card_contracts = section_refs(text, "packages/contracts/")
        card_migrations = section_refs(text, "packages/db/migrations/")
        if sorted(card_contracts) != sorted(task.get("contract_refs", [])):
            errors.append(f"{task['id']}: contract_refs differ")
        if sorted(card_migrations) != sorted(task.get("migration_refs", [])):
            errors.append(f"{task['id']}: migration_refs differ")
    print(f"checked={len(registry['tasks'])} errors={len(errors)}")
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
