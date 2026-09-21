import sqlite3
from uuid import uuid4

import pytest

from modules.topic import TopicOpportunityError, TopicOpportunityService, TopicSignalImportService


SCORES = {"demand": 80, "relevance": 90, "evidence_availability": 70,
          "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10}


def setup():
    signals = TopicSignalImportService()
    service = TopicOpportunityService(signals)
    org_id, actor_id = uuid4(), uuid4()
    row = {"source_type": "manual", "source_ref": "state:1", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                    idempotency_key="state-signal", rows=[row])["results"][0]["signal_id"]
    opportunity = service.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                idempotency_key="state-opportunity", signal_ids=[signal_id],
                                canonical_topic="State RAG", scores=SCORES,
                                expires_at="2099-01-01T00:00:00Z")["opportunity"]
    return signals, service, org_id, actor_id, opportunity


def test_reject_defer_resume_and_expire_require_reasons_and_versions() -> None:
    signals, service, org_id, actor_id, opportunity = setup()
    with pytest.raises(TopicOpportunityError) as error:
        service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                           idempotency_key="defer-no-reason", action="defer", expected_version=0)
    assert error.value.code == "REASON_REQUIRED"
    deferred = service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                                  trace_id="trace", idempotency_key="defer-one", action="defer",
                                  expected_version=0, reason="Need customer interview")
    assert deferred["opportunity"]["status"] == "deferred"
    replay = service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                                trace_id="retry", idempotency_key="defer-one", action="defer",
                                expected_version=0, reason="Need customer interview")
    assert replay == deferred
    resumed = service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                                 trace_id="trace", idempotency_key="resume-one", action="resume",
                                 expected_version=1, reason="Interview complete")
    assert resumed["opportunity"]["status"] == "proposed"
    rejected = service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                                 trace_id="trace", idempotency_key="reject-one", action="reject",
                                 expected_version=2, reason="Evidence is insufficient")
    assert rejected["opportunity"]["status"] == "rejected"
    with pytest.raises(TopicOpportunityError) as error:
        service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                           idempotency_key="expire-after-reject", action="expire", expected_version=3)
    assert error.value.code == "INVALID_TOPIC_STATE"
    events = service.state_events(org_id=org_id, opportunity_id=opportunity["id"])
    assert [event["payload"]["to_state"] for event in events] == ["deferred", "proposed", "rejected"]
    with pytest.raises(sqlite3.DatabaseError):
        service._connection.execute("DELETE FROM topic_opportunity_state_events")
    signals.close(); service.close()


def test_cross_tenant_and_locked_brief_block_state_changes() -> None:
    signals, service, org_id, actor_id, opportunity = setup()
    with pytest.raises(TopicOpportunityError) as error:
        service.transition(org_id=uuid4(), opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                           idempotency_key="other-tenant", action="reject", expected_version=0, reason="No")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    service._connection.execute(
        "CREATE TABLE topic_briefs (id TEXT PRIMARY KEY, org_id TEXT, opportunity_id TEXT, status TEXT)"
    )
    service._connection.execute("INSERT INTO topic_briefs VALUES ('b', ?, ?, 'locked')",
                                (str(org_id), str(opportunity["id"])))
    service._connection.commit()
    with pytest.raises(TopicOpportunityError) as error:
        service.transition(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                           idempotency_key="locked-reject", action="reject", expected_version=0, reason="No")
    assert error.value.code == "BRIEF_LOCKED"
    signals.close(); service.close()
