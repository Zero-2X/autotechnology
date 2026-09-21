"""Validate exact Python pins and both frontend lockfile importers."""

from __future__ import annotations

from pathlib import Path
import json
import re
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"
LOCK = ROOT / "requirements.lock"
TOOLS = ROOT / "ci/tooling.lock"


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s#]+)", line)
        if not match:
            raise ValueError(f"{path.relative_to(ROOT)}:{number}: expected exact == pin")
        name, version = match.groups()
        key = _normalise(name)
        if key in pins:
            raise ValueError(f"{path.relative_to(ROOT)}:{number}: duplicate package {name}")
        pins[key] = version
    return pins


def _requirement_names() -> list[str]:
    names: list[str] = []
    for number, raw in enumerate(REQ.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if not match:
            raise ValueError(f"{REQ.relative_to(ROOT)}:{number}: unsupported requirement syntax")
        names.append(_normalise(match.group(1)))
    return names


def check_lockfiles(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        runtime = _pins(root / "requirements.lock")
        tools = _pins(root / "ci/tooling.lock")
        for name in _requirement_names():
            if name not in runtime:
                errors.append(f"requirements.lock missing exact pin for {name}")
        if len(runtime) != len(set(runtime)):
            errors.append("requirements.lock contains duplicate normalized names")
        for path in (root / "apps/web-console", root / "apps/knowledge-site"):
            package = json.loads((path / "package.json").read_text(encoding="utf-8"))
            lock = yaml.safe_load((path / "pnpm-lock.yaml").read_text(encoding="utf-8")) or {}
            if not str(lock.get("lockfileVersion", "")).startswith("9"):
                errors.append(f"{path.relative_to(root)} lockfile is not pnpm v9")
            importer = (lock.get("importers") or {}).get(".")
            if importer is None:
                errors.append(f"{path.relative_to(root)} lockfile has no root importer")
            if package.get("private") is not True:
                errors.append(f"{path.relative_to(root)} must remain private")
        if not tools:
            errors.append("ci/tooling.lock is empty")
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    errors = check_lockfiles()
    for error in errors:
        print(error)
    print(f"lockfile_errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
