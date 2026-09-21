from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_dev_identity_me_and_role_binding_endpoints() -> None:
    client = TestClient(create_app())
    org_id = str(uuid4())
    created = client.post(
        "/internal/dev-identities",
        headers={"Idempotency-Key": "owner-api-1234"},
        json={"org_id": org_id, "subject": "owner", "display_name": "Owner"},
    )
    assert created.status_code == 200
    owner_id = created.json()["data"]["id"]
    me = client.get("/internal/me", headers={"X-Org-Id": org_id, "X-Actor-Id": owner_id})
    assert me.status_code == 200
    assert me.json()["data"]["roles"] == ["owner"]
    editor = client.post(
        "/internal/dev-identities",
        headers={"Idempotency-Key": "editor-api-1234"},
        json={"org_id": org_id, "subject": "editor", "display_name": "Editor"},
    ).json()["data"]["id"]
    bound = client.post(
        "/internal/role-bindings",
        headers={"X-Org-Id": org_id, "X-Actor-Id": owner_id},
        json={"actor_id": editor, "role": "editor"},
    )
    assert bound.status_code == 200


def test_missing_tenant_context_is_explicit() -> None:
    response = TestClient(create_app()).get("/internal/me")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "TENANT_CONTEXT_REQUIRED"
