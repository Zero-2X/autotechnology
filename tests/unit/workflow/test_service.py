from uuid import uuid4

import pytest

from modules.workflow import WorkflowError, WorkflowService


def test_workflow_state_machine_versions_and_outbox() -> None:
    service = WorkflowService()
    org_id = uuid4()
    run = service.start(org_id=org_id, workflow_key="publish", workflow_version=1, input_payload={"x": 1})
    assert (run.status, run.version) == ("running", 1)
    paused = service.pause(org_id=org_id, run_id=run.id, expected_version=1)
    resumed = service.resume(org_id=org_id, run_id=run.id, expected_version=paused.version)
    assert resumed.version == 3
    with pytest.raises(WorkflowError) as error:
        service.resume(org_id=org_id, run_id=run.id, expected_version=paused.version)
    assert error.value.code == "VERSION_CONFLICT"
    assert len(service.outbox) == 3


def test_retry_requires_transient_and_replay_creates_new_run() -> None:
    service = WorkflowService()
    org_id = uuid4()
    run = service.start(org_id=org_id, workflow_key="publish", workflow_version=1, input_payload={})
    failed = service._transition(run.id, org_id=org_id, action="fail", expected_version=1)
    with pytest.raises(WorkflowError) as error:
        service.retry(org_id=org_id, run_id=run.id, expected_version=failed.version, transient=False)
    assert error.value.code == "RETRY_NOT_ALLOWED"
    retried = service.retry(org_id=org_id, run_id=run.id, expected_version=failed.version, transient=True)
    assert retried.status == "running"
    terminal = service._transition(run.id, org_id=org_id, action="fail", expected_version=retried.version)
    replay = service.replay(org_id=org_id, run_id=terminal.id, expected_version=terminal.version)
    assert replay.replayed_from_run_id == terminal.id


def test_cross_tenant_and_invalid_transition_are_rejected() -> None:
    service = WorkflowService()
    run = service.start(org_id=uuid4(), workflow_key="x", workflow_version=1, input_payload={})
    with pytest.raises(WorkflowError) as error:
        service.pause(org_id=uuid4(), run_id=run.id, expected_version=1)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(WorkflowError) as error:
        service.pause(org_id=run.org_id, run_id=run.id, expected_version=0)
    assert error.value.code == "VERSION_CONFLICT"


def test_human_task_claim_update_and_expiry_pause_run() -> None:
    from datetime import datetime, timedelta, timezone

    service = WorkflowService()
    org_id = uuid4()
    run = service.start(org_id=org_id, workflow_key="review", workflow_version=1, input_payload={})
    task = service.create_human_task(org_id=org_id, run_id=run.id, due_at=datetime.now(timezone.utc) + timedelta(seconds=1))
    claimed = service.claim_task(org_id=org_id, task_id=task.id, actor_id=uuid4(), expected_version=0)
    started = service.update_task(org_id=org_id, task_id=task.id, actor_id=claimed.assignee_actor_id, expected_version=claimed.version, action="start")
    submitted = service.update_task(org_id=org_id, task_id=task.id, actor_id=claimed.assignee_actor_id, expected_version=started.version, action="submit")
    completed = service.update_task(org_id=org_id, task_id=task.id, actor_id=claimed.assignee_actor_id, expected_version=submitted.version, action="complete")
    assert completed.status == "completed"
    due = service.create_human_task(org_id=org_id, run_id=run.id, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    assert service.expire_due(now=datetime.now(timezone.utc))[0].id == due.id
    assert service.runs[run.id].status == "paused"


def test_workflow_step_keeps_contract_fields_and_expiry_is_idempotent() -> None:
    from datetime import datetime, timedelta, timezone

    service = WorkflowService()
    org_id = uuid4()
    run = service.start(org_id=org_id, workflow_key="publish", workflow_version=1, input_payload={"title": "x"})
    step = service.add_step(org_id=org_id, run_id=run.id, step_key="review", step_no=2, input_payload={"body": "draft"})
    assert step.status == "queued"
    assert step.step_no == 2
    assert len(step.input_hash) == 64
    assert step.created_at.endswith("+00:00")
    due = service.create_human_task(org_id=org_id, run_id=run.id, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    first = service.expire_due(now=datetime.now(timezone.utc))
    second = service.expire_due(now=datetime.now(timezone.utc))
    assert [item.id for item in first] == [due.id]
    assert second == []
    assert [item["type"] for item in service.outbox if "expired" in item["type"]] == ["human_task.expired"]
