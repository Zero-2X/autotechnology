"""Validate FOUND-012A's CI workflow and its no-production-secret boundary."""

from __future__ import annotations

from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_lockfiles import check_lockfiles


WORKFLOW = ROOT / ".github/workflows/ci.yml"
REQUIRED_FRAGMENTS = (
    "scripts/check_lockfiles.py",
    "scripts/check_plan_consistency.py --strict-contracts",
    "ruff format --check",
    "ruff check",
    "mypy",
    "pytest",
    "bandit",
    "pip-audit",
    "gitleaks/gitleaks-action@v3",
    "scripts/check_supply_chain.py",
)


def check_ci_configuration(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    workflow_path = root / ".github/workflows/ci.yml"
    try:
        raw = workflow_path.read_text(encoding="utf-8")
        document = yaml.load(raw, Loader=yaml.BaseLoader) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [str(exc)]
    permissions = document.get("permissions") or {}
    if permissions.get("contents") != "read":
        errors.append("workflow permissions must set contents: read")
    triggers = document.get("on") or {}
    if not isinstance(triggers, dict) or not {"push", "pull_request"} <= set(triggers):
        errors.append("workflow must run on push and pull_request")
    for fragment in REQUIRED_FRAGMENTS:
        if fragment not in raw:
            errors.append(f"workflow missing required check: {fragment}")
    if "pull_request_target" in raw:
        errors.append("workflow must not use pull_request_target")
    if re.search(r"\bsecrets\.", raw, re.IGNORECASE):
        errors.append("workflow must not read repository secrets")
    if re.search(r"\b(?:prod|production)[_-]?(?:token|password|secret|credential)\b", raw, re.IGNORECASE):
        errors.append("workflow contains a production credential reference")
    errors.extend(check_lockfiles(root))
    return sorted(set(errors))


def main() -> int:
    errors = check_ci_configuration()
    for error in errors:
        print(error)
    print(f"ci_configuration_errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
