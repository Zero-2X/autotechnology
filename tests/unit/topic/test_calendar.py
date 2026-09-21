import sqlite3
from uuid import uuid4

import pytest

from modules.topic import (
    EditorialCalendarError, EditorialCalendarService, TopicOpportunityService, TopicSignalImportService,
)


SCORES = {"demand": 80, "relevance": 90, "evidence_availability": 70,
          "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10}


def setup():
    signals = TopicSignalImportService()
    opportunities = TopicOpportunityService(signals)
    calendar = EditorialCalendarService(opportunities)
    org_id, actor_id, owner_id = uuid4(), uuid4(), uuid4()
    row = {"source_type": "manual", "source_ref": "source:calendar", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "RAG summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                    idempotency_key="calendar-signal", rows=[row])["results"][0]["signal_id"]
    opportunity = opportunities.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                      idempotency_key="calendar-opportunity", signal_ids=[signal_id],
                                      canonical_topic="RAG Calendar", scores=SCORES,
                                      expires_at="2099-01-01T00:00:00Z")["opportunity"]
    return signals, opportunities, calendar, org_id, actor_id, owner_id, opportunity


def test_schedule_and_manual_override_are_versioned_and_audited() -> None:
    signals, opportunities, calendar, org_id, actor_id, owner_id, opportunity = setup()
    scheduled = calendar.schedule(
        org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace-schedule",
        idempotency_key="calendar-create", expected_version=0, owner_id=owner_id,
        priority="high", due_at="2027-01-01T00:00:00Z",
    )
    assert scheduled["plan"]["version_no"] == 1
    assert scheduled["opportunity"]["editorial_plan_id"] == scheduled["plan"]["id"]
    assert scheduled["opportunity"]["owner_actor_id"] == str(owner_id)
    replay = calendar.schedule(
        org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="retry",
        idempotency_key="calendar-create", expected_version=0, owner_id=owner_id,
        priority="high", due_at="2027-01-01T00:00:00Z",
    )
    assert replay == scheduled
    with pytest.raises(EditorialCalendarError) as error:
        calendar.schedule(
            org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
            idempotency_key="calendar-duplicate", expected_version=1, owner_id=owner_id,
            priority="normal", due_at="2027-01-02T00:00:00Z",
        )
    assert error.value.code == "EDITORIAL_PLAN_EXISTS"
    overridden = calendar.schedule(
        org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace-override",
        idempotency_key="calendar-override", expected_version=1, owner_id=actor_id,
        priority="urgent", due_at="2027-02-01T00:00:00Z", manual_override_reason="Launch moved forward",
        override=True,
    )
    assert overridden["plan"]["version_no"] == 2
    assert overridden["plan"]["manual_override_reason"] == "Launch moved forward"
    assert calendar.get(org_id=org_id, plan_id=scheduled["plan"]["id"])["status"] == "superseded"
    assert calendar.current(org_id=org_id, opportunity_id=opportunity["id"]) == overridden["plan"]
    assert [item["event_type"] for item in calendar.audit(org_id=org_id)] == [
        "topic.editorial_plan.scheduled", "topic.editorial_plan.overridden"
    ]
    with pytest.raises(sqlite3.DatabaseError):
        calendar._connection.execute("DELETE FROM topic_editorial_audit")
    signals.close(); opportunities.close()


def test_calendar_validates_tenant_due_date_and_override_reason() -> None:
    signals, opportunities, calendar, org_id, actor_id, owner_id, opportunity = setup()
    with pytest.raises(EditorialCalendarError) as error:
        calendar.schedule(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="bad-priority", expected_version=0, owner_id=owner_id,
                          priority="p0", due_at="2027-01-01T00:00:00Z")
    assert error.value.code == "INVALID_PRIORITY"
    with pytest.raises(EditorialCalendarError) as error:
        calendar.schedule(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="bad-zone", expected_version=0, owner_id=owner_id,
                          priority="normal", due_at="2027-01-01T08:00:00+08:00")
    assert error.value.code == "INVALID_DUE_AT"
    with pytest.raises(EditorialCalendarError) as error:
        calendar.schedule(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="bad-override", expected_version=0, owner_id=owner_id,
                          priority="normal", due_at="2027-01-01T00:00:00Z", override=True)
    assert error.value.code == "INVALID_CALENDAR_COMMAND"
    with pytest.raises(EditorialCalendarError) as error:
        calendar.schedule(org_id=uuid4(), opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="other-tenant", expected_version=0, owner_id=owner_id,
                          priority="normal", due_at="2027-01-01T00:00:00Z")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    signals.close(); opportunities.close()
