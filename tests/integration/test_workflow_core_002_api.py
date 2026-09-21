from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.workflow import OutboxDispatcher


def test_workflow_run_and_human_task_routes_use_tenant_and_versions() -> None:
    client = TestClient(create_app())
    org_id = str(uuid4())
    actor_id = str(uuid4())
    created = client.post(
        "/internal/workflow-runs",
        headers={"X-Org-Id": org_id},
        json={"workflow_key": "review", "workflow_version": 1, "input_payload": {"id": "doc-1"}},
    )
    assert created.status_code == 200
    run = created.json()["data"]
    assert run["status"] == "running"

    task_response = client.post(
        f"/internal/workflow-runs/{run['id']}/human-tasks",
        headers={"X-Org-Id": org_id},
        json={},
    )
    assert task_response.status_code == 200
    task = task_response.json()["data"]
    claimed = client.post(
        f"/internal/human-tasks/{task['id']}:claim",
        headers={"X-Org-Id": org_id, "X-Actor-Id": actor_id},
        json={"expected_version": 0},
    )
    assert claimed.status_code == 200
    completed = client.post(
        f"/internal/human-tasks/{task['id']}:start",
        headers={"X-Org-Id": org_id, "X-Actor-Id": actor_id},
        json={"expected_version": 1},
    )
    assert completed.status_code == 200
    assert completed.json()["data"]["status"] == "in_progress"


def test_workflow_route_rejects_cross_tenant_access() -> None:
    client = TestClient(create_app())
    created = client.post(
        "/internal/workflow-runs",
        headers={"X-Org-Id": str(uuid4())},
        json={"workflow_key": "review", "workflow_version": 1, "input_payload": {}},
    )
    run_id = created.json()["data"]["id"]
    response = client.post(
        f"/internal/workflow-runs/{run_id}:pause",
        headers={"X-Org-Id": str(uuid4())},
        json={"expected_version": 1},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TENANT_SCOPE_VIOLATION"


def test_workflow_outbox_dispatch_requires_command_idempotency_key() -> None:
    dispatcher = OutboxDispatcher()
    org_id = uuid4()
    dispatcher.append_event(
        org_id=org_id,
        event_type="workflow.run.created",
        trace_id="trace-api",
        aggregate_type="workflow_run",
        aggregate_id=uuid4(),
        aggregate_version=1,
        idempotency_key="event-api",
        payload={},
    )
    client = TestClient(create_app(outbox_dispatcher=dispatcher))
    missing = client.post(
        "/internal/workflow/outbox:dispatch",
        headers={"X-Worker-Id": "worker-api"},
        json={"org_id": str(org_id)},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "INVALID_DISPATCH_COMMAND"
    dispatched = client.post(
        "/internal/workflow/outbox:dispatch",
        headers={"X-Worker-Id": "worker-api", "Idempotency-Key": "dispatch-api"},
        json={"org_id": str(org_id)},
    )
    assert dispatched.status_code == 200
    assert dispatched.json()["data"][0]["status"] == "published"
