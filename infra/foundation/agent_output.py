"""Offline, version-pinned structured output validation; no tools or side effects."""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry


class AgentOutputError(ValueError):
    """Deterministic contract failure; callers must not automatically retry."""


class AgentOutputRegistry:
    def __init__(self) -> None:
        self._validators = {}
        self._migrations = {}

    def register(self, ref: str, version: int, schema: dict) -> None:
        if not isinstance(ref, str) or not ref or type(version) is not int or version < 1:
            raise AgentOutputError("invalid schema identity")
        if (ref, version) in self._validators:
            raise AgentOutputError("schema version is immutable")
        Draft202012Validator.check_schema(schema)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise AgentOutputError("Draft 2020-12 is required")
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise AgentOutputError("output schema must be a closed object")
        version_schema = schema.get("properties", {}).get("schema_version", {})
        if ("schema_version" not in schema.get("required", [])
                or version_schema.get("type") != "integer"
                or type(version_schema.get("const")) is not int
                or version_schema["const"] != version):
            raise AgentOutputError("schema_version must be required and pinned to registration")
        self._validators[ref, version] = Draft202012Validator(
            deepcopy(schema), format_checker=FormatChecker(), registry=Registry()
        )

    def validate(self, ref: str, value: dict, version: int) -> dict:
        if type(version) is not int or (ref, version) not in self._validators:
            raise AgentOutputError("unsupported schema version")
        try:
            error = next(self._validators[ref, version].iter_errors(value), None)
        except Exception as exc:
            raise AgentOutputError("schema reference cannot be resolved offline") from exc
        if error is not None:
            # Do not expose model payloads in logs or error messages.
            raise AgentOutputError(f"agent output violates {error.validator}")
        return deepcopy(value)

    def register_migration(self, ref: str, source: int, target: int, fn: Callable) -> None:
        if type(source) is not int or type(target) is not int or target != source + 1:
            raise AgentOutputError("migration must advance exactly one version")
        if (ref, source) not in self._validators or (ref, target) not in self._validators:
            raise AgentOutputError("register both schemas before migration")
        if (ref, source, target) in self._migrations or not callable(fn):
            raise AgentOutputError("invalid or duplicate migration")
        self._migrations[ref, source, target] = fn

    def migrate(self, ref: str, value: dict, source: int, target: int) -> dict:
        current = self.validate(ref, value, source)
        if type(target) is not int or target < source:
            raise AgentOutputError("schema downgrade is forbidden")
        steps = []
        for version in range(source, target):
            fn = self._migrations.get((ref, version, version + 1))
            if fn is None:
                raise AgentOutputError("missing migration")
            steps.append((version + 1, fn))
        for version, fn in steps:
            try:
                migrated = fn(current)
            except Exception as exc:
                raise AgentOutputError("migration failed") from exc
            current = self.validate(ref, migrated, version)
        return current
