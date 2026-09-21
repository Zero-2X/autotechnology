from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.knowledge import KnowledgeService
from modules.provenance import RightsService, SourceService


def test_knowledge_core_api_validate_and_refresh_are_versioned(tmp_path) -> None:
    source = SourceService(tmp_path / "knowledge-core-api.db")
    rights = RightsService(connection=source._connection)
    client = TestClient(create_app(provenance_service=source, rights_service=rights))
    org_id, actor_id = uuid4(), uuid4()
    headers = {"X-Org-Id": str(org_id), "X-Actor-Id": str(actor_id)}
    try:
        captured = source.ingest(org_id=org_id, actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-source-1", source_type="url", canonical_url="https://api-core.example/source", content="api core")
        snapshot_id = captured["snapshot"]["id"]
        source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-source-2", action="quarantine", expected_version=0)
        source.transition_snapshot(org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-source-3", action="mark_usable", expected_version=1)
        right = rights.create_version(
            org_id=org_id, rights_record_id=uuid4(), actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-rights-1",
            source_snapshot_ids=[snapshot_id], license_ref="license:api", rights_holder="API Holder", permitted_regions=["US"],
            permitted_locales=["en-US"], permitted_media=["text"], permitted_use="commercial", terms_snapshot_hash="b" * 64,
            policy_rule_version="rights-v1", valid_to=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        )
        rights.verify_version(org_id=org_id, rights_record_id=right["rights_record"]["id"], version_id=right["version"]["id"], actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-rights-2", expected_version=1, verification_reason="reviewed")
        knowledge = KnowledgeService(connection=source._connection)
        entity = knowledge.create_entity(org_id=org_id, actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-entity", canonical_name="API core subject")
        claim = knowledge.create_claim(org_id=org_id, actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-claim", entity_ids=[entity["entity"]["id"]], statement="API core fact", fact_type="identity")
        evidence = knowledge.create_evidence(org_id=org_id, actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-evidence", source_snapshot_id=snapshot_id, claim_id=claim["claim"]["id"], rights_record_version_id=right["version"]["id"], quote="api core", locator="paragraph:1")
        knowledge.validate_evidence(org_id=org_id, evidence_id=evidence["evidence"]["id"], actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-evidence-validate", expected_version=0)
        knowledge.verify_claim(org_id=org_id, claim_id=claim["claim"]["id"], actor_id=actor_id, trace_id="api-core", idempotency_key="api-core-claim-verify", expected_version=0)

        created = client.post("/internal/knowledge-cores", headers={**headers, "Idempotency-Key": "api-core-create"}, json={"entity_ids": [entity["entity"]["id"]], "claim_ids": [claim["claim"]["id"]], "evidence_ids": [evidence["evidence"]["id"]]})
        assert created.status_code == 201
        core_id = created.json()["data"]["core"]["id"]
        validated = client.post(f"/internal/knowledge-cores/{core_id}:validate", headers={**headers, "Idempotency-Key": "api-core-validate"}, json={"expected_version": 1})
        assert validated.status_code == 200
        assert validated.json()["data"]["core"]["status"] == "validated"
        refreshed = client.post(f"/internal/knowledge-cores/{core_id}:refresh", headers={**headers, "Idempotency-Key": "api-core-refresh"}, json={"expected_version": 2})
        assert refreshed.status_code == 200
        assert refreshed.json()["data"]["version"]["version_no"] == 3
        assert refreshed.json()["data"]["core"]["status"] == "stale"
    finally:
        source.close()

