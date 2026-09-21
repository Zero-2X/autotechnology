"""Single transactional failure command for worker execution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .task_failure import RetryDecision, TaskFailureStore


@dataclass(frozen=True)
class FailureCommand:
    job_id: str
    org_id: str
    error_class: str
    error_code: str
    trace_id: str
    lease_token: str | None = None
    worker_id: str | None = None
    attempt_count: int | None = None
    message_redacted: str | None = None
    expected_version: int | None = None
    occurred_at: datetime | None = None


class TaskFailureFacade:
    """The only worker-facing failure path.

    TaskFailureStore performs the INSERT, retry/dead-letter decision, job state
    update, and lease cleanup in one transaction. The facade is deliberately
    thin so no second state-only failure implementation can drift.
    """

    def __init__(self, store: TaskFailureStore) -> None:
        self.store = store

    def handle(self, command: FailureCommand) -> RetryDecision:
        return self.store.record_failure(
            job_id=command.job_id, org_id=command.org_id,
            error_class=command.error_class, error_code=command.error_code,
            trace_id=command.trace_id, lease_token=command.lease_token,
            worker_id=command.worker_id, attempt_count=command.attempt_count,
            message_redacted=command.message_redacted,
            expected_version=command.expected_version,
            occurred_at=command.occurred_at,
        )

    __call__ = handle
