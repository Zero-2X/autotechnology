"""Validate the OpenAPI baseline and report catalog coverage.

The plan intentionally contains a larger command catalog than the first HTTP
baseline.  Normal mode reports the gap; ``--strict`` is used by a phase gate
when all commands for that phase have been implemented.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"
PLAN = ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md"
REGISTRY = ROOT / "docs/task-registry.yaml"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)+$")


def operations(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in METHODS and isinstance(operation, dict):
                result[(method.upper(), path)] = operation
    return result


def catalog_operations() -> set[tuple[str, str]]:
    rows: set[tuple[str, str]] = set()
    for line in PLAN.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in {m.upper() for m in METHODS} and cells[1].startswith("/"):
            rows.add((cells[0], cells[1]))
    return rows


def local_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and not item.startswith("#/"):
                refs.append(item)
            refs.extend(local_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(local_refs(item))
    return refs


def invalid_schema_nodes(value: Any, path: str = "$", *, schema_key: bool = False) -> list[str]:
    """Return paths where a declared OpenAPI schema is null or malformed."""
    errors: list[str] = []
    if schema_key and not isinstance(value, dict):
        errors.append(path)
        return errors
    if isinstance(value, dict):
        for key, item in value.items():
            errors.extend(invalid_schema_nodes(item, f"{path}.{key}", schema_key=key == "schema"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(invalid_schema_nodes(item, f"{path}[{index}]"))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    errors: list[str] = []
    warnings: list[str] = []
    if not OPENAPI.exists():
        errors.append(f"missing OpenAPI file: {OPENAPI}")
        print("errors=1 warnings=0")
        return 1
    try:
        doc = yaml.safe_load(OPENAPI.read_text(encoding="utf-8")) or {}
        registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - bootstrap diagnostic
        errors.append(f"cannot parse contract input: {exc}")
        print("errors=1 warnings=0")
        return 1
    known_ids = {str(task.get("id")) for task in registry.get("tasks", []) if isinstance(task, dict)}
    ops = operations(doc)
    for path in invalid_schema_nodes(doc):
        errors.append(f"invalid or null OpenAPI schema node: {path}")
    for (method, path), operation in ops.items():
        task_ids = operation.get("x-task-ids")
        if not isinstance(task_ids, list) or not task_ids:
            errors.append(f"{method} {path}: x-task-ids is required")
        else:
            for task_id in task_ids:
                if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id) or task_id not in known_ids:
                    errors.append(f"{method} {path}: unknown task id {task_id!r}")
        if not operation.get("operationId"):
            errors.append(f"{method} {path}: operationId is required")
    for ref in local_refs(doc):
        target = (OPENAPI.parent / ref.split("#", 1)[0]).resolve()
        if not target.exists():
            errors.append(f"missing local OpenAPI ref: {ref}")
    catalog = catalog_operations()
    missing = sorted(catalog - set(ops))
    extra = sorted(set(ops) - catalog)
    if missing:
        warnings.append(f"catalog operations not yet in OpenAPI: {len(missing)}")
    if extra:
        warnings.append(f"OpenAPI operations absent from catalog: {len(extra)}")
    if args.strict and missing:
        errors.append("strict coverage requires every catalog operation in OpenAPI")
    print(f"paths={len(doc.get('paths') or {})} operations={len(ops)} linked_tasks={len({x for op in ops.values() for x in (op.get('x-task-ids') or [])})} catalog_operations={len(catalog)} catalog_missing={len(missing)}")
    for message in warnings:
        print(f"WARNING: {message}")
    for message in errors:
        print(f"ERROR: {message}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
