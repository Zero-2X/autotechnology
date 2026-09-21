from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.topic import TopicOpportunityService, TopicSignalImportService


def test_state_transition_api(tmp_path) -> None:
    database = tmp_path / "state.db"
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    client = TestClient(create_app(topic_signal_service=signals, topic_opportunity_service=opportunities))
    org_id, actor_id = str(uuid4()), str(uuid4())
    row = {"source_type": "manual", "source_ref": "api-state", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                    idempotency_key="api-state-signal", rows=[row])["results"][0]["signal_id"]
    opportunity = opportunities.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                      idempotency_key="api-state-opportunity", signal_ids=[signal_id],
                                      canonical_topic="API State", scores={"demand": 80, "relevance": 90,
                                      "evidence_availability": 70, "differentiation": 60, "timeliness": 50,
                                      "cost": 20, "risk": 10}, expires_at="2099-01-01T00:00:00Z")["opportunity"]
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "api-defer"}
    response = client.post(f"/internal/topic-opportunities/{opportunity['id']}:defer", headers=headers,
                           json={"expected_version": 0, "reason": "Wait for legal review"})
    assert response.status_code == 200
    assert response.json()["data"]["opportunity"]["status"] == "deferred"
    missing = client.post(f"/internal/topic-opportunities/{opportunity['id']}:reject",
                          headers={**headers, "Idempotency-Key": "api-reject"},
                          json={"expected_version": 1})
    assert missing.status_code == 400
    assert missing.json()["detail"]["code"] == "REASON_REQUIRED"
    opportunities.close(); signals.close()
