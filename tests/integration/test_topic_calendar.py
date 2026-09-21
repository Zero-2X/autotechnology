from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.topic import EditorialCalendarService, TopicOpportunityService, TopicSignalImportService


def test_calendar_api_and_restart_persistence(tmp_path) -> None:
    database = tmp_path / "calendar.db"
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    calendar = EditorialCalendarService(opportunities)
    client = TestClient(create_app(topic_signal_service=signals, topic_opportunity_service=opportunities,
                                   editorial_calendar_service=calendar))
    org_id, actor_id, owner_id = str(uuid4()), str(uuid4()), str(uuid4())
    row = {"source_type": "manual", "source_ref": "source:api-calendar", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "RAG summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                    idempotency_key="api-calendar-signal", rows=[row])["results"][0]["signal_id"]
    opportunity = opportunities.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                      idempotency_key="api-calendar-opportunity", signal_ids=[signal_id],
                                      canonical_topic="RAG API Calendar", scores={"demand": 80, "relevance": 90,
                                      "evidence_availability": 70, "differentiation": 60, "timeliness": 50,
                                      "cost": 20, "risk": 10}, expires_at="2099-01-01T00:00:00Z")["opportunity"]
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "api-calendar-create"}
    response = client.post(f"/internal/topic-opportunities/{opportunity['id']}:schedule", headers=headers,
                           json={"expected_version": 0, "owner_id": owner_id, "priority": "high",
                                 "due_at": "2027-01-01T00:00:00Z"})
    assert response.status_code == 200
    plan = response.json()["data"]["plan"]
    missing_reason = client.post(f"/internal/topic-opportunities/{opportunity['id']}:override",
                                 headers={**headers, "Idempotency-Key": "api-calendar-bad-override"},
                                 json={"expected_version": 1, "owner_id": owner_id, "priority": "urgent",
                                       "due_at": "2027-02-01T00:00:00Z"})
    assert missing_reason.status_code == 400
    overridden = client.post(f"/internal/topic-opportunities/{opportunity['id']}:override",
                             headers={**headers, "Idempotency-Key": "api-calendar-override"},
                             json={"expected_version": 1, "owner_id": owner_id, "priority": "urgent",
                                   "due_at": "2027-02-01T00:00:00Z", "manual_override_reason": "Campaign change"})
    assert overridden.status_code == 200
    assert overridden.json()["data"]["plan"]["version_no"] == 2
    calendar._connection.close()
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    calendar = EditorialCalendarService(opportunities)
    assert calendar.current(org_id=org_id, opportunity_id=opportunity["id"])["version_no"] == 2
    assert calendar.get(org_id=org_id, plan_id=plan["id"])["status"] == "superseded"
    calendar._connection.close()
    signals.close()
