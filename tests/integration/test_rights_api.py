from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.provenance import RightsService, SourceService


def _ready_source(service: SourceService, org_id, actor_id):
    created = service.ingest(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="api-rights-source-1",
        source_type="url", canonical_url="https://rights-api.example/source", content="source",
    )
    snapshot_id = created["snapshot"]["id"]
    service.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
                                idempotency_key="api-rights-source-2", action="quarantine", expected_version=0)
    service.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
                                idempotency_key="api-rights-source-3", action="mark_usable", expected_version=1)
    return snapshot_id


def test_rights_api_creates_and_verifies_version(tmp_path) -> None:
    source = SourceService(tmp_path / "rights-api.db")
    rights = RightsService(connection=source._connection)
    client = TestClient(create_app(provenance_service=source, rights_service=rights))
    org_id, actor_id, record_id = str(uuid4()), str(uuid4()), str(uuid4())
    snapshot_id = _ready_source(source, org_id, actor_id)
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "api-rights-version-1"}
    created = client.post(
        f"/v1/rights-records/{record_id}/versions", headers=headers,
        json={"source_snapshot_ids": [snapshot_id], "license_ref": "license:api",
              "rights_holder": "API Holder", "permitted_regions": ["US"],
              "permitted_locales": ["en-US"], "permitted_media": ["text"],
              "permitted_use": "commercial", "terms_snapshot_hash": "b" * 64,
              "policy_rule_version": "rights-policy-v1"},
    )
    assert created.status_code == 201
    version = created.json()["data"]["version"]
    verified = client.post(
        f"/v1/rights-records/{record_id}/versions/{version['id']}/verify",
        headers={**headers, "Idempotency-Key": "api-rights-verify-1", "If-Match": "1"},
        json={"verification_reason": "manual review"},
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["version"]["status"] == "verified"
    source.close()
