"""Static module dependency and direct-write gate for FOUND-011."""

from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Mapping
import json

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs/foundation/architecture-guard-v1.yaml"
SCHEMA = ROOT / "packages/contracts/jsonschema/architecture-guard.schema.json"
WRITE = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+([A-Za-z_][A-Za-z_0-9]*)\b", re.IGNORECASE)


def load_policy() -> dict:
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(policy)
    return policy


def _import_error(name: str, owner: str | None, forbidden_roots: set[str]) -> str | None:
    if owner is None:
        return None
    parts = name.split(".")
    if parts[0] in forbidden_roots:
        return f"domain_imports_{parts[0]}"
    if parts[0] == "modules" and len(parts) > 1 and parts[1] != owner:
        return f"cross_module_import:{parts[1]}"
    return None


def check_architecture(root: Path = ROOT, policy: Mapping[str, object] | None = None) -> list[str]:
    rules = dict(policy or load_policy())
    owners = rules["table_owners"]
    forbidden = set(rules["forbidden_domain_import_roots"])
    errors: list[str] = []
    for top in ("modules", "apps"):
        directory = root / top
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            pieces = path.relative_to(root).parts
            owner = pieces[1] if top == "modules" and len(pieces) > 2 else None
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except (SyntaxError, UnicodeError) as exc:
                errors.append(f"{relative}: parse_error:{exc}")
                continue
            for node in ast.walk(tree):
                imports: list[str] = []
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if owner and node.level >= 2:
                        errors.append(f"{relative}:{node.lineno}: cross_module_relative_import")
                    if node.module:
                        imports = [
                            f"modules.{alias.name}" for alias in node.names
                        ] if node.module == "modules" else [node.module]
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "import_module" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    imports = [node.args[0].value]
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__" and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    imports = [node.args[0].value]
                for name in imports:
                    violation = _import_error(name, owner, forbidden)
                    if violation:
                        errors.append(f"{relative}:{node.lineno}: {violation}")
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for match in WRITE.finditer(node.value):
                        table = match.group(1).lower()
                        table_owner = owners.get(table)
                        if top == "apps":
                            errors.append(f"{relative}:{node.lineno}: app_direct_write:{table}")
                        elif owner and table_owner != owner:
                            errors.append(f"{relative}:{node.lineno}: cross_module_write:{table}")
    return sorted(set(errors))


def main() -> int:
    errors = check_architecture()
    for error in errors:
        print(error)
    print(f"architecture_errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
