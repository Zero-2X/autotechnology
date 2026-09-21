"""Versioned, tenant-scoped AgentDefinition registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import ValidationError, validate


class AgentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AgentDefinition:
    id: UUID
    org_id: UUID
    key: str
    version: int
    input_schema_ref: str
    output_schema_ref: str
    tool_allowlist: tuple[str, ...]
    permissions: tuple[str, ...]
    cost_limit_cents: int
    timeout_ms: int
    human_escalation_conditions: tuple[str, ...]
    status: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "key": self.key,
            "version": self.version,
            "input_schema_ref": self.input_schema_ref,
            "output_schema_ref": self.output_schema_ref,
            "tool_allowlist": list(self.tool_allowlist),
            "permissions": list(self.permissions),
            "cost_limit_cents": self.cost_limit_cents,
            "timeout_ms": self.timeout_ms,
            "human_escalation_conditions": list(self.human_escalation_conditions),
            "status": self.status,
        }


class AgentRegistry:
    def __init__(self, schemas: Mapping[str, dict[str, Any]] | None = None) -> None:
        self.schemas = dict(schemas or {})
        self.definitions: dict[tuple[UUID, str, int], AgentDefinition] = {}

    def register(
        self,
        *,
        org_id: UUID,
        key: str,
        input_schema_ref: str,
        output_schema_ref: str,
        tool_allowlist: list[str],
        permissions: list[str],
        cost_limit_cents: int,
        timeout_ms: int,
        human_escalation_conditions: list[str],
        version: int | None = None,
        status: str = "active",
    ) -> AgentDefinition:
        if not key.strip() or cost_limit_cents < 0 or timeout_ms <= 0:
            raise AgentError("AGENT_DEFINITION_INVALID", "key, cost and timeout are required")
        if input_schema_ref not in self.schemas or output_schema_ref not in self.schemas:
            raise AgentError("AGENT_SCHEMA_NOT_FOUND", "input/output schema reference is unknown")
        next_version = max((item.version for item in self.definitions.values() if item.org_id == org_id and item.key == key), default=0) + 1
        actual_version = version or next_version
        if actual_version != next_version:
            raise AgentError("AGENT_VERSION_CONFLICT", "version must increment from the current definition")
        definition = AgentDefinition(uuid4(), org_id, key, actual_version, input_schema_ref, output_schema_ref, tuple(sorted(set(tool_allowlist))), tuple(sorted(set(permissions))), cost_limit_cents, timeout_ms, tuple(sorted(set(human_escalation_conditions))), status)
        self.definitions[(org_id, key, actual_version)] = definition
        return definition

    def get(self, *, org_id: UUID, key: str, version: int | None = None) -> AgentDefinition:
        candidates = [item for item in self.definitions.values() if item.org_id == org_id and item.key == key]
        if not candidates:
            raise AgentError("AGENT_NOT_FOUND", "agent definition not found")
        if version is None:
            return max(candidates, key=lambda item: item.version)
        definition = self.definitions.get((org_id, key, version))
        if definition is None:
            raise AgentError("AGENT_NOT_FOUND", "agent definition not found")
        return definition

    def validate_input(self, definition: AgentDefinition, payload: Any) -> None:
        try:
            validate(payload, self.schemas[definition.input_schema_ref])
        except ValidationError as exc:
            raise AgentError("AGENT_INPUT_SCHEMA_INVALID", "input failed agent schema") from exc

    def validate_output(self, definition: AgentDefinition, payload: Any) -> None:
        try:
            validate(payload, self.schemas[definition.output_schema_ref])
        except ValidationError as exc:
            raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", "output failed agent schema") from exc
