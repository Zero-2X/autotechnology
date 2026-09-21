"""Allowlisted, schema-validated tool execution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str): super().__init__(message); self.code = code


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: int
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    handler: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    timeout_seconds: float = 5.0
    side_effect: bool = False


class ToolRegistry:
    def __init__(self) -> None: self._tools: dict[tuple[str, int], ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        Draft202012Validator.check_schema(dict(spec.input_schema)); Draft202012Validator.check_schema(dict(spec.output_schema))
        if spec.timeout_seconds <= 0 or (spec.name, spec.version) in self._tools: raise ToolError("TOOL_INVALID", "tool version is invalid or already registered")
        self._tools[(spec.name, spec.version)] = spec

    def execute(self, name: str, *, version: int, arguments: Mapping[str, Any], allow_side_effect: bool = False) -> dict[str, Any]:
        spec = self._tools.get((name, version))
        if spec is None: raise ToolError("TOOL_NOT_FOUND", "tool is not registered")
        if spec.side_effect and not allow_side_effect: raise ToolError("TOOL_SIDE_EFFECT_BLOCKED", "side-effect tool is not allowed")
        try: Draft202012Validator(spec.input_schema).validate(arguments)
        except Exception as exc: raise ToolError("TOOL_INPUT_INVALID", "tool arguments violate schema") from exc
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(spec.handler, dict(arguments))
        try:
            result = future.result(timeout=spec.timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise ToolError("TOOL_TIMEOUT", "tool exceeded timeout") from exc
        except Exception as exc:
            raise ToolError("TOOL_FAILED", str(exc)) from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if not isinstance(result, Mapping): raise ToolError("TOOL_OUTPUT_INVALID", "tool output must be an object")
        try: Draft202012Validator(spec.output_schema).validate(result)
        except Exception as exc: raise ToolError("TOOL_OUTPUT_INVALID", "tool output violates schema") from exc
        return dict(result)


__all__ = ["ToolError", "ToolRegistry", "ToolSpec"]
