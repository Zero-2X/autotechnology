"""Dependency-free workflow state machine with optimistic version checks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Protocol
from uuid import UUID, uuid4


class WorkflowError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WorkflowRun:
    id: UUID
    org_id: UUID
    workflow_key: str
    workflow_version: int
    status: str
    input_hash: str
    version: int
    created_at: str
    replayed_from_run_id: UUID | None = None


@dataclass(frozen=True)
class WorkflowStep:
    id: UUID
    run_id: UUID
    org_id: UUID
    step_key: str
    step_no: int
    status: str
    input_hash: str
    created_at: str
    version: int


@dataclass(frozen=True)
class HumanTask:
    id: UUID
    run_id: UUID
    org_id: UUID
    status: str
    version: int
    assignee_actor_id: UUID | None = None
    due_at: datetime | None = None


class WorkflowPort(Protocol):
    def start(self, **kwargs: Any) -> WorkflowRun: ...
    def resume(self, **kwargs: Any) -> WorkflowRun: ...
    def pause(self, **kwargs: Any) -> WorkflowRun: ...
    def retry(self, **kwargs: Any) -> WorkflowRun: ...
    def replay(self, **kwargs: Any) -> WorkflowRun: ...


class WorkflowService:
    transitions = {
        "planned": {"start": "running", "cancel": "cancelled"},
        "pending": {"start": "running", "cancel": "cancelled"},
        "running": {"pause": "paused", "wait_human": "waiting_human", "succeed": "succeeded", "fail": "failed", "cancel": "cancelled"},
        "paused": {"resume": "running", "cancel": "cancelled"},
        "waiting_human": {"resume": "running", "cancel": "cancelled"},
        "failed": {"retry": "running", "replay": "running"},
    }

    def __init__(self) -> None:
        self.runs: dict[UUID, WorkflowRun] = {}
        self.steps: dict[UUID, WorkflowStep] = {}
        self.human_tasks: dict[UUID, HumanTask] = {}
        self.outbox: list[dict[str, Any]] = []

    def start(self, *, org_id: UUID, workflow_key: str, workflow_version: int, input_payload: Any) -> WorkflowRun:
        if not workflow_key.strip():
            raise WorkflowError("INVALID_WORKFLOW", "workflow_key is required")
        if workflow_version < 1:
            raise WorkflowError("INVALID_WORKFLOW", "workflow_version must be positive")
        run = WorkflowRun(uuid4(), org_id, workflow_key, workflow_version, "planned", self._hash(input_payload), 0, datetime.now(timezone.utc).isoformat())
        self.runs[run.id] = run
        return self._transition(run.id, org_id=org_id, action="start", expected_version=0)

    def resume(self, *, org_id: UUID, run_id: UUID, expected_version: int) -> WorkflowRun:
        return self._transition(run_id, org_id=org_id, action="resume", expected_version=expected_version)

    def pause(self, *, org_id: UUID, run_id: UUID, expected_version: int) -> WorkflowRun:
        return self._transition(run_id, org_id=org_id, action="pause", expected_version=expected_version)

    def retry(self, *, org_id: UUID, run_id: UUID, expected_version: int, transient: bool) -> WorkflowRun:
        if not transient:
            raise WorkflowError("RETRY_NOT_ALLOWED", "only transient failures may be retried")
        return self._transition(run_id, org_id=org_id, action="retry", expected_version=expected_version)

    def replay(self, *, org_id: UUID, run_id: UUID, expected_version: int) -> WorkflowRun:
        source = self._get(run_id, org_id)
        if source.version != expected_version:
            raise WorkflowError("VERSION_CONFLICT", "workflow version changed")
        if source.status not in {"failed", "succeeded", "cancelled"}:
            raise WorkflowError("INVALID_STATE_TRANSITION", "only terminal runs may be replayed")
        replay = WorkflowRun(uuid4(), org_id, source.workflow_key, source.workflow_version, "running", source.input_hash, 1, datetime.now(timezone.utc).isoformat(), source.id)
        self.runs[replay.id] = replay
        self.outbox.append({"type": "workflow.run.replayed", "org_id": str(org_id), "run_id": str(replay.id), "replayed_from_run_id": str(source.id)})
        return replay

    def add_step(self, *, org_id: UUID, run_id: UUID, step_key: str, step_no: int, input_payload: Any) -> WorkflowStep:
        if not step_key.strip():
            raise WorkflowError("INVALID_STEP", "step_key is required")
        if step_no < 0:
            raise WorkflowError("INVALID_STEP", "step_no must be non-negative")
        self._get(run_id, org_id)
        step = WorkflowStep(
            uuid4(),
            run_id,
            org_id,
            step_key,
            step_no,
            "queued",
            self._hash(input_payload),
            datetime.now(timezone.utc).isoformat(),
            0,
        )
        self.steps[step.id] = step
        self.outbox.append({"type": "workflow.step.queued", "org_id": str(org_id), "run_id": str(run_id), "step_id": str(step.id), "input_hash": step.input_hash, "step_no": step.step_no})
        return step

    def create_human_task(self, *, org_id: UUID, run_id: UUID, due_at: datetime | None = None) -> HumanTask:
        run = self._get(run_id, org_id)
        task = HumanTask(uuid4(), run.id, org_id, "queued", 0, None, due_at)
        self.human_tasks[task.id] = task
        self.outbox.append({"type": "human_task.created", "org_id": str(org_id), "run_id": str(run_id), "task_id": str(task.id)})
        return task

    def claim_task(self, *, org_id: UUID, task_id: UUID, actor_id: UUID, expected_version: int, reviewer: bool = False) -> HumanTask:
        task = self._task(task_id, org_id)
        if task.version != expected_version:
            raise WorkflowError("VERSION_CONFLICT", "human task version changed")
        if task.status not in {"queued", "assigned"}:
            raise WorkflowError("INVALID_STATE_TRANSITION", "human task is not claimable")
        updated = replace(task, status="claimed", version=task.version + 1, assignee_actor_id=actor_id)
        self.human_tasks[task.id] = updated
        self.outbox.append({"type": "human_task.claimed", "org_id": str(org_id), "task_id": str(task.id), "actor_id": str(actor_id), "reviewer": reviewer})
        return updated

    def update_task(self, *, org_id: UUID, task_id: UUID, actor_id: UUID, expected_version: int, action: str, reviewer: bool = False) -> HumanTask:
        task = self._task(task_id, org_id)
        if task.version != expected_version:
            raise WorkflowError("VERSION_CONFLICT", "human task version changed")
        if task.assignee_actor_id != actor_id and not reviewer:
            raise WorkflowError("FORBIDDEN", "assignee or reviewer required")
        targets = {"start": ("claimed", "in_progress"), "submit": ("in_progress", "submitted"), "complete": ("submitted", "completed"), "reject": ("submitted", "rejected"), "cancel": ("queued", "cancelled")}
        expected, target = targets.get(action, ("", ""))
        if task.status != expected:
            if action == "complete" and task.status == "completed":
                return task
            raise WorkflowError("INVALID_STATE_TRANSITION", f"cannot {action} from {task.status}")
        updated = replace(task, status=target, version=task.version + 1)
        self.human_tasks[task.id] = updated
        self.outbox.append({"type": f"human_task.{target}", "org_id": str(org_id), "task_id": str(task.id), "actor_id": str(actor_id)})
        return updated

    def expire_due(self, *, now: datetime) -> list[HumanTask]:
        expired: list[HumanTask] = []
        for task in list(self.human_tasks.values()):
            if task.due_at and task.due_at <= now and task.status not in {"completed", "cancelled", "expired", "rejected"}:
                updated = replace(task, status="expired", version=task.version + 1)
                self.human_tasks[task.id] = updated
                run = self.runs[task.run_id]
                if run.status != "paused":
                    run = replace(run, status="paused", version=run.version + 1)
                    self.runs[run.id] = run
                    self.outbox.append({"type": "workflow.run.paused", "org_id": str(task.org_id), "run_id": str(run.id), "reason": "human_task_expired", "version": run.version})
                self.outbox.append({"type": "human_task.expired", "org_id": str(task.org_id), "task_id": str(task.id), "run_id": str(run.id)})
                expired.append(updated)
        return expired

    def _transition(self, run_id: UUID, *, org_id: UUID, action: str, expected_version: int) -> WorkflowRun:
        run = self._get(run_id, org_id)
        if run.version != expected_version:
            raise WorkflowError("VERSION_CONFLICT", "workflow version changed")
        target = self.transitions.get(run.status, {}).get(action)
        if target is None:
            raise WorkflowError("INVALID_STATE_TRANSITION", f"cannot {action} from {run.status}")
        updated = replace(run, status=target, version=run.version + 1)
        self.runs[run_id] = updated
        self.outbox.append({"type": f"workflow.run.{target}", "org_id": str(org_id), "run_id": str(run_id), "version": updated.version})
        return updated

    def _get(self, run_id: UUID, org_id: UUID) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run is None or run.org_id != org_id:
            raise WorkflowError("TENANT_SCOPE_VIOLATION", "workflow run does not belong to organization")
        return run

    def _task(self, task_id: UUID, org_id: UUID) -> HumanTask:
        task = self.human_tasks.get(task_id)
        if task is None or task.org_id != org_id:
            raise WorkflowError("TENANT_SCOPE_VIOLATION", "human task does not belong to organization")
        return task

    @staticmethod
    def _hash(value: Any) -> str:
        return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
