"""TaskJob to GraphRun mapping without duplicating TaskJob state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from .errors import GraphError


@dataclass(frozen=True)
class TaskGraphMapping:
    task_job_id: str
    org_id: str
    graph_key: str
    workflow_version: int
    idempotency_key: str
    trace_id: str
    input_refs: dict[str, str]


class TaskJobGraphMapper:
    """Translate a queued TaskJob projection into a runner command."""

    def map(self, task: Mapping[str, Any], *, org_id: UUID | str, actor_id: UUID | str | None = None) -> TaskGraphMapping:
        tenant = str(org_id)
        if str(task.get("org_id")) != tenant:
            raise GraphError("TENANT_SCOPE_VIOLATION", "TaskJob belongs to another organization")
        if task.get("status") not in {"queued", "running", "retryable"}:
            raise GraphError("TASK_STATE_INVALID", "only queued or retryable tasks can enter a graph")
        graph_key = task.get("graph_key") or task.get("workflow_key")
        if not isinstance(graph_key, str) or not graph_key.strip():
            raise GraphError("TASK_GRAPH_INVALID", "TaskJob has no graph key")
        refs = task.get("input_refs", {})
        if not isinstance(refs, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in refs.items()):
            raise GraphError("TASK_INPUT_INVALID", "TaskJob input_refs must be references")
        trace = task.get("trace_id")
        idem = task.get("idempotency_key")
        if not isinstance(trace, str) or not trace.strip() or not isinstance(idem, str) or not idem.strip():
            raise GraphError("TASK_CONTEXT_INVALID", "TaskJob requires trace_id and idempotency_key")
        try: version = int(task.get("workflow_version", task.get("graph_version", 1)))
        except (TypeError, ValueError) as exc: raise GraphError("TASK_GRAPH_INVALID", "workflow version is invalid") from exc
        return TaskGraphMapping(str(task.get("id")), tenant, graph_key.strip(), version, idem.strip(), trace.strip(), dict(refs))

    def command(self, task: Mapping[str, Any], *, org_id: UUID | str, actor_id: UUID | str) -> dict[str, Any]:
        mapping = self.map(task, org_id=org_id, actor_id=actor_id)
        return {"task_job_id": mapping.task_job_id, "org_id": mapping.org_id, "actor_id": str(actor_id),
                "graph_key": mapping.graph_key, "workflow_version": mapping.workflow_version,
                "idempotency_key": mapping.idempotency_key, "trace_id": mapping.trace_id,
                "input_refs": mapping.input_refs}


__all__ = ["TaskGraphMapping", "TaskJobGraphMapper"]
