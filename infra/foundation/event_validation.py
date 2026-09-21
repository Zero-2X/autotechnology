"""Immutable event-type/version validators with explicitly supplied offline refs.

Foundation owns schema selection; consumer dispatch, dedupe and business
authorization remain the caller's responsibility. Registration never fetches
references and each version keeps its own copied dependency bundle.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Mapping

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


class EventValidationError(ValueError):
    """Deterministic contract error with no event payload in its message."""


def _schema_children(schema):
    """Walk schema locations, not instance data such as examples/const/default."""
    if not isinstance(schema, dict):
        return
    for key in ("$defs", "definitions", "properties", "patternProperties", "dependentSchemas"):
        yield from schema.get(key, {}).values()
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        yield from schema.get(key, [])
    for key in ("items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems", "contains", "propertyNames", "if", "then", "else", "not", "contentSchema"):
        if key in schema:
            yield schema[key]


class EventSchemaRegistry:
    def __init__(self) -> None:
        self._validators = {}

    def register(self, event_type: str, version: int, schema: dict, *, resources: Mapping[str, dict] | None = None) -> None:
        if not isinstance(event_type, str) or not event_type.strip() or type(version) is not int or version < 1:
            raise EventValidationError("invalid event schema identity")
        if (event_type, version) in self._validators:
            raise EventValidationError("event schema version is immutable")
        try:
            document = deepcopy(schema)
            bundle = deepcopy(dict(resources or {}))
            if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError("wrong draft")
            identity = document["$id"]
            if not isinstance(identity, str) or not identity or identity in bundle:
                raise ValueError("invalid or duplicate schema identity")
            specific = document["allOf"][1]["properties"]
            if specific["event_type"].get("const") != event_type:
                raise ValueError("event type mismatch")
            pinned = specific["event_schema_version"].get("const")
            if type(pinned) is not int or pinned != version:
                raise ValueError("event version mismatch")
            bundle[identity] = document
            registry = Registry()
            for uri, contents in bundle.items():
                Draft202012Validator.check_schema(contents)
                if not isinstance(uri, str) or not uri or contents.get("$schema") != document["$schema"]:
                    raise ValueError("invalid dependency")
                registry = registry.with_resource(uri, Resource.from_contents(contents))
            registry = registry.crawl()

            def check_refs(node, resolver):
                if not isinstance(node, dict):
                    return
                resolver = resolver.in_subresource(Resource.from_contents(node, default_specification=DRAFT202012))
                for keyword in ("$ref", "$dynamicRef"):
                    if keyword in node:
                        resolver.lookup(node[keyword])
                for child in _schema_children(node):
                    check_refs(child, resolver)

            for uri, contents in bundle.items():
                # The root's $id has already been applied by crawl/resolver.
                base = contents.get("$id", uri)
                check_refs({k: v for k, v in contents.items() if k != "$id"}, registry.resolver(base))
            validator = Draft202012Validator(document, registry=registry, format_checker=FormatChecker())
        except Exception:
            raise EventValidationError("invalid event schema or unresolved offline reference") from None
        self._validators[event_type, version] = validator

    def validate(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise EventValidationError("event must be an object")
        event_type, version = event.get("event_type"), event.get("event_schema_version")
        if not isinstance(event_type, str) or type(version) is not int or (event_type, version) not in self._validators:
            raise EventValidationError("unsupported event type or schema version")
        try:
            # Validate a detached JSON value, including rejection of NaN/Infinity.
            value = deepcopy(event)
            json.dumps(value, allow_nan=False)
            error = next(self._validators[event_type, version].iter_errors(value), None)
            if error is not None:
                raise ValueError("invalid event")
        except Exception:
            raise EventValidationError("event violates its registered schema") from None
        return value
