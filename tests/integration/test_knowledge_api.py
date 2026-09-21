from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.provenance import SourceService


def test_knowledge_api_runs_tenant_scoped_entity_claim_evidence_flow(tmp_path) -> None:
    source = SourceService(tmp_path / "knowledge-api.db")
    client = TestClient(create_app(provenance_service=source))
    org_id, actor_id, other_org = str(uuid4()), str(uuid4()), str(uuid4())
    base_headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id}
    try:
        source_response = client.post(
            "/v1/sources",
            headers={**base_headers, "Idempotency-Key": "api-knowledge-source"},
            json={
                "source_type": "url",
                "fetch_method": "url",
                "canonical_url": "https://knowledge-api.example/source",
                "content": {"body": "api evidence"},
            },
        )
        assert source_response.status_code == 201
        snapshot_id = source_response.json()["data"]["snapshot"]["id"]
        for action, version, key in (("quarantine", 0, "api-knowledge-quarantine"), ("mark_usable", 1, "api-knowledge-usable")):
            response = client.post(
                f"/internal/source-snapshots/{snapshot_id}:{action}",
                headers={**base_headers, "Idempotency-Key": key},
                json={"expected_version": version},
            )
            assert response.status_code == 200

        entity_response = client.post(
            "/v1/entities",
            headers={**base_headers, "Idempotency-Key": "api-knowledge-entity"},
            json={"canonical_name": "API Entity", "aliases": ["API"], "entity_type": "organization"},
        )
        assert entity_response.status_code == 201
        entity_id = entity_response.json()["data"]["entity"]["id"]
        claim_response = client.post(
            "/v1/claims",
            headers={**base_headers, "Idempotency-Key": "api-knowledge-claim"},
            json={
                "entity_ids": [entity_id],
                "statement": "The API entity has source-backed evidence.",
                "fact_type": "identity",
                "applicable_versions": ["v1"],
                "applicable_regions": ["US"],
                "applicable_locales": ["en-US"],
            },
        )
        assert claim_response.status_code == 201
        claim_id = claim_response.json()["data"]["claim"]["id"]
        evidence_response = client.post(
            "/v1/evidences",
            headers={**base_headers, "Idempotency-Key": "api-knowledge-evidence"},
            json={
                "source_snapshot_id": snapshot_id,
                "claim_id": claim_id,
                "quote": "api evidence",
                "locator": "paragraph:1",
                "applicable_versions": ["v1"],
                "applicable_regions": ["US"],
                "applicable_locales": ["en-US"],
            },
        )
        assert evidence_response.status_code == 201
        evidence_id = evidence_response.json()["data"]["evidence"]["id"]
        validated = client.post(
            f"/internal/evidences/{evidence_id}:validate",
            headers={**base_headers, "Idempotency-Key": "api-knowledge-validate"},
            json={"expected_version": 0},
        )
        assert validated.status_code == 200
        verified = client.post(
            f"/internal/claims/{claim_id}:verify",
            headers={**base_headers, "Idempotency-Key": "api-knowledge-verify"},
            json={"expected_version": 0},
        )
        assert verified.status_code == 200
        assert verified.json()["data"]["claim"]["status"] == "verified"

        forbidden = client.get(
            f"/internal/claims/{claim_id}",
            headers={"X-Org-Id": other_org},
        )
        assert forbidden.status_code == 403
    finally:
        source.close()

