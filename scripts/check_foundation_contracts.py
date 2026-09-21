"""Local/CI contract gate. Fail fast; never regenerate baselines to pass a gate."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    ("scripts/repo_inventory.py", "--check"),
    ("scripts/check_json_schemas.py",),
    ("scripts/check_task_card_registry_refs.py",),
    ("scripts/check_task_card_precision.py", "--task", "FOUND-007D", "--strict"),
    ("scripts/check_plan_consistency.py", "--strict-contracts"),
    ("scripts/check_migrations.py", "--strict", "--json"),
    ("scripts/check_lockfiles.py",),
    ("scripts/check_ci_configuration.py",),
    ("scripts/check_secrets.py",),
    ("scripts/check_architecture.py",),
    ("scripts/smoke_foundation.py",),
    ("scripts/check_openapi_compatibility.py", "--strict"),
    ("scripts/check_event_compatibility.py", "--strict"),
    ("-m", "pytest", "tests", "--maxfail=1", "-q", "-rs"),
)


def main() -> int:
    for tool in ("node", "pnpm"):
        if not shutil.which(tool):
            print(f"Missing {tool}; install frontend build prerequisites before the full gate.")
            return 1
    for args in CHECKS:
        print("Running: " + " ".join(args), flush=True)
        result = subprocess.run([sys.executable, *args], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
