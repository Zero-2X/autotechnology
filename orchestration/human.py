"""Human interrupt and resume facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .errors import GraphInterrupt, GraphError

_REFERENCE_PREFIXES = (
    "private://", "ref://", "artifact://", "evidence://", "policy://", "human://",
    "task://", "object://", "error://", "resume://",
)


def _validate_refs(refs: Mapping[str, str], *, field: str) -> dict[str, str]:
    if not isinstance(refs, Mapping):
        raise GraphError("REFERENCE_MAP_INVALID", f"{field} must be a reference map")
    validated: dict[str, str] = {}
    for key, value in refs.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise GraphError("REFERENCE_MAP_INVALID", f"{field} keys must be bounded text")
        if not isinstance(value, str) or not value.startswith(_REFERENCE_PREFIXES) or len(value) > 2048:
            raise GraphError("REFERENCE_MAP_INVALID", f"{field}.{key} must be an opaque reference")
        validated[key] = value
    return validated


@dataclass(frozen=True)
class HumanTask:
    id: str
    org_id: str
    run_id: str
    task_type: str
    status: str
    input_refs: dict[str, str]
    assigned_to: str | None = None
    result_refs: dict[str, str] | None = None
    expires_at: str | None = None


class HumanTaskService:
    def __init__(self) -> None:
        self.tasks: dict[str, HumanTask] = {}
        self.audit: list[dict[str, Any]] = []

    def interrupt(self, *, org_id: str, run_id: str, task_type: str,
                  input_refs: Mapping[str, str], expires_at: str | None = None) -> HumanTask:
        input_refs = _validate_refs(input_refs, field="input_refs")
        if any(str(key).lower() in {"token", "secret", "password", "body", "prompt"} for key in input_refs):
            raise GraphError("SENSITIVE_STATE_REJECTED", "human task contains a sensitive reference")
        task = HumanTask(str(uuid4()), str(org_id), str(run_id), task_type, "waiting", dict(input_refs), expires_at=expires_at)
        self.tasks[task.id] = task
        self.audit.append({"event_type": "human_task.created", "task_id": task.id, "org_id": task.org_id, "run_id": task.run_id})
        return task

    def claim(self, *, org_id: str, task_id: str, actor_id: str) -> HumanTask:
        task = self._owned(org_id, task_id)
        if task.status != "waiting":
            raise GraphError("HUMAN_TASK_STATE_INVALID", "task is not waiting")
        updated = HumanTask(task.id, task.org_id, task.run_id, task.task_type, "claimed", task.input_refs,
                            assigned_to=str(actor_id), result_refs=task.result_refs, expires_at=task.expires_at)
        self.tasks[task.id] = updated
        self.audit.append({"event_type": "human_task.claimed", "task_id": task.id, "actor_id": str(actor_id)})
        return updated

    def resolve(self, *, org_id: str, task_id: str, actor_id: str,
                result_refs: Mapping[str, str]) -> HumanTask:
        task = self._owned(org_id, task_id)
        if task.status not in {"claimed", "waiting"} or (task.assigned_to not in {None, str(actor_id)}):
            raise GraphError("HUMAN_TASK_STATE_INVALID", "task cannot be resolved by actor")
        result_refs = _validate_refs(result_refs, field="result_refs")
        if any(str(key).lower() in {"token", "secret", "password", "body", "prompt"} for key in result_refs):
            raise GraphError("SENSITIVE_STATE_REJECTED", "human task result contains a sensitive reference")
        updated = HumanTask(task.id, task.org_id, task.run_id, task.task_type, "resolved", task.input_refs,
                            assigned_to=task.assigned_to or str(actor_id), result_refs=dict(result_refs), expires_at=task.expires_at)
        self.tasks[task.id] = updated
        self.audit.append({"event_type": "human_task.resolved", "task_id": task.id, "actor_id": str(actor_id)})
        return updated

    def _owned(self, org_id: str, task_id: str) -> HumanTask:
        task = self.tasks.get(str(task_id))
        if task is None or task.org_id != str(org_id):
            raise GraphError("HUMAN_TASK_NOT_FOUND", "human task is not available in organization")
        return task


def require_human(*, interrupt_ref: str, message: str = "human approval required") -> None:
    raise GraphInterrupt(interrupt_ref, message)


__all__ = ["HumanTask", "HumanTaskService", "require_human"]
