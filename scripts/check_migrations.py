"""Lint the Alembic revision graph and enforce expand/contract safety rules."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSIONS_DIR = ROOT / "packages/db/migrations/versions"
FILENAME_RE = re.compile(r"^\d{8}_[a-z0-9]+_[a-z0-9_]+\.py$")
DESTRUCTIVE_CALLS = {"drop_column", "drop_constraint", "drop_table", "rename_column", "rename_table", "truncate"}
DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(?:DROP\s+(?:TABLE|COLUMN|CONSTRAINT)|TRUNCATE\b|ALTER\s+TABLE\s+[^\n;]*\bRENAME\b)\b",
    re.IGNORECASE,
)
EXTERNAL_NETWORK_MODULES = {
    "boto3",
    "httpx",
    "requests",
    "socket",
    "urllib",
}
SECRET_RE = re.compile(
    r"(?i)(?:BEGIN\s+(?:RSA|OPENSSH|EC|DSA)?\s*PRIVATE\s+KEY|aws_secret_access_key|password\s*=|token\s*=)"
)


@dataclass(frozen=True)
class MigrationNode:
    path: Path
    revision: str | None
    down_revision: str | None
    upgrade_node: ast.FunctionDef | ast.AsyncFunctionDef | None
    source: str


def _literal(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            try:
                return ast.literal_eval(node.value) if node.value else None
            except (ValueError, TypeError):
                return None
    return None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def load_migrations(versions_dir: Path = DEFAULT_VERSIONS_DIR) -> tuple[list[MigrationNode], list[str]]:
    nodes: list[MigrationNode] = []
    errors: list[str] = []
    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            errors.append(f"MIGRATION_SYNTAX_INVALID: {path.name}: {exc.msg}")
            continue
        revision = _literal(tree, "revision")
        down_revision = _literal(tree, "down_revision")
        if not isinstance(revision, str) or not revision:
            errors.append(f"MIGRATION_REVISION_INVALID: {path.name}: revision must be a string")
            revision = None
        if down_revision is not None and not isinstance(down_revision, str):
            errors.append(f"MIGRATION_HEAD_INVALID: {path.name}: down_revision must be null or one string")
            down_revision = None
        upgrade_node = _function(tree, "upgrade")
        downgrade_node = _function(tree, "downgrade")
        if upgrade_node is None or downgrade_node is None:
            errors.append(f"MIGRATION_NOT_REVERSIBLE: {path.name}: upgrade and downgrade are required")
        if not FILENAME_RE.fullmatch(path.name):
            errors.append(f"MIGRATION_NAME_INVALID: {path.name}: use YYYYMMDD_<task-id>_<slug>.py")
        if SECRET_RE.search(source):
            errors.append(f"MIGRATION_SECRET_BLOCKED: {path.name}: secret-like literal or assignment found")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules = [node.module.split(".", 1)[0]]
            else:
                imported_modules = []
            for module in imported_modules:
                if module in EXTERNAL_NETWORK_MODULES:
                    errors.append(
                        f"MIGRATION_EXTERNAL_NETWORK_BLOCKED: {path.name}: import {module} is not allowed"
                    )
        if upgrade_node is not None:
            for node in ast.walk(upgrade_node):
                if isinstance(node, ast.Call):
                    function_name = node.func.attr if isinstance(node.func, ast.Attribute) else None
                    if function_name in DESTRUCTIVE_CALLS:
                        errors.append(f"DESTRUCTIVE_MIGRATION_BLOCKED: {path.name}: {function_name} in upgrade()")
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and DESTRUCTIVE_SQL_RE.search(node.value):
                    errors.append(f"DESTRUCTIVE_MIGRATION_BLOCKED: {path.name}: destructive SQL in upgrade()")
        nodes.append(MigrationNode(path, revision, down_revision, upgrade_node, source))
    return nodes, errors


def analyze_migrations(versions_dir: Path = DEFAULT_VERSIONS_DIR) -> dict[str, Any]:
    nodes, errors = load_migrations(versions_dir)
    revisions = {node.revision for node in nodes if node.revision}
    valid_nodes = [node for node in nodes if node.revision]
    if len(revisions) != len(valid_nodes):
        errors.append("MIGRATION_HEAD_INVALID: revision IDs must be unique")
    for node in valid_nodes:
        if node.down_revision and node.down_revision not in revisions:
            errors.append(f"MIGRATION_HEAD_INVALID: {node.path.name}: unknown down_revision {node.down_revision}")
    referenced = {node.down_revision for node in valid_nodes if node.down_revision}
    heads = sorted(revisions - referenced)
    if len(heads) != 1:
        errors.append(f"MIGRATION_HEAD_INVALID: expected exactly one head, found {len(heads)}")
    graph = {node.revision: node.down_revision for node in valid_nodes}
    for start in graph:
        seen: set[str] = set()
        current: str | None = start
        while current is not None:
            if current in seen:
                errors.append(f"MIGRATION_HEAD_INVALID: cycle detected at {current}")
                break
            seen.add(current)
            current = graph.get(current)
    return {
        "versions_dir": str(versions_dir),
        "revision_count": len(nodes),
        "heads": heads,
        "errors": sorted(set(errors)),
        "ok": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--versions-dir", type=Path, default=DEFAULT_VERSIONS_DIR)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = analyze_migrations(args.versions_dir)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"revisions={report['revision_count']} heads={report['heads']} errors={len(report['errors'])}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
    return 1 if args.strict and report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
