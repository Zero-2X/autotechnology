import json
import sqlite3
from uuid import uuid4

import pytest

from modules.topic import (
    TopicBriefError, TopicBriefService, TopicOpportunityService, TopicSignalImportService,
)


SCORES = {"demand": 80, "relevance": 90, "evidence_availability": 70,
          "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10}


class AllowPolicy:
    def verify(self, **kwargs):
        return kwargs["policy_snapshot_ref"] == "policy/v1"


def content(ref="evidence:1"):
    return {
        "audience": {"role": "engineer", "experience_level": "senior", "job_to_be_done": "choose a RAG design"},
        "problem_statement": "Teams need a reliable retrieval design.",
        "core_claims": [{"claim_key": "claim-1", "statement": "Hybrid retrieval reduces misses.",
                         "evidence_plan_keys": ["plan-1"]}],
        "evidence_plan": [{"key": "plan-1", "required": True, "evidence_refs": [ref]}],
        "original_angle": "Failure-first comparison",
        "locales": ["en-US"], "markets": ["US"], "expected_channels": ["blog"],
    }


def setup():
    signals = TopicSignalImportService()
    opportunities = TopicOpportunityService(signals)
    org_id, actor_id = uuid4(), uuid4()
    row = {"source_type": "manual", "source_ref": "source:1", "captured_at": "2026-09-18T00:00:00Z",
           "locale": "en-US", "region": "US", "title": "RAG", "summary": "RAG summary",
           "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
           "permitted_use": "editorial", "confidence": 0.9}
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                    idempotency_key="signal-brief", rows=[row])["results"][0]["signal_id"]
    opportunity = opportunities.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                      idempotency_key="opportunity-brief", signal_ids=[signal_id],
                                      canonical_topic="RAG", scores=SCORES,
                                      expires_at="2099-01-01T00:00:00Z")["opportunity"]
    opportunities.shortlist(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                            trace_id="trace", idempotency_key="shortlist-brief", expected_version=0,
                            decision_reason="approved")
    return signals, opportunities, TopicBriefService(opportunities, AllowPolicy()), org_id, actor_id, opportunity


