"""Create and verify the safe repository inventory required by FOUND-000.

Sensitive filename hits are handled with filesystem metadata only. Their contents
are never opened for hashing or environment-variable discovery.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "repo-inventory.md"
REPORT_VERSION = "found-000-v1"
MAX_REPORT_AGE = timedelta(hours=24)
SKIP_DIRS = {
    ".git", ".mypy_cache", ".next", ".pytest_cache", ".ruff_cache", ".tmp", ".tox",
    ".local", ".venv", "__pycache__", "build", "dist", "node_modules", "venv",
}
MODULE_ROOTS = ("apps", "modules", "services", "src", "packages", "infra", "adapters")
RUNTIME_ROOTS = {"apps", "modules", "services", "src"}
RUNTIME_SUFFIXES = {".cs", ".go", ".java", ".js", ".jsx", ".kt", ".py", ".rs", ".ts", ".tsx"}
TEXT_SUFFIXES = {
    ".cfg", ".ini", ".js", ".json", ".jsx", ".md", ".ps1", ".py", ".sh",
    ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}
TEXT_FILENAMES = {"dockerfile", "makefile", "procfile"}
DEPENDENCY_FILENAMES = {
    "cargo.lock", "cargo.toml", "composer.json", "composer.lock", "gemfile",
    "gemfile.lock", "go.mod", "go.sum", "package-lock.json", "package.json",
    "pipfile", "pipfile.lock", "pnpm-lock.yaml", "poetry.lock", "pom.xml",
    "pyproject.toml", "uv.lock", "yarn.lock",
}
REQUIRED_SECTIONS = (
    "## Scan metadata",
    "## Git status and branch",
    "## Top-level directories",
    "## Existing applications and modules",
    "## Dependency manifests",
    "## Migrations",
    "## Environment variable names",
    "## Sensitive filename hits",
    "## Deployment scripts",
    "## Test entrypoints",
    "## Uncommitted changes",
    "## Repository classification",
    "## Compatibility strategy",
    "## Do-not-overwrite paths",
    "## Scanned files",
)
ENV_PATTERNS = (
    re.compile(r"os\.getenv\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
    re.compile(r"process\.env\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
    re.compile(r"env::var\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::?[-?][^}]*)?\}"),
)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sensitive_category(path: Path) -> str | None:
    """Classify a credential-like filename without inspecting its contents."""
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return "environment-file"
    if path.suffix.lower() in {".key", ".p12", ".pem", ".pfx"} or name in {"id_ed25519", "id_rsa"}:
        return "private-key-file"
    if any(marker in name for marker in ("credential", "password", "secret", "token")):
        return "credential-name-marker"
    return None


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if path == OUTPUT or path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        files.append(path)
    return sorted(files, key=relative)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_component(path: Path) -> str:
    """Return a deterministic component; sensitive files never reach sha256_file."""
    stat = path.stat()
    category = sensitive_category(path)
    if category:
        return f"sensitive-metadata:{category}:{stat.st_size}:{stat.st_mtime_ns}"
    return f"content:sha256:{sha256_file(path)}:{stat.st_size}"


def run_git(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
        )
    except OSError:
        return None


def git_metadata() -> dict[str, object]:
    probe = run_git("rev-parse", "--is-inside-work-tree")
    if probe is None:
        return {"availability": "git unavailable", "branch": "unavailable", "head": "unavailable", "changes": []}
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return {"availability": "not a git worktree", "branch": "unavailable", "head": "unavailable", "changes": []}
    branch_result = run_git("branch", "--show-current")
    head_result = run_git("rev-parse", "HEAD")
    status_result = run_git("status", "--short", "--untracked-files=all")
    branch = branch_result.stdout.strip() if branch_result and branch_result.returncode == 0 else "unavailable"
    head = head_result.stdout.strip() if head_result and head_result.returncode == 0 else "unavailable"
    changes = status_result.stdout.splitlines() if status_result and status_result.returncode == 0 else []
    return {
        "availability": "git worktree",
        "branch": branch or "detached HEAD",
        "head": head,
        "changes": sorted(line.rstrip() for line in changes if line.strip()),
    }


def source_fingerprint(files: list[Path], _git: dict[str, object]) -> str:
    """Hash repository files while keeping volatile Git metadata informational."""
    digest = hashlib.sha256()
    for path in files:
        digest.update(relative(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(fingerprint_component(path).encode("utf-8"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in TEXT_FILENAMES


def extract_environment_names(files: list[Path]) -> dict[str, list[str]]:
    references: dict[str, set[str]] = defaultdict(set)
    for path in files:
        if sensitive_category(path) or not is_text_candidate(path) or path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in ENV_PATTERNS:
            for name in pattern.findall(content):
                references[name].add(relative(path))
    return {name: sorted(paths) for name, paths in sorted(references.items())}


def dependency_manifests(files: list[Path]) -> list[str]:
    result = []
    for path in files:
        name = path.name.lower()
        rel = relative(path)
        if (
            name in DEPENDENCY_FILENAMES
            or name.startswith("requirements") and name.endswith(".txt")
            or rel == "docs/external-dependencies.yaml"
        ):
            result.append(rel)
    return result


def migration_files(files: list[Path]) -> list[str]:
    return [
        relative(path) for path in files
        if relative(path).startswith("packages/db/migrations/") or path.name.lower() == "alembic.ini"
    ]


def deployment_files(files: list[Path]) -> list[str]:
    result = []
    for path in files:
        rel = relative(path)
        name = path.name.lower()
        parts = rel.split("/")
        if (
            parts[0] == "deploy"
            or rel.startswith(".github/workflows/")
            or name in {"dockerfile", "compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml", "procfile"}
            or parts[0] in {"infra", "scripts"} and any(word in name for word in ("deploy", "release", "start", "bootstrap"))
        ):
            result.append(rel)
    return result


def test_entrypoints(files: list[Path]) -> list[str]:
    result = []
    for path in files:
        rel = relative(path)
        name = path.name.lower()
        if (
            rel.startswith("tests/") and (name.startswith("test_") or name == "conftest.py")
            or rel.startswith("scripts/check_") and path.suffix.lower() == ".py"
            or name in {"pytest.ini", "tox.ini"}
        ):
            result.append(rel)
    return result


def module_inventory(files: list[Path]) -> list[tuple[str, int, int]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        rel_parts = path.relative_to(ROOT).parts
        if not rel_parts or rel_parts[0] not in MODULE_ROOTS:
            continue
        label = "/".join(rel_parts[:2]) if len(rel_parts) > 1 else rel_parts[0]
        groups[label].append(path)
    return [
        (label, len(paths), sum(path.suffix.lower() in RUNTIME_SUFFIXES for path in paths))
        for label, paths in sorted(groups.items())
    ]


def runtime_files(files: list[Path]) -> list[str]:
    return [
        relative(path) for path in files
        if path.relative_to(ROOT).parts[0] in RUNTIME_ROOTS and path.suffix.lower() in RUNTIME_SUFFIXES
    ]


def bullet_lines(items: list[str], empty: str = "None detected.") -> list[str]:
    return [f"- `{item}`" for item in items] if items else [empty]


def build_report(generated_at: datetime | None = None) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    files = iter_files()
    git = git_metadata()
    fingerprint = source_fingerprint(files, git)
    env_names = extract_environment_names(files)
    dependencies = dependency_manifests(files)
    migrations = migration_files(files)
    deployments = deployment_files(files)
    tests = test_entrypoints(files)
    modules = module_inventory(files)
    runtimes = runtime_files(files)
    classification = "runtime-implementation-detected" if runtimes else "planning-and-contract-baseline"
    top_directories = [path for path in ROOT.iterdir() if path.is_dir() and path.name not in SKIP_DIRS and not path.is_symlink()]
    counts = {directory.name: sum(relative(path).startswith(f"{directory.name}/") for path in files) for directory in top_directories}

    lines = [
        "# Repository inventory",
        "",
        "This report contains repository structure and metadata only. Sensitive filename hits are never opened.",
        "",
        "## Scan metadata",
        "",
        f"- Inventory version: `{REPORT_VERSION}`",
        f"- Generated at (UTC): `{generated_at.astimezone(timezone.utc).isoformat(timespec='seconds')}`",
        f"- Source fingerprint: `{fingerprint}`",
        f"- Repository root: `{ROOT.as_posix()}`",
        f"- Scanned files: `{len(files)}`",
        "- Secret contents read: `false`",
        "- Freshness limit: `24 hours`",
        "",
        "## Git status and branch",
        "",
        f"- Availability: `{git['availability']}`",
        f"- Branch: `{git['branch']}`",
        f"- HEAD: `{git['head']}`",
        "",
        "## Top-level directories",
        "",
        "| Directory | Scanned files |",
        "|---|---:|",
    ]
    if top_directories:
        lines.extend(f"| `{path.name}/` | {counts[path.name]} |" for path in sorted(top_directories, key=lambda item: item.name.lower()))
    else:
        lines.append("| _None_ | 0 |")

    lines.extend(["", "## Existing applications and modules", ""])
    if modules:
        lines.extend(["| Path | Files | Runtime source files |", "|---|---:|---:|"])
        lines.extend(f"| `{label}` | {file_count} | {runtime_count} |" for label, file_count, runtime_count in modules)
    else:
        lines.append("None detected under apps, modules, services, src, packages, infra, or adapters.")

    lines.extend(["", "## Dependency manifests", "", *bullet_lines(dependencies)])
    lines.extend(["", "## Migrations", "", *bullet_lines(migrations)])
    lines.extend(["", "## Environment variable names", ""])
    if env_names:
        lines.extend(["| Name | Referenced by |", "|---|---|"])
        for name, paths in env_names.items():
            lines.append(f"| `{name}` | {', '.join(f'`{path}`' for path in paths)} |")
    else:
        lines.append("None detected in non-sensitive text files.")

    lines.extend(["", "## Sensitive filename hits", ""])
    sensitive = [(relative(path), sensitive_category(path), path.stat().st_size) for path in files if sensitive_category(path)]
    if sensitive:
        lines.extend(["| Path | Redacted type | Size |", "|---|---|---:|"])
        lines.extend(f"| `{path}` | `{category}` | {size} |" for path, category, size in sensitive)
    else:
        lines.append("None detected. No sensitive file contents were read.")

    lines.extend(["", "## Deployment scripts", "", *bullet_lines(deployments)])
    lines.extend(["", "## Test entrypoints", "", "Recommended repository gate: `python -m pytest tests --maxfail=1 -q`", ""])
    lines.extend(bullet_lines(tests))
    lines.extend(["", "## Uncommitted changes", ""])
    if git["availability"] != "git worktree":
        lines.append(f"Unavailable: `{git['availability']}`. No clean-worktree claim is made.")
    else:
        lines.extend(bullet_lines(list(git["changes"]), "Clean worktree."))

    lines.extend([
        "",
        "## Repository classification",
        "",
        f"Classification: `{classification}`.",
        "",
    ])
    if runtimes:
        lines.append("Formal runtime source was detected under apps/modules/services/src:")
        lines.extend(bullet_lines(runtimes))
    else:
        lines.append(
            "The repository is not empty: it contains plans, ADRs, governance baselines, machine contracts, "
            "versioned migrations, task cards, checks, and tests. No formal business runtime source was found "
            "under apps/modules/services/src."
        )

    lines.extend([
        "",
        "## Compatibility strategy",
        "",
        "- Continue from the frozen modular-monolith and LangGraph/LangChain boundaries in ADR-001.",
        "- Extend existing contracts and migrations with new versions; do not replace or rewrite accepted baselines.",
        "- Preserve current checks, tests, task IDs, synthetic-only policy, and account-free delivery constraints.",
        "- Treat any later runtime implementation as existing user work and integrate through declared ports and module boundaries.",
        "",
        "## Do-not-overwrite paths",
        "",
        "- `AI跨境技术内容自动化工作流开发清单*.md` — human plan and task ordering.",
        "- `docs/adr/`, `docs/governance/`, `docs/task-registry.yaml`, `docs/tasks/` — accepted decisions and task state.",
        "- `packages/contracts/` — machine-readable contracts; changes require compatible versions and tests.",
        "- `packages/db/migrations/versions/` — append-only versioned migrations; never rewrite accepted revisions.",
        "- `adapters/platforms/`, `deploy/environments/prod/`, `secrets/`, `**/*.pem`, `**/*secret*.json`, `**/*token*.json` — forbidden for FOUND-000.",
        "",
        "## Scanned files",
        "",
        "| Path | Size | Content evidence |",
        "|---|---:|---|",
    ])
    for path in files:
        category = sensitive_category(path)
        evidence = f"redacted:{category}; metadata-only" if category else f"sha256:{sha256_file(path)}"
        lines.append(f"| `{relative(path)}` | {path.stat().st_size} | `{evidence}` |")
    lines.append("")
    return "\n".join(lines)


def report_field(text: str, label: str) -> str | None:
    match = re.search(rf"^- {re.escape(label)}: `([^`]+)`\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def validate_report(text: str, now: datetime | None = None) -> list[str]:
    errors: list[str] = []
    for section in REQUIRED_SECTIONS:
        if section not in text:
            errors.append(f"missing required section: {section}")
    if report_field(text, "Inventory version") != REPORT_VERSION:
        errors.append(f"inventory version must be {REPORT_VERSION}")
    if report_field(text, "Secret contents read") != "false":
        errors.append("report must attest that secret contents were not read")

    generated_value = report_field(text, "Generated at (UTC)")
    if generated_value is None:
        errors.append("missing generated timestamp")
    else:
        try:
            generated_at = datetime.fromisoformat(generated_value)
            if generated_at.tzinfo is None:
                raise ValueError("timestamp has no timezone")
            current = now or datetime.now(timezone.utc)
            age = current.astimezone(timezone.utc) - generated_at.astimezone(timezone.utc)
            if age > MAX_REPORT_AGE:
                errors.append(f"inventory is stale: age {age} exceeds {MAX_REPORT_AGE}")
            if age < timedelta(minutes=-5):
                errors.append("inventory timestamp is more than five minutes in the future")
        except ValueError as exc:
            errors.append(f"invalid generated timestamp: {exc}")

    recorded_fingerprint = report_field(text, "Source fingerprint")
    if not recorded_fingerprint or not re.fullmatch(r"sha256:[0-9a-f]{64}", recorded_fingerprint):
        errors.append("missing or invalid source fingerprint")
    else:
        current_fingerprint = source_fingerprint(iter_files(), git_metadata())
        if recorded_fingerprint != current_fingerprint:
            errors.append(
                f"source fingerprint mismatch: report={recorded_fingerprint} current={current_fingerprint}"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write a fresh inventory report")
    mode.add_argument("--check", action="store_true", help="verify the checked-in report without modifying it")
    args = parser.parse_args()

    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(build_report(), encoding="utf-8", newline="\n")
        print(f"wrote {OUTPUT}")
        return 0

    if not OUTPUT.exists():
        print(f"inventory missing: {OUTPUT}")
        return 1
    errors = validate_report(OUTPUT.read_text(encoding="utf-8"))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"inventory valid: {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
