"""Validate the Markdown plan and its machine task registry.

The checker is intentionally dependency-free apart from PyYAML.  It is safe to run
before the implementation repository exists: test commands are required as metadata,
while executable/path checks are opt-in (`--strict-commands`, `--check-test-paths`).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import argparse
import fnmatch
import json
import re
import shutil
import shlex
import sys
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - bootstrap diagnostic
    raise SystemExit("PyYAML is required: python -m pip install pyyaml") from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT = ROOT / "AI跨境技术内容自动化工作流开发清单_审计与优化版.md"
DEFAULT_REGISTRY = ROOT / "docs" / "task-registry.yaml"
DEFAULT_EXTERNAL_DEPENDENCIES = ROOT / "docs" / "external-dependencies.yaml"
DEFAULT_EVENT_REGISTRY = ROOT / "docs" / "contracts" / "event-registry.yaml"
TASK_ID_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)+$")
CHECKBOX_RE = re.compile(r"^\s*-\s*\[[ xX]\]\s*`([^`]+)`\s*(.*)$")
PHASE_RE = re.compile(r"^###\s+阶段\s+(\d+)[：:]?\s*(.*)$")
# Only flag a slash between two complete task IDs.  Ordinary paths
# (``docs/task-registry.yaml``), state pairs (``draft/planned``), and the
# shorthand grouping notation ``FEEDBACK-CORE-001/002`` are not task IDs.
TASK_ID_TOKEN = r"[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)+"
COMPOSITE_RE = re.compile(rf"`{TASK_ID_TOKEN}/{TASK_ID_TOKEN}`")
EVENT_NAME_RE = re.compile(r"^[a-z0-9_.]+$")


def parse_document(path: Path) -> tuple[list[dict[str, Any]], dict[int, str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    phase: int | None = None
    phases: dict[int, str] = {}
    tasks: list[dict[str, Any]] = []
    errors: list[str] = []
    for line_no, line in enumerate(lines, 1):
        heading = PHASE_RE.match(line)
        if heading:
            phase = int(heading.group(1))
            phases[phase] = heading.group(2).strip()
            continue
        match = CHECKBOX_RE.match(line)
        if not match:
            continue
        if phase is None:
            errors.append(f"line {line_no}: checkbox task appears before a phase heading")
        task_id = match.group(1).strip()
        tasks.append({"id": task_id, "title": match.group(2).strip(), "phase": phase, "line": line_no})
        if "/" in task_id:
            errors.append(f"line {line_no}: composite checkbox task ID {task_id!r}; split it into single IDs")
        if not TASK_ID_RE.fullmatch(task_id.replace("/", "-")):
            errors.append(f"line {line_no}: invalid task ID {task_id!r}")
    return tasks, phases, errors


def normalize_path(value: str) -> str:
    value = str(value).replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/") or "."


def path_overlap(left: str, right: str) -> bool:
    """Conservative overlap test for repository path prefixes and simple globs."""
    left, right = normalize_path(left), normalize_path(right)
    if left == right:
        return True
    # fnmatch handles exact files/globs; prefix comparison catches directory scopes.
    if any(ch in left for ch in "*?[") or any(ch in right for ch in "*?["):
        lp = re.split(r"[*?\[]", left, maxsplit=1)[0].rstrip("/")
        rp = re.split(r"[*?\[]", right, maxsplit=1)[0].rstrip("/")
        if lp and rp and (lp == rp or lp.startswith(rp + "/") or rp.startswith(lp + "/")):
            return True
        return fnmatch.fnmatch(left, right) or fnmatch.fnmatch(right, left)
    return left.startswith(right + "/") or right.startswith(left + "/")


def transitive_dependencies(tasks: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    cache: dict[str, set[str]] = {}

    def visit(task_id: str, stack: list[str]) -> set[str]:
        if task_id in cache:
            return cache[task_id]
        if task_id in stack:
            cycle = " -> ".join(stack[stack.index(task_id):] + [task_id])
            raise ValueError(f"dependency cycle: {cycle}")
        result: set[str] = set()
        for dep in tasks[task_id].get("depends_on", []) or []:
            result.add(dep)
            result.update(visit(dep, stack + [task_id]))
        cache[task_id] = result
        return result

    for task_id in tasks:
        visit(task_id, [])
    return cache


def add(report: dict[str, list[str]], level: str, message: str) -> None:
    report[level].append(message)


def parse_event_names(document: Path) -> set[str]:
    """Return event names from the 5.2 text fence."""
    lines = document.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "### 5.2 业务事件")
        fence = next(i for i in range(start, len(lines)) if lines[i].strip() == "```text")
        end = next(i for i in range(fence + 1, len(lines)) if lines[i].strip() == "```")
    except StopIteration:
        return set()
    return {line.strip() for line in lines[fence + 1 : end] if EVENT_NAME_RE.fullmatch(line.strip())}


def parse_state_table_events(document: Path) -> set[str]:
    """Return event names emitted by rows in the 4.5 state table."""
    lines = document.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "### 4.5 关键状态转换表")
        end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("### "))
    except StopIteration:
        return set()
    events: set[str] = set()
    for line in lines[start:end]:
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) >= 6 and EVENT_NAME_RE.fullmatch(cells[5]):
            events.add(cells[5])
    return events


def check(
    document: Path,
    registry_path: Path,
    strict_commands: bool = False,
    check_test_paths: bool = False,
    strict_contracts: bool = False,
) -> dict[str, Any]:
    report: dict[str, list[str]] = {"errors": [], "warnings": [], "ok": []}
    if not document.exists():
        add(report, "errors", f"document not found: {document}")
        return report
    if not registry_path.exists():
        add(report, "errors", f"registry not found: {registry_path}")
        return report
    doc_tasks, phase_names, parse_errors = parse_document(document)
    for message in parse_errors:
        add(report, "errors", message)
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except Exception as exc:
        add(report, "errors", f"cannot parse registry YAML: {exc}")
        return report
    if not isinstance(raw, dict):
        add(report, "errors", "registry root must be a mapping")
        return report
    registry_tasks_raw = raw.get("tasks")
    if not isinstance(registry_tasks_raw, list):
        add(report, "errors", "registry.tasks must be a list")
        return report

    doc_ids = [item["id"] for item in doc_tasks]
    reg_ids = [item.get("id") for item in registry_tasks_raw if isinstance(item, dict)]
    for task_id, count in sorted((task_id, doc_ids.count(task_id)) for task_id in set(doc_ids)):
        if count > 1:
            add(report, "errors", f"document task ID appears {count} times: {task_id}")
    for task_id, count in sorted((task_id, reg_ids.count(task_id)) for task_id in set(reg_ids)):
        if count > 1:
            add(report, "errors", f"registry task ID appears {count} times: {task_id}")
    if set(doc_ids) != set(reg_ids):
        for task_id in sorted(set(doc_ids) - set(reg_ids)):
            add(report, "errors", f"task is in Markdown but missing from registry: {task_id}")
        for task_id in sorted(set(reg_ids) - set(doc_ids)):
            add(report, "errors", f"task is in registry but missing from Markdown: {task_id}")
    if raw.get("task_count") != len(registry_tasks_raw):
        add(report, "errors", f"registry.task_count={raw.get('task_count')!r} but tasks has {len(registry_tasks_raw)} entries")
    if raw.get("schema_version") != 1:
        add(report, "errors", "registry.schema_version must be 1")

    allowed_statuses = set(raw.get("allowed_statuses") or ["planned", "in_progress", "blocked", "done"])
    valid_tiers = {"P0", "P1", "M2", "M3"}
    valid_priorities = {"critical", "high", "normal", "low"}
    tasks: dict[str, dict[str, Any]] = {}
    doc_by_id = {item["id"]: item for item in doc_tasks}
    for item in registry_tasks_raw:
        if not isinstance(item, dict):
            add(report, "errors", "each registry task must be a mapping")
            continue
        task_id = item.get("id")
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            add(report, "errors", f"invalid registry task ID: {task_id!r}")
            continue
        if "/" in task_id:
            add(report, "errors", f"composite registry task ID: {task_id}")
        tasks[task_id] = item
        required = [
            "phase", "depends_on", "allowed_paths", "forbidden_paths", "owned_paths",
            "exclusive_paths", "shared_paths", "test_command", "gate", "owner", "priority",
            "tier", "status", "contract_refs", "migration_refs", "task_spec_ref", "inputs",
            "outputs", "acceptance", "external_dependencies", "source_line",
        ]
        for field in required:
            if field not in item:
                add(report, "errors", f"{task_id}: missing required field {field}")
        if not isinstance(item.get("phase"), int) or item.get("phase") not in phase_names:
            add(report, "errors", f"{task_id}: phase must match a Markdown phase heading")
        if item.get("status") not in allowed_statuses:
            add(report, "errors", f"{task_id}: invalid status {item.get('status')!r}")
        if item.get("tier") not in valid_tiers:
            add(report, "errors", f"{task_id}: invalid tier {item.get('tier')!r}")
        if item.get("priority") not in valid_priorities:
            add(report, "errors", f"{task_id}: invalid priority {item.get('priority')!r}")
        if not isinstance(item.get("owner"), str) or not item.get("owner").strip():
            add(report, "errors", f"{task_id}: owner must be non-empty")
        if not isinstance(item.get("gate"), str) or not item.get("gate").strip():
            add(report, "errors", f"{task_id}: gate must be non-empty")
        if not isinstance(item.get("test_command"), str) or not item.get("test_command").strip():
            add(report, "errors", f"{task_id}: test_command must be non-empty")
        for field in ("depends_on", "allowed_paths", "forbidden_paths", "owned_paths", "exclusive_paths", "shared_paths", "expected_paths", "contract_refs", "migration_refs", "inputs", "outputs", "external_dependencies"):
            if field in item and not isinstance(item[field], list):
                add(report, "errors", f"{task_id}: {field} must be a list")
        if task_id in doc_by_id:
            doc_item = doc_by_id[task_id]
            if item.get("phase") != doc_item.get("phase"):
                add(report, "errors", f"{task_id}: registry phase does not match Markdown")
            if item.get("title") != doc_item.get("title"):
                add(report, "errors", f"{task_id}: registry title does not match Markdown")
            if item.get("source_line") != doc_item.get("line"):
                add(report, "errors", f"{task_id}: registry source_line does not match Markdown")
        if not item.get("contract_refs"):
            add(report, "errors", f"{task_id}: contract_refs cannot be empty")
        if not item.get("migration_refs"):
            add(report, "errors", f"{task_id}: migration_refs cannot be empty")
        if not item.get("task_spec_ref"):
            add(report, "errors", f"{task_id}: task_spec_ref cannot be empty")
        if not isinstance(item.get("acceptance"), dict) or any(not item["acceptance"].get(k) for k in ("given", "when", "then")):
            add(report, "errors", f"{task_id}: acceptance must contain non-empty given/when/then")

    # Dependency existence, wildcards, and cycles.
    tier_rank = {"P0": 0, "P1": 1, "M2": 2, "M3": 3}
    for task_id, item in tasks.items():
        for dep in item.get("depends_on", []) or []:
            if not isinstance(dep, str) or not dep or any(ch in dep for ch in "*/"):
                add(report, "errors", f"{task_id}: dependency must be one exact ID (no wildcard/slash): {dep!r}")
            elif dep not in tasks:
                add(report, "errors", f"{task_id}: dependency does not exist: {dep}")
            elif dep == task_id:
                add(report, "errors", f"{task_id}: task cannot depend on itself")
            elif tier_rank.get(item.get("tier"), 99) < tier_rank.get(tasks[dep].get("tier"), 99):
                add(
                    report,
                    "errors",
                    f"{task_id}: {item.get('tier')} task cannot depend on later tier {tasks[dep].get('tier')} task {dep}",
                )
    try:
        transitive = transitive_dependencies(tasks)
    except (KeyError, ValueError) as exc:
        add(report, "errors", str(exc))
        transitive = {task_id: set() for task_id in tasks}

    # Path declarations and forbidden overlaps.
    for task_id, item in tasks.items():
        allowed = [normalize_path(x) for x in item.get("allowed_paths", []) or []]
        forbidden = [normalize_path(x) for x in item.get("forbidden_paths", []) or []]
        owned = [normalize_path(x) for x in item.get("owned_paths", []) or []]
        exclusive = [normalize_path(x) for x in item.get("exclusive_paths", []) or []]
        for path in owned:
            if not any(path_overlap(path, candidate) for candidate in allowed):
                add(report, "errors", f"{task_id}: owned path is outside allowed_paths: {path}")
        if not allowed:
            add(report, "errors", f"{task_id}: allowed_paths cannot be empty")
        for path in exclusive:
            if not any(path_overlap(path, candidate) for candidate in allowed):
                add(report, "errors", f"{task_id}: exclusive path is outside allowed_paths: {path}")
        for left in allowed:
            for right in forbidden:
                if path_overlap(left, right):
                    add(report, "errors", f"{task_id}: allowed/forbidden path overlap: {left} vs {right}")
        expected = [normalize_path(x) for x in item.get("expected_paths", []) or []]
        for path in expected:
            if not any(path_overlap(path, candidate) for candidate in allowed):
                add(report, "errors", f"{task_id}: expected path is outside allowed_paths: {path}")

    # Same-phase exclusive path conflicts must be ordered by a dependency.
    task_ids = list(tasks)
    for index, left_id in enumerate(task_ids):
        left = tasks[left_id]
        for right_id in task_ids[index + 1 :]:
            right = tasks[right_id]
            if left.get("phase") != right.get("phase"):
                continue
            conflict = any(path_overlap(a, b) for a in left.get("exclusive_paths", []) for b in right.get("exclusive_paths", []))
            if not conflict:
                continue
            ordered = right_id in transitive.get(left_id, set()) or left_id in transitive.get(right_id, set())
            if not ordered:
                add(report, "errors", f"parallel path conflict in phase {left.get('phase')}: {left_id} vs {right_id}")

    # Optional command/path checks are deliberately opt-in until the implementation exists.
    external_ids: set[str] = set()
    if DEFAULT_EXTERNAL_DEPENDENCIES.exists():
        try:
            external_raw = yaml.safe_load(DEFAULT_EXTERNAL_DEPENDENCIES.read_text(encoding="utf-8")) or {}
            external_ids = {str(item.get("id")) for item in (external_raw.get("dependencies") or []) if isinstance(item, dict)}
        except Exception as exc:
            add(report, "errors", f"cannot parse external dependency registry: {exc}")
    for task_id, item in tasks.items():
        for dep in item.get("external_dependencies", []) or []:
            if dep not in external_ids:
                add(report, "errors", f"{task_id}: unknown external dependency {dep}")
        card_ref = item.get("task_spec_ref")
        if isinstance(card_ref, str):
            card_path = ROOT / card_ref
            if not card_path.exists():
                add(report, "errors" if item.get("status") in {"in_progress", "done"} else ("warnings" if strict_contracts else "ok"), f"{task_id}: task card missing: {card_ref}")
        for ref_field in ("contract_refs", "migration_refs"):
            for ref in item.get(ref_field, []) or []:
                ref_path = ROOT / str(ref)
                if not ref_path.exists() and item.get("status") in {"in_progress", "done"}:
                    add(report, "errors", f"{task_id}: {ref_field} path missing for active task: {ref}")
                elif not ref_path.exists() and strict_contracts:
                    add(report, "warnings", f"{task_id}: planned {ref_field} path not created yet: {ref}")

    if DEFAULT_EVENT_REGISTRY.exists():
        try:
            event_raw = yaml.safe_load(DEFAULT_EVENT_REGISTRY.read_text(encoding="utf-8")) or {}
            events = event_raw.get("events") or []
            if not isinstance(events, list):
                add(report, "errors", "event registry events must be a list")
            else:
                seen_event_types: set[str] = set()
                for event in events:
                    if not isinstance(event, dict):
                        add(report, "errors", "each event registry entry must be a mapping")
                        continue
                    event_type = event.get("event_type")
                    schema_ref = event.get("schema_ref")
                    required_event_fields = (
                        "event_type", "producer", "aggregate_type", "event_kind",
                        "side_effect_scope", "ordering_key", "consumer_dedupe_key",
                        "schema_ref", "replay_policy", "state_transitions",
                    )
                    missing_fields = [field for field in required_event_fields if field not in event or event.get(field) is None or event.get(field) == ""]
                    if missing_fields:
                        add(report, "errors", f"{event_type or '<unknown>'}: event registry missing {', '.join(missing_fields)}")
                    if event_type in seen_event_types:
                        add(report, "errors", f"duplicate event registry event_type: {event_type}")
                    if event_type:
                        seen_event_types.add(event_type)
                    if event.get("event_kind") not in {"transition", "append_only", "control"}:
                        add(report, "errors", f"{event_type}: invalid event_kind: {event.get('event_kind')!r}")
                    if event.get("side_effect_scope") not in {"none", "fake", "conditional", "real"}:
                        add(report, "errors", f"{event_type}: invalid side_effect_scope: {event.get('side_effect_scope')!r}")
                    if not isinstance(event.get("state_transitions"), list):
                        add(report, "errors", f"{event_type}: state_transitions must be a list")
                    if isinstance(schema_ref, str):
                        normalized_ref = normalize_path(schema_ref)
                        schema_file = normalized_ref.split("#", 1)[0]
                        if not schema_file.startswith("packages/contracts/events/"):
                            add(report, "errors", f"{event_type}: event schema_ref must be under packages/contracts/events/: {schema_ref}")
                        if not (ROOT / schema_file).exists() and strict_contracts:
                            add(report, "warnings", f"{event_type}: planned event schema path not created yet: {schema_ref}")
                document_events = parse_event_names(document)
                registry_events = {event.get("event_type") for event in events if isinstance(event, dict)}
                for missing in sorted(document_events - registry_events):
                    add(report, "errors", f"event is in Markdown but missing from registry: {missing}")
                for extra in sorted(registry_events - document_events):
                    add(report, "errors", f"event is in registry but missing from Markdown: {extra}")
                state_events = parse_state_table_events(document)
                for missing in sorted(state_events - document_events):
                    add(report, "errors", f"state-table event is not listed in 5.2 event catalog: {missing}")
                for missing in sorted(state_events - registry_events):
                    add(report, "errors", f"state-table event is missing from event registry: {missing}")
        except Exception as exc:
            add(report, "errors", f"cannot parse event registry: {exc}")
    else:
        add(report, "warnings", f"event registry not found yet: {DEFAULT_EVENT_REGISTRY}")

    if strict_commands:
        for task_id, item in tasks.items():
            try:
                argv = shlex.split(item["test_command"], posix=False)
            except ValueError as exc:
                add(report, "errors", f"{task_id}: cannot parse test_command: {exc}")
                continue
            if argv and shutil.which(argv[0]) is None:
                add(report, "errors", f"{task_id}: command executable not found: {argv[0]}")
    if check_test_paths:
        for task_id, item in tasks.items():
            for token in re.findall(r"(?:tests|src|modules|apps)/[A-Za-z0-9_./-]+", item.get("test_command", "")):
                candidate = ROOT / token.rstrip(".,")
                if not candidate.exists():
                    add(report, "warnings", f"{task_id}: referenced test/path does not exist yet: {token}")

    # Composite references outside checkbox lines are warnings by default. They are
    # useful human grouping notation, but must never be copied into depends_on.
    for line_no, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
        for match in COMPOSITE_RE.finditer(line):
            add(report, "warnings", f"line {line_no}: composite reference {match.group(0)} is human-only; do not use it as a task ID")

    if not report["errors"]:
        add(report, "ok", f"validated {len(tasks)} registry tasks against {len(doc_tasks)} Markdown checkbox tasks")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--strict-commands", action="store_true", help="also verify the first executable in each test_command")
    parser.add_argument("--check-test-paths", action="store_true", help="warn when referenced test paths do not exist yet")
    parser.add_argument("--strict-contracts", action="store_true", help="report missing planned contract/migration files")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit JSON instead of human-readable output")
    args = parser.parse_args()
    report = check(args.document, args.registry, args.strict_commands, args.check_test_paths, args.strict_contracts)
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for level in ("errors", "warnings", "ok"):
            for message in report[level]:
                print(f"{level.upper()}: {message}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
