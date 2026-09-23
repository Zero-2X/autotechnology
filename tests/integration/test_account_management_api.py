from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_account_management_routes_keep_credentials_out_of_contracts():
    app = create_app()
    client = TestClient(app)
    org_id, actor_id, platform_id = str(uuid4()), str(uuid4()), str(uuid4())
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "profile-create-1"}
    profile = client.post("/internal/account-profiles", headers=headers, json={
        "platform_id": platform_id, "profile_kind": "real", "display_name": "试点账号",
    })
    assert profile.status_code == 200
    profile_id = profile.json()["data"]["id"]
    listed = client.get("/internal/account-profiles", headers={"X-Org-Id": org_id})
    assert listed.status_code == 200 and listed.json()["data"][0]["display_name"] == "试点账号"
    target = client.post(f"/internal/account-profiles/{profile_id}/targets", headers={"X-Org-Id": org_id}, json={"channel": "short_post"})
    assert target.status_code == 200
    connection = client.post("/internal/account-connections", headers=headers, json={
        "account_profile_id": profile_id, "platform_id": platform_id,
        "external_account_id": "redacted-account", "environment": "sandbox",
        "scope_snapshot": {"provider": "fixture", "scopes": ["profile"]},
    })
    assert connection.status_code == 200
    connection_id = connection.json()["data"]["id"]
    passport = client.get(f"/internal/account-connections/{connection_id}/passport", headers={"X-Org-Id": org_id})
    assert passport.status_code == 200
    assert passport.json()["data"]["ready_for_side_effects"] is False
    assert "access-secret" not in passport.text.lower()
