"""Bounded structured-output parser with one deterministic repair attempt."""

from __future__ import annotations

import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator, ValidationError


class ParseError(ValueError):
    def __init__(self, code: str, message: str): super().__init__(message); self.code = code


class StructuredOutputParser:
    def __init__(self, schema: Mapping[str, Any], *, max_repairs: int = 1) -> None:
        Draft202012Validator.check_schema(dict(schema))
        if isinstance(max_repairs, bool) or not isinstance(max_repairs, int) or max_repairs < 0 or max_repairs > 3:
            raise ValueError("max_repairs must be an integer between 0 and 3")
        self.schema, self.max_repairs = dict(schema), max_repairs

    def parse(self, value: Any, *, repair: Any | None = None) -> dict[str, Any]:
        candidate = value
        for attempt in range(self.max_repairs + 1):
            if isinstance(candidate, str):
                try: candidate = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    if attempt < self.max_repairs and repair: candidate = repair(candidate, exc); continue
                    raise ParseError("OUTPUT_NOT_JSON", "model output is not valid JSON") from exc
            try:
                Draft202012Validator(self.schema).validate(candidate)
                if not isinstance(candidate, Mapping): raise ParseError("OUTPUT_NOT_OBJECT", "structured output must be an object")
                return dict(candidate)
            except ValidationError as exc:
                if attempt < self.max_repairs and repair: candidate = repair(candidate, exc); continue
                raise ParseError("OUTPUT_SCHEMA_INVALID", "structured output violates schema") from exc
        raise ParseError("OUTPUT_SCHEMA_INVALID", "structured output could not be repaired")


__all__ = ["ParseError", "StructuredOutputParser"]
