import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
import pytest

from apps.api.main import create_app
from modules.topic import TopicOpportunityService, TopicSignalImportService


SCORES = {"demand": 80, "relevance": 90, "evidence_availability": 70,
          "differentiation": 60, "timeliness": 50, "cost": 20, "risk": 10}


def signal_row():
    return {"source_type": "manual", "source_ref": "source:1", "captured_at": "2026-09-18T00:00:00Z",
            "locale": "en-US", "region": "US", "title": "RAG", "summary": "A useful question",
            "usage_rights_status": "verified", "terms_snapshot_ref": "terms:1", "license_ref": None,
            "permitted_use": "editorial", "confidence": 0.9}


def test_opportunity_and_score_snapshot_survive_restart(tmp_path) -> None:
    database = tmp_path / "topic.db"
    org_id, actor_id = uuid4(), uuid4()
    signals = TopicSignalImportService(database)
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                     idempotency_key="signal-restart", rows=[signal_row()])["results"][0]["signal_id"]
    service = TopicOpportunityService(signals, database)
    scored = service.score(org_id=org_id, actor_id=actor_id, trace_id="trace",
                           idempotency_key="opportunity-restart", signal_ids=[signal_id],
                           canonical_topic="RAG Patterns", scores=SCORES,
                           expires_at="2099-01-01T00:00:00Z")
    service.close()
    signals.close()

    signals = TopicSignalImportService(database)
    service = TopicOpportunityService(signals, database)
    assert service.get(org_id=org_id, opportunity_id=scored["opportunity"]["id"]) == scored["opportunity"]
    assert service.recompute_snapshot(org_id=org_id, snapshot_id=scored["snapshot"]["id"]) == scored["snapshot"]
    assert service.score(org_id=org_id, actor_id=actor_id, trace_id="retry",
                         idempotency_key="opportunity-restart", signal_ids=[signal_id],
                         canonical_topic="RAG Patterns", scores=SCORES,
                         expires_at="2099-01-01T00:00:00Z") == scored
    event, = service.scored_events(org_id=org_id)
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "packages/contracts/events/topic-opportunity-scored.schema.json").read_text(encoding="utf-8"))
    envelope = json.loads((root / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
    uri = schema["$id"].rsplit("/", 1)[0] + "/event-envelope.schema.json"
    validator = Draft202012Validator(schema, registry=Registry().with_resource(uri, Resource.from_contents(envelope)),
                                      format_checker=FormatChecker())
    validator.validate(event)
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE topic_scoring_versions SET content_hash = 'tamper'")
    service.close()
    signals.close()


def test_score_and_human_shortlist_api(tmp_path) -> None:
    database = tmp_path / "api.db"
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    client = TestClient(create_app(topic_signal_service=signals, topic_opportunity_service=opportunities))
    org_id, actor_id = str(uuid4()), str(uuid4())
    signal_id = signals.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace",
                                     idempotency_key="signal-api", rows=[signal_row()])["results"][0]["signal_id"]
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "opportunity-api"}
    response = client.post("/internal/topic-opportunities:score", headers=headers,
                           json={"signal_ids": [signal_id], "canonical_topic": "RAG Patterns",
                                 "scores": SCORES, "expires_at": "2099-01-01T00:00:00Z"})
    assert response.status_code == 200
    opportunity = response.json()["data"]["opportunity"]
    denied = client.post(f"/internal/topic-opportunities/{opportunity['id']}:shortlist",
                         headers={**headers, "Idempotency-Key": "shortlist-api"},
                         json={"expected_version": 0, "decision_reason": "Human review"})
    assert denied.status_code == 403
    accepted = client.post(f"/internal/topic-opportunities/{opportunity['id']}:shortlist",
                           headers={**headers, "Idempotency-Key": "shortlist-api", "X-Actor-Type": "user"},
                           json={"expected_version": 0, "decision_reason": "Human review"})
    assert accepted.status_code == 200
    assert accepted.json()["data"]["opportunity"]["status"] == "shortlisted"
    opportunities.close()
    signals.close()


def test_score_snapshot_verification_api_is_tenant_scoped_and_idempotent(tmp_path) -> None:
    database = tmp_path / "verification-api.db"
    signals = TopicSignalImportService(database)
    opportunities = TopicOpportunityService(signals, database)
    client = TestClient(create_app(topic_signal_service=signals, topic_opportunity_service=opportunities))
    org_id, actor_id, other_org = str(uuid4()), str(uuid4()), str(uuid4())
    signal_id = signals.import_json(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="signal-verification-api",
        rows=[signal_row()],
    )["results"][0]["signal_id"]
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "score-verification-api"}
    scored = client.post(
        "/internal/topic-opportunities:score", headers=headers,
        json={"signal_ids": [signal_id], "canonical_topic": "Verification API",
              "scores": SCORES, "expires_at": "2099-01-01T00:00:00Z"},
    )
    assert scored.status_code == 200
    snapshot_id = scored.json()["data"]["snapshot"]["id"]

    verify_headers = {**headers, "Idempotency-Key": "verify-api"}
    verified = client.post(f"/internal/topic-score-snapshots/{snapshot_id}:verify", headers=verify_headers)
    assert verified.status_code == 200
    assert verified.json()["data"]["verified"] is True
    replay = client.post(
        f"/internal/topic-score-snapshots/{snapshot_id}:verify",
        headers={**verify_headers, "X-Trace-Id": "replay-trace"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"] == verified.json()["data"]

    denied = client.post(
        f"/internal/topic-score-snapshots/{snapshot_id}:verify",
        headers={"X-Org-Id": other_org, "X-Actor-Id": actor_id, "Idempotency-Key": "verify-other"},
    )
    assert denied.status_code == 403
    opportunities.close()
    signals.close()
