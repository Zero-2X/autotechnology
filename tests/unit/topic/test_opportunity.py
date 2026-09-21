import json
import sqlite3
from uuid import uuid4

import pytest

from modules.topic import (
    TopicOpportunityError, TopicOpportunityService, TopicSignalImportService,
)


SCORES = {
    "demand": 80, "relevance": 90, "evidence_availability": 70,
    "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10,
}


def signal_row(source_ref="source:1", rights="verified", evidence="terms:1"):
    return {
        "source_type": "manual", "source_ref": source_ref, "captured_at": "2026-09-18T00:00:00Z",
        "locale": "en-US", "region": "US", "title": "RAG", "summary": "A useful question",
        "usage_rights_status": rights, "terms_snapshot_ref": evidence, "license_ref": None,
        "permitted_use": "editorial", "confidence": 0.9,
    }


def make_signal(service, org_id, actor_id, **changes):
    return service.import_json(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key=f"signal-{uuid4()}",
        rows=[signal_row(**changes)],
    )["results"][0]["signal_id"]


def test_score_is_explainable_recomputable_and_shortlist_requires_version() -> None:
    signals = TopicSignalImportService()
    org_id, actor_id = uuid4(), uuid4()
    signal_id = make_signal(signals, org_id, actor_id)
    service = TopicOpportunityService(signals)
    scored = service.score(
        org_id=org_id, actor_id=actor_id, trace_id="trace-score", idempotency_key="score-command-1",
        signal_ids=[signal_id], canonical_topic="RAG Patterns", scores=SCORES,
        expires_at="2099-01-01T00:00:00Z",
    )
    opportunity, snapshot = scored["opportunity"], scored["snapshot"]
    assert opportunity["score_total"] == 67.5
    assert opportunity["status"] == "proposed" and opportunity["shortlist_eligible"] is True
    assert snapshot["deductions"] == {"cost": 3.0, "risk": 2.5, "rights_blocked": False}
    assert snapshot["signal_inputs"]["signals"][0]["id"] == signal_id
    assert snapshot["signal_inputs"]["signals"][0]["deduction_reasons"] == []
    assert service.recompute_snapshot(org_id=org_id, snapshot_id=snapshot["id"]) == snapshot
    assert service.score(org_id=org_id, actor_id=actor_id, trace_id="trace-retry", idempotency_key="score-command-1",
                         signal_ids=[signal_id], canonical_topic="RAG Patterns", scores=SCORES,
                         expires_at="2099-01-01T00:00:00Z") == scored
    with pytest.raises(TopicOpportunityError) as error:
        service.score(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="score-command-2",
                      signal_ids=[signal_id], canonical_topic="rag patterns", scores=SCORES,
                      expires_at="2099-01-01T00:00:00Z")
    assert error.value.code == "TOPIC_ACTIVE_CONFLICT"
    shortlisted = service.shortlist(
        org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace-human",
        idempotency_key="shortlist-command-1", expected_version=0, decision_reason="Editorial review approved",
    )
    assert shortlisted["opportunity"]["status"] == "shortlisted"
    assert service.assert_brief_eligible(org_id=org_id, opportunity_id=opportunity["id"])["version"] == 1
    with pytest.raises(TopicOpportunityError) as error:
        service.shortlist(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="shortlist-command-2", expected_version=0, decision_reason="Again")
    assert error.value.code == "VERSION_CONFLICT"
    assert len(service.scored_events(org_id=org_id)) == 1
    service.close()
    signals.close()


def test_rights_and_evidence_block_shortlist_and_cross_tenant_reads() -> None:
    signals = TopicSignalImportService()
    org_id, actor_id, other_org = uuid4(), uuid4(), uuid4()
    signal_id = make_signal(signals, org_id, actor_id, rights="restricted", evidence=None)
    service = TopicOpportunityService(signals)
    scored = service.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                           idempotency_key="blocked-score", signal_ids=[signal_id],
                           canonical_topic="Restricted RAG", scores=SCORES,
                           expires_at="2099-01-01T00:00:00Z")
    snapshot, opportunity = scored["snapshot"], scored["opportunity"]
    assert snapshot["score_components"]["evidence_availability"] == 0
    assert snapshot["deductions"]["rights_blocked"] is True
    assert "missing_rights_evidence" in snapshot["signal_inputs"]["signals"][0]["deduction_reasons"]
    assert "usage_rights_restricted" in snapshot["signal_inputs"]["signals"][0]["deduction_reasons"]
    assert opportunity["shortlist_eligible"] is False
    with pytest.raises(TopicOpportunityError) as error:
        service.shortlist(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id, trace_id="trace",
                          idempotency_key="blocked-shortlist", expected_version=0, decision_reason="Try")
    assert error.value.code == "RIGHTS_BLOCK_SHORTLIST"
    with pytest.raises(TopicOpportunityError) as error:
        service.get(org_id=other_org, opportunity_id=opportunity["id"])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    service.close()
    signals.close()


