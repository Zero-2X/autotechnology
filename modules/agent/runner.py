"""AgentRunner that depends only on the ModelPort protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import UUID, uuid4

from jsonschema import ValidationError, validate

from modules.agent.registry import AgentDefinition, AgentError, AgentRegistry


class ModelPort(Protocol):
    def generate(self, request: Any) -> Any: ...


@dataclass(frozen=True)
class AgentRun:
    id: UUID
    org_id: UUID
    agent_definition_id: UUID
    status: str
    input_hash: str
    output_hash: str | None
    created_at: str
    output: Any = None
    error_code: str | None = None

    def as_contract(self) -> dict[str, Any]:
        return {"id": str(self.id), "org_id": str(self.org_id), "agent_definition_id": str(self.agent_definition_id), "status": self.status, "input_hash": self.input_hash, "output_hash": self.output_hash, "created_at": self.created_at}


class AgentRunner:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self.runs: dict[UUID, AgentRun] = {}
        self.events: list[dict[str, Any]] = []

    def run(self, *, org_id: UUID, definition: AgentDefinition, input: Any, model_port: ModelPort, model_request: Any) -> AgentRun:
        if definition.org_id != org_id:
            raise AgentError("TENANT_SCOPE_VIOLATION", "agent definition does not belong to organization")
        self.registry.validate_input(definition, input)
        requested_tools = input.get("tool_calls", []) if isinstance(input, dict) else []
        denied = [tool for tool in requested_tools if tool not in definition.tool_allowlist]
        if denied:
            raise AgentError("AGENT_TOOL_NOT_ALLOWED", "tool is not in the agent allowlist")
        input_hash = sha256(json.dumps(input, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        run_id = uuid4()
        try:
            response = model_port.generate(model_request)
            try:
                validate(response.output, self.registry.schemas[definition.output_schema_ref])
            except ValidationError as exc:
                raise AgentError("AGENT_OUTPUT_SCHEMA_INVALID", "model output failed agent schema") from exc
            output_hash = sha256(json.dumps(response.output, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            needs_review = isinstance(response.output, dict) and (response.output.get("needs_review") is True or response.output.get("confidence", 1) < 0.5)
            status = "needs_review" if needs_review else "succeeded"
            record = AgentRun(run_id, org_id, definition.id, status, input_hash, output_hash, datetime.now(timezone.utc).isoformat(), response.output)
            self.runs[run_id] = record
            self.events.append({"type": "agent.run.completed", "run_id": str(run_id), "org_id": str(org_id), "status": status, "trace_id": model_request.trace_id})
            return record
        except AgentError as exc:
            record = AgentRun(run_id, org_id, definition.id, "failed", input_hash, None, datetime.now(timezone.utc).isoformat(), error_code=exc.code)
            self.runs[run_id] = record
            self.events.append({"type": "agent.run.failed", "run_id": str(run_id), "org_id": str(org_id), "error_code": exc.code})
            raise
        except ValueError as exc:
            error_code = str(getattr(exc, "code", "MODEL_PROVIDER_ERROR"))
            record = AgentRun(run_id, org_id, definition.id, "failed", input_hash, None, datetime.now(timezone.utc).isoformat(), error_code=error_code)
            self.runs[run_id] = record
            self.events.append({"type": "agent.run.failed", "run_id": str(run_id), "org_id": str(org_id), "error_code": error_code})
            raise