def test_brief_requires_evidence_refs_and_locks_only_shortlisted_opportunity() -> None:
    signals, opportunities, service, org_id, actor_id, opportunity = setup()
    with pytest.raises(TopicBriefError) as error:
        service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                       idempotency_key="brief-invalid", content={**content(), "core_claims": [
                           {"claim_key": "claim-1", "statement": "bad", "evidence_plan_keys": ["missing"]}
                       ]})
    assert error.value.code == "CLAIM_EVIDENCE_PLAN_MISSING"
    created = service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                             trace_id="trace", idempotency_key="brief-create", content=content())
    brief = created["brief"]
    locked = service.lock(org_id=org_id, brief_id=brief["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="brief-lock", expected_version_no=1, policy_snapshot_ref="policy/v1")
    assert locked["brief"]["status"] == "locked"
    replay = service.lock(org_id=org_id, brief_id=brief["id"], actor_id=actor_id, trace_id="new",
                          idempotency_key="brief-lock", expected_version_no=1, policy_snapshot_ref="policy/v1")
    assert replay == locked
    with pytest.raises(TopicBriefError) as error:
        service.lock(org_id=org_id, brief_id=brief["id"], actor_id=actor_id, trace_id="trace",
                     idempotency_key="brief-lock-different", expected_version_no=1, policy_snapshot_ref="policy/v2")
    assert error.value.code == "BRIEF_ALREADY_LOCKED"
    signals.close(); opportunities.close()


def test_supersede_creates_new_locked_version_and_preserves_old() -> None:
    signals, opportunities, service, org_id, actor_id, opportunity = setup()
    first = service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                           trace_id="trace", idempotency_key="brief-first", content=content())
    locked = service.lock(org_id=org_id, brief_id=first["brief"]["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="brief-first-lock", expected_version_no=1, policy_snapshot_ref="policy/v1")
    second = service.supersede(org_id=org_id, brief_id=first["brief"]["id"], actor_id=actor_id,
                               trace_id="trace", idempotency_key="brief-second", expected_version_no=1,
                               policy_snapshot_ref="policy/v1", content={**content("evidence:2"),
                               "original_angle": "Updated angle"})
    assert second["brief"]["version_no"] == 2 and second["brief"]["status"] == "locked"
    assert second["superseded_version_id"] == first["brief"]["id"]
    assert service.get(org_id=org_id, brief_id=first["brief"]["id"])["status"] == "superseded"
    assert service.latest_locked(org_id=org_id, opportunity_id=opportunity["id"])["id"] == second["brief"]["id"]
    assert len(service.events(org_id=org_id)) == 4
    signals.close(); opportunities.close()


def test_cross_tenant_and_policy_gate_are_enforced() -> None:
    signals, opportunities, service, org_id, actor_id, opportunity = setup()
    created = service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                             trace_id="trace", idempotency_key="brief-policy", content=content())
    with pytest.raises(TopicBriefError) as error:
        service.lock(org_id=uuid4(), brief_id=created["brief"]["id"], actor_id=actor_id, trace_id="trace",
                     idempotency_key="brief-other", expected_version_no=1, policy_snapshot_ref="policy/v1")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(TopicBriefError) as error:
        service.lock(org_id=org_id, brief_id=created["brief"]["id"], actor_id=actor_id, trace_id="trace",
                     idempotency_key="brief-denied", expected_version_no=1, policy_snapshot_ref="policy/deny")
    assert error.value.code == "POLICY_DENIED"
    signals.close(); opportunities.close()


def test_public_approval_persists_lock_metadata_and_is_immutable() -> None:
    signals, opportunities, service, org_id, actor_id, opportunity = setup()
    reviewer = uuid4()
    created = service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                             trace_id="trace", idempotency_key="approve-create", content=content())
    approved = service.approve(org_id=org_id, brief_id=created["brief"]["id"], actor_id=reviewer,
                               trace_id="approve-trace", idempotency_key="approve-command",
                               if_match='"1"')
    brief = approved["brief"]
    assert brief["status"] == "approved"
    assert brief["version_no"] == 1
    assert brief["created_by"] == str(actor_id)
    assert brief["locked_by"] == str(reviewer)
    assert brief["locked_at"] and brief["approved_at"]
    assert brief["lock_hash"] == service.recompute_lock_hash(brief)
    assert brief["input_snapshot_hash"]
    assert service.approve(org_id=org_id, brief_id=brief["id"], actor_id=uuid4(),
                           trace_id="replay", idempotency_key="approve-command", if_match="1") == approved
    with pytest.raises(TopicBriefError) as error:
        service.approve(org_id=org_id, brief_id=brief["id"], actor_id=uuid4(),
                        trace_id="concurrent", idempotency_key="approve-second", if_match="1")
    assert error.value.code == "OPTIMISTIC_LOCK_CONFLICT"
    with pytest.raises(TopicBriefError) as error:
        service.approve(org_id=org_id, brief_id=brief["id"], actor_id=reviewer,
                        trace_id="stale", idempotency_key="approve-stale", if_match="2")
    assert error.value.code == "OPTIMISTIC_LOCK_CONFLICT"
    with pytest.raises(sqlite3.DatabaseError):
        service._connection.execute(
            "UPDATE topic_briefs SET payload = ? WHERE org_id = ? AND id = ?",
            (json.dumps({**brief, "original_angle": "tampered"}, sort_keys=True), str(org_id), brief["id"]),
        )
    service._connection.rollback()
    event = [item for item in service.events(org_id=org_id) if item["event_type"] == "topic.brief.approved"][-1]
    assert event["payload"]["input_snapshot_hash"] == brief["input_snapshot_hash"]
    signals.close(); opportunities.close()


def test_creator_cannot_approve_and_approved_revision_starts_as_draft() -> None:
    signals, opportunities, service, org_id, actor_id, opportunity = setup()
    reviewer = uuid4()
    created = service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                             trace_id="trace", idempotency_key="creator-create", content=content())
    with pytest.raises(TopicBriefError) as error:
        service.approve(org_id=org_id, brief_id=created["brief"]["id"], actor_id=actor_id,
                        trace_id="trace", idempotency_key="creator-approve", if_match="1")
    assert error.value.code == "BRIEF_CREATOR_CANNOT_APPROVE"
    approved = service.approve(org_id=org_id, brief_id=created["brief"]["id"], actor_id=reviewer,
                               trace_id="trace", idempotency_key="reviewer-approve", if_match="1")
    revision = service.supersede(org_id=org_id, brief_id=approved["brief"]["id"], actor_id=actor_id,
                                 trace_id="trace", idempotency_key="revision", expected_version_no=1,
                                 policy_snapshot_ref="policy/v1", content={**content(), "original_angle": "New"})
    assert revision["brief"]["status"] == "draft"
    assert revision["brief"]["version_no"] == 2
    assert revision["brief"]["supersedes_version_id"] == approved["brief"]["id"]
    assert service.get(org_id=org_id, brief_id=approved["brief"]["id"])["status"] == "superseded"
    final = service.approve(org_id=org_id, brief_id=revision["brief"]["id"], actor_id=reviewer,
                            trace_id="trace", idempotency_key="revision-approve", if_match="2")
    assert final["brief"]["status"] == "approved"
    assert service.latest_locked(org_id=org_id, opportunity_id=opportunity["id"])["id"] == final["brief"]["id"]
    signals.close(); opportunities.close()


def test_approval_rejects_incomplete_draft_without_state_change() -> None:
    signals, opportunities, service, org_id, actor_id, opportunity = setup()
    reviewer = uuid4()
    created = service.create(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                             trace_id="trace", idempotency_key="incomplete-create", content=content())
    payload = created["brief"].copy()
    payload.pop("audience")
    service._connection.execute(
        "UPDATE topic_briefs SET payload = ? WHERE org_id = ? AND id = ?",
        (json.dumps(payload, sort_keys=True), str(org_id), created["brief"]["id"]),
    )
    service._connection.commit()
    with pytest.raises(TopicBriefError) as error:
        service.approve(org_id=org_id, brief_id=created["brief"]["id"], actor_id=reviewer,
                        trace_id="trace", idempotency_key="incomplete-approve", if_match="1")
    assert error.value.code == "TOPIC_BRIEF_INCOMPLETE"
    assert service.get(org_id=org_id, brief_id=created["brief"]["id"])["status"] == "draft"
    signals.close(); opportunities.close()
