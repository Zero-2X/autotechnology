"""Generate a contract/migration manifest for planning and CI gates."""
from __future__ import annotations

from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs/task-registry.yaml"
OUT = ROOT / "docs/contracts/contract-manifest.yaml"


def exists(ref: str) -> bool:
    return (ROOT / ref.split("#", 1)[0]).exists()


def openapi_task_ids() -> set[str]:
    """Read explicit x-task-ids extensions instead of substring matching."""
    path = ROOT / "packages/contracts/openapi/openapi.yaml"
    if not path.exists():
        return set()
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    result: set[str] = set()
    for operations in (document.get("paths") or {}).values():
        if not isinstance(operations, dict):
            continue
        for operation in operations.values():
            if isinstance(operation, dict):
                result.update(str(task_id) for task_id in operation.get("x-task-ids", []) or [])
    return result


def main() -> None:
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    api_task_ids = openapi_task_ids()
    tasks = []
    for task in registry.get("tasks", []):
        tasks.append(
            {
                "task_id": task["id"],
                "readiness": task.get("readiness", "needs_refinement"),
                "status": task.get("status", "planned"),
                "contract_refs": [
                    {"path": ref, "exists": exists(ref)} for ref in task.get("contract_refs", [])
                ],
                "migration_refs": [
                    {"path": ref, "exists": exists(ref)} for ref in task.get("migration_refs", [])
                ],
                "openapi_task_link": task["id"] if task["id"] in api_task_ids else None,
            }
        )
    object_files = sorted(
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in (ROOT / "packages/contracts/jsonschema").glob("*.schema.json")
    )
    event_files = sorted(
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in (ROOT / "packages/contracts/events").glob("*.schema.json")
    )
    manifest = {
        "schema_version": 1,
        "status": "baseline",
        "source_documents": [
            "AI跨境技术内容自动化工作流开发清单_审计与优化版.md",
            "docs/task-registry.yaml",
        ],
        "machine_sources": {
            "object_jsonschema_dir": "packages/contracts/jsonschema",
            "event_jsonschema_dir": "packages/contracts/events",
            "openapi": "packages/contracts/openapi/openapi.yaml",
            "event_index": "docs/contracts/event-registry.yaml",
            "state_index": "docs/contracts/state-registry.yaml",
            "migration_manifest": "docs/contracts/migration-manifest.yaml",
        },
        "object_schema_files": object_files,
        "event_schema_files": event_files,
        "tasks": tasks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=160), encoding="utf-8")
    print(f"wrote {OUT} ({len(tasks)} tasks, {len(object_files)} object schemas, {len(event_files)} event schemas)")


if __name__ == "__main__":
    main()
