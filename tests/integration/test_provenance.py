from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.provenance import SourceService


def test_source_api_ingest_transition_and_cross_tenant_rejection(tmp_path) -> None:
    service = SourceService(tmp_path / "provenance.db")
    client = TestClient(create_app(provenance_service=service))
    org_id, actor_id, other_org = str(uuid4()), str(uuid4()), str(uuid4())
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "api-source-001"}
    response = client.post(
        "/v1/sources",
        headers=headers,
        json={"source_type": "url", "fetch_method": "url", "canonical_url": "https://example.test/api",
              "content": {"body": "captured"}, "confidence": 0.9},
    )
    assert response.status_code == 201
    body = response.json()["data"]
    snapshot_id = body["snapshot"]["id"]
    transition = client.post(
        f"/internal/source-snapshots/{snapshot_id}:quarantine",
        headers={**headers, "Idempotency-Key": "api-source-002"},
        json={"expected_version": 0},
    )
    assert transition.status_code == 200
    assert transition.json()["data"]["snapshot"]["status"] == "quarantined"
    forbidden = client.get(f"/internal/sources/{body['source']['id']}", headers={"X-Org-Id": other_org})
    assert forbidden.status_code == 403
    service.close()


def test_source_service_reopens_from_file_and_preserves_audit_chain(tmp_path) -> None:
    path = tmp_path / "reopen.db"
    org_id, actor_id = uuid4(), uuid4()
    first = SourceService(path)
    created = first.ingest(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="persist-source-1",
        source_type="file", fetch_method="upload", content=b"persisted", confidence=0.7,
    )
    first.close()
    second = SourceService(path)
    assert second.get_source(org_id=org_id, source_id=created["source"]["id"])["id"] == created["source"]["id"]
    assert len(second.events(org_id=org_id)) == 1
    second.close()
