"""Check the OpenAPI contract against the frozen FOUND-007A baseline.

The checker is intentionally read-only.  It validates the current document,
then compares operation identity, parameters, constraints, and response codes
with the baseline.  Planned catalog gaps remain warnings because this gate is
for compatibility, not for prematurely implementing future business routes.
"""
from __future__ import annotations

import argparse
import copy
import re
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"
BASELINE = ROOT / "docs/foundation/openapi-compatibility-baseline-v1.yaml"
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
OPENAPI_VERSION_RE = re.compile(r"^3\.1\.\d+$")


def operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return operations keyed by the stable ``METHOD /path`` identifier."""

    result: dict[str, dict[str, Any]] = {}
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() in METHODS and isinstance(operation, dict):
                result[f"{method.upper()} {path}"] = operation
    return result


def _json_pointer(document: Any, pointer: str) -> Any:
    value = document
    if pointer in ("", "#"):
        return value
    if pointer.startswith("#/"):
        pointer = pointer[2:]
    elif pointer.startswith("/"):
        pointer = pointer[1:]
    else:
        raise KeyError(pointer)
    for token in pointer.split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        else:
            value = value[token]
    return value


def resolve_ref(ref: str, document: dict[str, Any], source: Path = OPENAPI) -> Any:
    """Resolve an internal or local file reference for contract checks."""

    file_part, _, fragment = ref.partition("#")
    if file_part:
        target = (source.parent / file_part).resolve()
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(ref)
        target_doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    else:
        target = source
        target_doc = document
    return _json_pointer(target_doc, fragment) if fragment else target_doc


def iter_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            yield ref
        for item in value.values():
            yield from iter_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_refs(item)


def dereference(value: Any, document: dict[str, Any]) -> Any:
    if isinstance(value, dict) and isinstance(value.get("$ref"), str):
        return resolve_ref(value["$ref"], document)
    return value


def _constraints(schema: dict[str, Any]) -> dict[str, Any]:
    keys = ("minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "pattern", "enum")
    return {key: copy.deepcopy(schema[key]) for key in keys if key in schema}


def parameter_snapshot(operation: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for raw in operation.get("parameters") or []:
        parameter = dereference(raw, document)
        if not isinstance(parameter, dict):
            continue
        schema = parameter.get("schema")
        if isinstance(schema, dict) and "$ref" in schema:
            schema = dereference(schema, document)
        snapshots.append(
            {
                "name": parameter.get("name"),
                "in": parameter.get("in"),
                "required": bool(parameter.get("required", False)),
                "constraints": _constraints(schema) if isinstance(schema, dict) else {},
            }
        )
    return sorted(snapshots, key=lambda item: (str(item.get("in")), str(item.get("name"))))


def _baseline_parameters(entry: dict[str, Any]) -> list[dict[str, Any]]:
    values = entry.get("parameters") or []
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, dict)]


def _parameter_key(parameter: dict[str, Any]) -> tuple[str, str]:
    return str(parameter.get("in")), str(parameter.get("name"))


def _narrowed(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    old_constraints = old.get("constraints") or {}
    new_constraints = new.get("constraints") or {}
    for key, lower in (("minLength", True), ("maxLength", False)):
        if key in new_constraints and (key not in old_constraints or (
            new_constraints[key] > old_constraints[key] if lower else new_constraints[key] < old_constraints[key]
        )):
            issues.append(f"{key} {'increased' if lower else 'decreased'}")

    def bound(constraints, lower):
        inclusive = "minimum" if lower else "maximum"
        exclusive = "exclusiveMinimum" if lower else "exclusiveMaximum"
        # Equal lower endpoints: exclusive is stricter. Equal upper endpoints:
        # exclusive sorts first, so min selects the stricter endpoint.
        candidates = []
        if inclusive in constraints:
            candidates.append((constraints[inclusive], not lower))
        if exclusive in constraints:
            candidates.append((constraints[exclusive], lower))
        return (max(candidates) if lower else min(candidates)) if candidates else None

    for lower in (True, False):
        before, after = bound(old_constraints, lower), bound(new_constraints, lower)
        if after is not None and (before is None or (after > before if lower else after < before)):
            issues.append("minimum increased" if lower else "maximum decreased")
    if "enum" in new_constraints:
        if "enum" not in old_constraints or any(value not in new_constraints["enum"] for value in old_constraints["enum"]):
            issues.append("enum narrowed")
    if "pattern" in new_constraints and new_constraints["pattern"] != old_constraints.get("pattern"):
        issues.append("pattern changed")
    return issues


def _catalog_warning(document: dict[str, Any]) -> str | None:
    catalog = ROOT / "docs/contracts/api-catalog.yaml"
    if not catalog.exists():
        return None
    try:
        planned = yaml.safe_load(catalog.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    planned_paths: set[tuple[str, str]] = set()
    rows = planned.get("operations") if isinstance(planned, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and str(row.get("status", "")).lower() == "planned":
                method, path = str(row.get("method", "")).upper(), str(row.get("path", ""))
                if method and path:
                    planned_paths.add((method, path))
    if planned_paths:
        current = {(key.split(" ", 1)[0], key.split(" ", 1)[1]) for key in operations(document)}
        missing = planned_paths - current
        if missing:
            return f"planned catalog operations not yet in OpenAPI: {len(missing)}"
    return None


def check_compatibility(document: dict[str, Any], baseline: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return deterministic ``(errors, warnings)`` for two parsed documents."""

    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(document, dict):
        return ["OpenAPI document must be an object"], warnings
    version = document.get("openapi")
    if not isinstance(version, str) or not OPENAPI_VERSION_RE.fullmatch(version):
        errors.append(f"OpenAPI version must be 3.1.x, got {version!r}")

    current = operations(document)
    seen_ids: dict[str, str] = {}
    for key, operation in current.items():
        operation_id = operation.get("operationId")
        if not isinstance(operation_id, str) or not operation_id.strip():
            errors.append(f"{key}: operationId is required")
        elif operation_id in seen_ids:
            errors.append(f"{key}: duplicate operationId {operation_id!r} (also {seen_ids[operation_id]})")
        else:
            seen_ids[operation_id] = key
        if not isinstance(operation.get("x-task-ids"), list) or not operation["x-task-ids"]:
            errors.append(f"{key}: x-task-ids is required")
        if not isinstance(operation.get("x-real-account-required"), bool):
            errors.append(f"{key}: x-real-account-required must be boolean")
        parameters = parameter_snapshot(operation, document)
        by_key = {_parameter_key(item): item for item in parameters}
        if key.split(" ", 1)[1].startswith("/internal/"):
            worker = by_key.get(("header", "X-Worker-Id"))
            if not worker or not worker["required"]:
                errors.append(f"{key}: /internal/* requires required X-Worker-Id header")
        method, path = key.split(" ", 1)
        if method in WRITE_METHODS and not path.startswith("/internal/"):
            idem = by_key.get(("header", "Idempotency-Key"))
            if not idem:
                errors.append(f"{key}: write operation requires Idempotency-Key")
            else:
                constraints = idem.get("constraints") or {}
                if constraints.get("minLength") != 8 or constraints.get("maxLength") != 200:
                    errors.append(f"{key}: Idempotency-Key must retain minLength=8 and maxLength=200")

    for ref in iter_refs(document):
        try:
            resolve_ref(ref, document)
        except (FileNotFoundError, KeyError, IndexError, TypeError, ValueError, yaml.YAMLError) as exc:
            errors.append(f"broken local $ref {ref!r}: {exc}")

    baseline_ops = baseline.get("operations") if isinstance(baseline, dict) else None
    if not isinstance(baseline_ops, dict):
        errors.append("baseline.operations must be an object")
        baseline_ops = {}
    for key, old in baseline_ops.items():
        if key not in current:
            errors.append(f"removed baseline operation: {key}")
            continue
        if not isinstance(old, dict):
            errors.append(f"baseline operation {key} must be an object")
            continue
        operation = current[key]
        if old.get("operation_id") != operation.get("operationId"):
            errors.append(f"{key}: operationId changed from {old.get('operation_id')!r} to {operation.get('operationId')!r}")
        old_responses = {str(code) for code in (old.get("responses") or [])}
        new_responses = {str(code) for code in (operation.get("responses") or {})}
        for code in sorted(old_responses - new_responses):
            errors.append(f"{key}: response code {code} was removed")
        old_params = {_parameter_key(item): item for item in _baseline_parameters(old)}
        new_params = {_parameter_key(item): item for item in parameter_snapshot(operation, document)}
        for parameter_key, previous in old_params.items():
            if parameter_key not in new_params:
                if previous.get("required"):
                    errors.append(f"{key}: required parameter {parameter_key[1]} ({parameter_key[0]}) was removed")
                continue
            current_parameter = new_params[parameter_key]
            if not previous.get("required") and current_parameter.get("required"):
                errors.append(f"{key}: optional parameter {parameter_key[1]} became required")
            for issue in _narrowed(previous, current_parameter):
                errors.append(f"{key}: parameter {parameter_key[1]} ({parameter_key[0]}) {issue}")
        for parameter_key, current_parameter in new_params.items():
            if parameter_key not in old_params and current_parameter.get("required"):
                errors.append(f"{key}: new required parameter {parameter_key[1]} ({parameter_key[0]})")

    baseline_count = baseline.get("operation_count") if isinstance(baseline, dict) else None
    if isinstance(baseline_count, int) and baseline_count != len(baseline_ops):
        errors.append(f"baseline operation_count {baseline_count} does not match operations {len(baseline_ops)}")
    if (warning := _catalog_warning(document)):
        warnings.append(warning)
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="retain the gate's strict validation mode")
    parser.add_argument("--openapi", type=Path, default=OPENAPI)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    try:
        document = yaml.safe_load(args.openapi.read_text(encoding="utf-8")) or {}
        baseline = yaml.safe_load(args.baseline.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print("errors=1 warnings=0")
        print(f"ERROR: cannot parse compatibility inputs: {exc}")
        return 1
    errors, warnings = check_compatibility(document, baseline)
    print(f"operations={len(operations(document))} baseline_operations={len(baseline.get('operations') or {})} errors={len(errors)} warnings={len(warnings)}")
    for message in warnings:
        print(f"WARNING: {message}")
    for message in errors:
        print(f"ERROR: {message}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
