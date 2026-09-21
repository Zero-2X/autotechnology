"""Validate a supplied observation against its pinned metric definition offline.

The caller must load the definition by immutable ID/version under authorization.
This boundary does not query a database, grant permissions, or persist records.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable


class ObservationContractError(ValueError):
    """A deterministic, non-retryable contract rejection with no payload echo."""


@lru_cache(maxsize=2)
def _validator(name: str) -> Draft202012Validator:
    path = Path(__file__).resolve().parents[2] / "packages/contracts/jsonschema" / f"{name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker(), registry=Registry())


def validate_observation(observation: dict, definition: dict, *, org_id: str) -> dict:
    """Return a detached valid observation; reject mismatched tenant/type/version."""
    try:
        tenant = UUID(org_id)
        # Reject non-JSON numeric values before schema validation (NaN/Infinity).
        json.dumps([observation, definition], allow_nan=False)
        _validator("observation").validate(observation)
        _validator("metric-definition").validate(definition)
    except (ValueError, TypeError, AttributeError, ValidationError):
        raise ObservationContractError("invalid observation or metric definition") from None

    if UUID(observation["org_id"]) != tenant:
        raise ObservationContractError("observation tenant mismatch")
    if definition["org_id"] is not None and UUID(definition["org_id"]) != tenant:
        raise ObservationContractError("metric definition tenant mismatch")
    if (UUID(observation["metric_definition_id"]) != UUID(definition["id"])
            or observation["metric_definition_version_no"] != definition["version_no"]
            or observation["metric_type"] != definition["metric_type"]
            or observation["metric_name"] != definition["key"]):
        raise ObservationContractError("metric definition identity, version or type mismatch")

    value_schema = definition["quality_rules"].get("value_schema")
    if value_schema is not None:
        try:
            Draft202012Validator.check_schema(value_schema)
            dialect = value_schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
            if dialect != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError("unsupported value schema dialect")
            if definition["metric_type"] == "enum":
                values = value_schema.get("enum")
                if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
                    raise ValueError("enum values must be explicit strings")
            if definition["metric_type"] == "json" and not any(
                key in value_schema for key in ("type", "enum", "const", "oneOf", "anyOf", "allOf", "$ref")
            ):
                raise ValueError("JSON value schema must constrain values")
            Draft202012Validator(
                value_schema, format_checker=FormatChecker(), registry=Registry()
            ).validate(observation["metric_value"])
        except (ValueError, TypeError, SchemaError, ValidationError, Unresolvable, RecursionError):
            raise ObservationContractError("metric value schema rejected output") from None
    return deepcopy(observation)
