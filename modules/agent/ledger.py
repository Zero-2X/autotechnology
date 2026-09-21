"""Append-only, tenant-scoped ledger for redacted AgentRun/ModelCall evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4


class LedgerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PersistedAgentRun:
    id: UUID
    org_id: UUID
    agent_definition_id: UUID
    status: str
    input_hash: str
    output_hash: str | None
    retry_count: int
    reviewer_actor_id: UUID | None
    created_at: str
    error_code: str | None = None


@dataclass(frozen=True)
class PersistedModelCall:
    id: UUID
    org_id: UUID
    model_config_id: str
    prompt_version: str
    request_hash: str
    input_hash: str
    output_hash: str | None
    cost_cents: int | None
    latency_ms: int | None
    status: str
    attempt_no: int
    error_code: str | None
    created_at: str


class AgentRunLedger:
    def __init__(self) -> None:
        self.agent_runs: dict[UUID, PersistedAgentRun] = {}
        self.model_calls: dict[UUID, PersistedModelCall] = {}

    def record_agent_run(self, *, org_id: UUID, agent_definition_id: UUID, status: str, input_payload: Any, output_payload: Any = None, retry_count: int = 0, reviewer_actor_id: UUID | None = None, error_code: str | None = None) -> PersistedAgentRun:
        input_hash = sha256(self._canonical(input_payload).encode()).hexdigest()
        output_hash = sha256(self._canonical(output_payload).encode()).hexdigest() if output_payload is not None else None
        record = PersistedAgentRun(uuid4(), org_id, agent_definition_id, status, input_hash, output_hash, retry_count, reviewer_actor_id, datetime.now(timezone.utc).isoformat(), error_code)
        self.agent_runs[record.id] = record
        return record

    def record_model_call(self, *, org_id: UUID, model_config_id: str, prompt_version: str, request_hash: str, input_payload: Any, output_payload: Any = None, cost_cents: int | None, latency_ms: int | None, status: str, attempt_no: int, error_code: str | None = None) -> PersistedModelCall:
        record = PersistedModelCall(uuid4(), org_id, model_config_id, prompt_version, request_hash, sha256(self._canonical(input_payload).encode()).hexdigest(), sha256(self._canonical(output_payload).encode()).hexdigest() if output_payload is not None else None, cost_cents, latency_ms, status, attempt_no, error_code, datetime.now(timezone.utc).isoformat())
        self.model_calls[record.id] = record
        return record

    def get_agent_run(self, *, org_id: UUID, run_id: UUID) -> PersistedAgentRun:
        record = self.agent_runs.get(run_id)
        if record is None or record.org_id != org_id:
            raise LedgerError("TENANT_SCOPE_VIOLATION", "agent run does not belong to organization")
        return record

    @staticmethod
    def _canonical(value: Any) -> str:
        return __import__("json").dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
