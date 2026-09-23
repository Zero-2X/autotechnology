from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.operations import OperationsPolicyStore


def test_operations_policy_api_and_guard_use_console_state(tmp_path, monkeypatch):
    state_path = Path(tmp_path) / "workflow-state.json"
    policy_path = Path(tmp_path) / "operations-policy.json"
    monkeypatch.setattr("apps.api.main.CONSOLE_STATE_PATH", state_path)
    app = create_app(operations_policy_store=OperationsPolicyStore(policy_path))
    client = TestClient(app)
    state = {
        "accounts": [{"id": "acct-1", "name": "试点账号"}],
        "contents": [{"status": "published", "account": "试点账号", "publishedAt": datetime.now(timezone.utc).isoformat()}],
    }
    assert client.put("/internal/console/state", json={"state": state}).status_code == 200
    response = client.put("/internal/operations/policy", json={
        "default_limits": {"daily_publish": 1, "weekly_publish": 4},
        "accounts": {"acct-1": {"enabled": True, "limits": {"daily_publish": 1, "weekly_publish": 4}}},
    })
    assert response.status_code == 200
    guarded = client.post("/internal/operations/guard", json={"action": "prepare_publish", "account_key": "acct-1"})
    assert guarded.status_code == 200
    assert guarded.json()["data"]["allowed"] is False


def test_xhs_browser_route_honors_emergency_stop(monkeypatch, tmp_path):
    monkeypatch.setattr("apps.api.main.CONSOLE_STATE_PATH", Path(tmp_path) / "state.json")
    store = OperationsPolicyStore(Path(tmp_path) / "policy.json")
    store.update_stop(paused=True, reason="演练")
    called = False

    def fake_launch(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "browser_starting"}

    monkeypatch.setattr("apps.api.main.launch_operator_session", fake_launch)
    client = TestClient(create_app(operations_policy_store=store))
    response = client.post(
        "/internal/xhs/accounts/xhs-9653254890/browser:open",
        json={"target": "publish", "content": {"title": "标题", "body": "正文"}},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "OPERATIONS_POLICY_BLOCKED"
    assert called is False
