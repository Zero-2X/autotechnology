from uuid import uuid4

from fastapi.testclient import TestClient

from apps.api.main import create_app
from modules.topic import TopicBriefService, TopicOpportunityService, TopicSignalImportService


def test_brief_api_create_lock_and_supersede(tmp_path) -> None:
    database = tmp_path / "brief.db"
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    briefs = TopicBriefService(opportunities, type("Policy", (), {"verify": lambda self, **kwargs: True})())
    client = TestClient(create_app(topic_signal_service=signals, topic_opportunity_service=opportunities,
                                   topic_brief_service=briefs))
    org_id, actor_id = str(uuid4()), str(uuid4())
    row = {"source_type": "manual", "source_ref": "source:1", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "RAG summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                    idempotency_key="api-signal", rows=[row])["results"][0]["signal_id"]
    opportunity = opportunities.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                      idempotency_key="api-opportunity", signal_ids=[signal_id], canonical_topic="RAG",
                                      scores={"demand": 80, "relevance": 90, "evidence_availability": 70,
                                              "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10},
                                      expires_at="2099-01-01T00:00:00Z")["opportunity"]
    opportunities.shortlist(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                            trace_id="trace", idempotency_key="api-shortlist", expected_version=0,
                            decision_reason="review")
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "api-brief"}
    payload = {"opportunity_id": opportunity["id"], "content": {
        "audience": {"role": "engineer", "experience_level": "senior", "job_to_be_done": "choose"},
        "problem_statement": "Need a design", "core_claims": [{"claim_key": "c", "statement": "Claim", "evidence_plan_keys": ["p"]}],
        "evidence_plan": [{"key": "p", "required": True, "evidence_refs": ["e:1"]}],
        "original_angle": "Angle", "locales": ["en-US"], "markets": ["US"], "expected_channels": ["blog"]}}
    created = client.post("/internal/topic-briefs", headers=headers, json=payload)
    assert created.status_code == 200
    brief = created.json()["data"]["brief"]
    locked = client.post(f"/internal/topic-briefs/{brief['id']}:lock", headers={**headers, "Idempotency-Key": "api-lock"},
                         json={"expected_version_no": 1, "policy_snapshot_ref": "policy/v1"})
    assert locked.status_code == 200 and locked.json()["data"]["brief"]["status"] == "locked"
    briefs.opportunities._connection.close()


def test_brief_public_approval_route_uses_if_match_and_returns_approved_version(tmp_path) -> None:
    database = tmp_path / "brief-approval.db"
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    briefs = TopicBriefService(opportunities, type("Policy", (), {"verify": lambda self, **kwargs: True})())
    client = TestClient(create_app(topic_signal_service=signals, topic_opportunity_service=opportunities,
                                   topic_brief_service=briefs))
    org_id, creator_id, reviewer_id = str(uuid4()), str(uuid4()), str(uuid4())
    row = {"source_type": "manual", "source_ref": "source:approval", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "RAG summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=creator_id, trace_id="trace",
                                    idempotency_key="api-approval-signal", rows=[row])["results"][0]["signal_id"]
    opportunity = opportunities.score(
        org_id=org_id, actor_id=creator_id, trace_id="trace", idempotency_key="api-approval-opportunity",
        signal_ids=[signal_id], canonical_topic="RAG approval", scores={"demand": 80, "relevance": 90,
        "evidence_availability": 70, "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10},
        expires_at="2099-01-01T00:00:00Z",
    )["opportunity"]
    opportunities.shortlist(org_id=org_id, opportunity_id=opportunity["id"], actor_id=creator_id,
                            trace_id="trace", idempotency_key="api-approval-shortlist", expected_version=0,
                            decision_reason="review")
    create_headers = {"X-Org-Id": org_id, "X-Actor-Id": creator_id, "Idempotency-Key": "api-approval-create"}
    payload = {"opportunity_id": opportunity["id"], "content": {
        "audience": {"role": "engineer", "experience_level": "senior", "job_to_be_done": "choose"},
        "problem_statement": "Need a design", "core_claims": [{"claim_key": "c", "statement": "Claim",
        "evidence_plan_keys": ["p"]}], "evidence_plan": [{"key": "p", "required": True, "evidence_refs": ["e:1"]}],
        "original_angle": "Angle", "locales": ["en-US"], "markets": ["US"], "expected_channels": ["blog"]}}
    created = client.post("/internal/topic-briefs", headers=create_headers, json=payload)
    assert created.status_code == 200
    brief_id = created.json()["data"]["brief"]["id"]
    approve_headers = {"X-Org-Id": org_id, "X-Actor-Id": reviewer_id,
                       "Idempotency-Key": "api-approval", "If-Match": '"1"'}
    approved = client.post(f"/v1/topic-briefs/{brief_id}/approve", headers=approve_headers)
    assert approved.status_code == 200
    assert approved.json()["data"]["brief"]["status"] == "approved"
    replay = client.post(f"/v1/topic-briefs/{brief_id}/approve",
                         headers={**approve_headers, "X-Trace-Id": "replay"})
    assert replay.status_code == 200
    assert replay.json()["data"] == approved.json()["data"]
    stale = client.post(f"/v1/topic-briefs/{brief_id}/approve",
                        headers={**approve_headers, "Idempotency-Key": "api-approval-stale", "If-Match": "2"})
    assert stale.status_code == 409
    briefs.opportunities._connection.close()
