"""Static-ish Graph State lint used by CI and task acceptance tests."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Mapping

from .state import StateViolation, validate_state


FORBIDDEN_TEXT = ("token", "secret", "password", "authorization", "raw_content", "raw_output", "pii", "binary")


def lint_state(value: Mapping[str, Any], *, max_bytes: int = 64 * 1024) -> dict[str, Any]:
    return validate_state(value, max_bytes=max_bytes)


def lint_source(path: str | Path) -> tuple[str, ...]:
    """Flag literal sensitive state keys in orchestration source."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if any(marker in lowered for marker in FORBIDDEN_TEXT) and "forbidden" not in lowered and "sensitive" not in lowered:
                findings.append(f"{path}:{node.lineno}:{node.value}")
    return tuple(sorted(set(findings)))


__all__ = ["lint_source", "lint_state"]
