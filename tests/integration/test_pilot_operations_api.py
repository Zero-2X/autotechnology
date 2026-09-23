from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.operations import PilotRunStore


def test_pilot_operations_api_is_local_and_credential_free(tmp_path, monkeypatch):
    app = create_app(pilot_run_store=PilotRunStore(Path(tmp_path) / "pilot-runs.json"))
    client = TestClient(app)
    response = client.post("/internal/operations/pilot-runs", json={
        "name": "跨平台人工确认试点",
        "start_at": datetime.now(timezone.utc).isoformat(),
        "owner": "运营",
        "backup": "审核",
        "account_keys": ["xhs-9653254890", "demo-1"],
        "stop_conditions": ["版权投诉", "平台异常提示"],
    })
    assert response.status_code == 200
    run = response.json()["data"]
    assert "password" not in str(run).lower()
    run_id = run["id"]
    assert client.post(f"/internal/operations/pilot-runs/{run_id}:start", json={}).status_code == 200
    assert client.post(f"/internal/operations/pilot-runs/{run_id}/items", json={
        "title": "人工确认的跨平台内容",
        "account_key": "xhs-9653254890",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }).status_code == 200
    summary = client.get(f"/internal/operations/pilot-runs/{run_id}/summary")
    assert summary.status_code == 200
    assert summary.json()["data"]["item_counts"]["planned"] == 1
    assert client.post(f"/internal/operations/pilot-runs/{run_id}:stop", json={"reason": "平台规则变更"}).status_code == 200
    assert client.post(f"/internal/operations/pilot-runs/{run_id}/items", json={
        "title": "不应添加",
        "account_key": "demo-1",
        "scheduled_at": datetime.now(timezone.utc).isoformat(),
    }).status_code == 400

