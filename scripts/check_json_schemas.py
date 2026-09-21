"""Read-only offline integrity gate for the checked-in object contracts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]


def check(directory: Path) -> list[str]:
    errors = []
    documents = {}
    resources = {}
    for path in sorted(directory.glob("*.schema.json")):
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError("Draft 2020-12 declaration required")
            identity = schema.get("$id")
            if not isinstance(identity, str) or not identity:
                raise ValueError("missing schema identity")
            if identity in resources:
                raise ValueError("duplicate schema identity")
            resource = Resource.from_contents(schema)
            documents[path.name] = schema
            resources[identity] = resource
        except (ValueError, TypeError, AttributeError) as exc:
            errors.append(f"{path.name}: invalid schema ({type(exc).__name__})")
        except Exception as exc:
            errors.append(f"{path.name}: schema check failed ({type(exc).__name__})")
    registry = Registry().with_resources(resources.items())

    def references(node):
        if isinstance(node, dict):
            if "$ref" in node:
                yield node["$ref"]
            for value in node.values():
                yield from references(value)
        elif isinstance(node, list):
            for value in node:
                yield from references(value)

    for name, schema in documents.items():
        for ref in references(schema):
            try:
                registry.resolver(schema["$id"]).lookup(ref)
            except Exception:
                errors.append(f"{name}: unresolved offline reference {ref}")
        if schema.get("type") == "object":
            log_extension = name == "structured-log.schema.json" and schema.get("x-allow-extra") is True
            if schema.get("additionalProperties") is not False and not log_extension:
                errors.append(f"{name}: top-level object is not closed")
            if not isinstance(schema.get("required"), list):
                errors.append(f"{name}: explicit required list missing")
            for field, rule in schema.get("properties", {}).items():
                if rule == {}:
                    errors.append(f"{name}: unconstrained property {field}")
        elif any(branch.get("$ref") in ("./" + name, name, schema["$id"]) for branch in schema.get("oneOf", []) if isinstance(branch, dict)):
            errors.append(f"{name}: self-referencing module union")
    if not documents:
        errors.append("no object schemas found")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "packages/contracts/jsonschema")
    args = parser.parse_args()
    errors = check(args.directory)
    for error in errors:
        print(error)
    print(f"schema_errors={len(errors)}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
