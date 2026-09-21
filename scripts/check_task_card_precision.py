"""Audit whether task cards contain Codex-executable implementation detail.

Default mode reports gaps without failing the current planning baseline. Use
``--strict`` in a phase gate once the cards in scope have been refined.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/task-registry.yaml"
REQUIRED = (
    "## 实现规格",
    "## Given–When–Then",
    "## 验证",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--tier", default="P0")
    parser.add_argument("--task", help="check one exact task ID; useful for an incremental task gate")
    args = parser.parse_args()
    registry_path = (
        ROOT / "docs/task-registry-langgraph-v3.yaml"
        if args.task and args.task.startswith(("GRAPH-", "LC-"))
        else REGISTRY
    )
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    gaps: list[tuple[str, list[str]]] = []
    if args.task:
        scoped = [t for t in registry["tasks"] if t.get("id") == args.task]
        if not scoped:
            print(f"unknown task: {args.task}")
            return 1
    else:
        scoped = [t for t in registry["tasks"] if t.get("tier") == args.tier]
    for task in scoped:
        path = ROOT / task["task_spec_ref"]
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [section for section in REQUIRED if section not in text]
        if missing:
            gaps.append((task["id"], missing))
    print(f"scoped={len(scoped)} precise={len(scoped)-len(gaps)} gaps={len(gaps)}")
    for task_id, missing in gaps:
        print(f"{task_id}: missing {', '.join(missing)}")
    return 1 if args.strict and gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