def test_expired_opportunity_cannot_create_brief(monkeypatch) -> None:
    signals = TopicSignalImportService()
    org_id, actor_id = uuid4(), uuid4()
    signal_id = make_signal(signals, org_id, actor_id)
    service = TopicOpportunityService(signals)
    opportunity = service.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                idempotency_key="expires-score", signal_ids=[signal_id],
                                canonical_topic="Soon expires", scores=SCORES,
                                expires_at="2099-01-01T00:00:00Z")["opportunity"]
    service.shortlist(org_id=org_id, opportunity_id=opportunity["id"], actor_id=actor_id,
                      trace_id="trace", idempotency_key="expires-shortlist", expected_version=0,
                      decision_reason="Approved")
    monkeypatch.setattr("modules.topic.opportunity._now", lambda: "2099-01-01T00:00:00.000000Z")
    with pytest.raises(TopicOpportunityError) as error:
        service.assert_brief_eligible(org_id=org_id, opportunity_id=opportunity["id"])
    assert error.value.code == "TOPIC_OPPORTUNITY_EXPIRED"
    service.close()
    signals.close()


def test_input_snapshot_verification_is_idempotent_and_detects_signal_drift() -> None:
    signals = TopicSignalImportService()
    org_id, actor_id, other_org = uuid4(), uuid4(), uuid4()
    signal_id = make_signal(signals, org_id, actor_id)
    service = TopicOpportunityService(signals)
    scored = service.score(
        org_id=org_id, actor_id=actor_id, trace_id="trace-score", idempotency_key="snapshot-score",
        signal_ids=[signal_id], canonical_topic="Snapshot verification", scores=SCORES,
        expires_at="2099-01-01T00:00:00Z",
    )
    snapshot = scored["snapshot"]
    assert len(snapshot["input_snapshot_hash"]) == 64
    assert len(snapshot["signal_inputs"]["signals"][0]["input_hash"]) == 64

    report = service.verify_snapshot(
        org_id=org_id, snapshot_id=snapshot["id"], actor_id=actor_id,
        trace_id="trace-verify", idempotency_key="verify-1",
    )
    assert report["verified"] is True
    assert report["drift"] == []
    assert service.verify_snapshot(
        org_id=org_id, snapshot_id=snapshot["id"], actor_id=other_org,
        trace_id="different-trace", idempotency_key="verify-1",
    ) == report

    signal = signals.get(org_id=org_id, signal_id=signal_id)
    signal["title"] = "Changed after scoring"
    signals._connection.execute(
        "UPDATE topic_signals SET payload = ? WHERE org_id = ? AND id = ?",
        (json.dumps(signal, ensure_ascii=False, sort_keys=True), str(org_id), str(signal_id)),
    )
    signals._connection.commit()
    drifted = service.verify_snapshot(
        org_id=org_id, snapshot_id=snapshot["id"], actor_id=actor_id,
        trace_id="trace-verify-2", idempotency_key="verify-2",
    )
    assert drifted["verified"] is False
    assert drifted["drift"] == [f"{signal_id}:changed"]
    with pytest.raises(TopicOpportunityError) as error:
        service.verify_snapshot(
            org_id=other_org, snapshot_id=snapshot["id"], actor_id=actor_id,
            trace_id="trace-cross-tenant", idempotency_key="verify-other",
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(sqlite3.DatabaseError):
        service._connection.execute(
            "UPDATE topic_score_snapshot_verifications SET payload = '{}' "
            "WHERE org_id = ? AND snapshot_id = ? AND idempotency_key = ?",
            (str(org_id), snapshot["id"], "verify-1"),
        )
    service._connection.rollback()
    service.close()
    signals.close()


def test_tampered_score_snapshot_fails_recomputation() -> None:
    signals = TopicSignalImportService()
    org_id, actor_id = uuid4(), uuid4()
    signal_id = make_signal(signals, org_id, actor_id)
    service = TopicOpportunityService(signals)
    snapshot = service.score(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="tamper-score",
        signal_ids=[signal_id], canonical_topic="Tamper check", scores=SCORES,
        expires_at="2099-01-01T00:00:00Z",
    )["snapshot"]
    payload = json.loads(service._connection.execute(
        "SELECT payload FROM topic_score_snapshots WHERE id = ?", (snapshot["id"],)
    ).fetchone()[0])
    payload["score_components"]["demand"] = 1.0
    service._connection.execute(
        "UPDATE topic_score_snapshots SET payload = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False, sort_keys=True), snapshot["id"]),
    )
    service._connection.commit()
    with pytest.raises(TopicOpportunityError) as error:
        service.verify_snapshot(
            org_id=org_id, snapshot_id=snapshot["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="tamper-verify",
        )
    assert error.value.code == "SCORING_SNAPSHOT_MISMATCH"
    service.close()
    signals.close()
