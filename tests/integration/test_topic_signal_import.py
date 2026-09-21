import csv
from io import StringIO
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from apps.api.main import create_app
from modules.topic import TopicSignalError, TopicSignalImportService


def signal_row(**changes):
    row = {
        "source_type": "manual", "source_ref": "note:1", "captured_at": "2026-09-18T00:00:00Z",
        "locale": "en-US", "region": "US", "title": "RAG question", "summary": "A customer question",
        "usage_rights_status": "unknown", "terms_snapshot_ref": None, "license_ref": None,
        "permitted_use": "research", "confidence": 0.75,
    }
    row.update(changes)
    return row


def test_import_result_and_rejection_event_survive_restart(tmp_path) -> None:
    database = tmp_path / "topic-signals.db"
    org_id, actor_id = uuid4(), uuid4()
    first = TopicSignalImportService(database)
    rows = [signal_row(source_ref="one"), signal_row(source_ref="invalid", confidence=-1)]
    result = first.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace-1",
                               idempotency_key="batch-restart", rows=rows)
    first.close()

    reopened = TopicSignalImportService(database)
    assert reopened.import_json(org_id=org_id, actor_id=actor_id, trace_id="new-trace",
                                idempotency_key="batch-restart", rows=rows) == result
    assert len(reopened.list(org_id=org_id)) == 1
    event, = reopened.rejection_events(org_id=org_id)
    root = Path(__file__).resolve().parents[2]
    signal_schema = json.loads((root / "packages/contracts/jsonschema/topic-signal.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(signal_schema, format_checker=FormatChecker()).validate(reopened.list(org_id=org_id)[0])
    envelope_schema = json.loads((root / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
    rejected_schema = json.loads((root / "packages/contracts/events/topic-signal-rejected.schema.json").read_text(encoding="utf-8"))
    envelope_uri = rejected_schema["$id"].rsplit("/", 1)[0] + "/event-envelope.schema.json"
    registry = Registry().with_resource(envelope_uri, Resource.from_contents(envelope_schema))
    Draft202012Validator(rejected_schema, registry=registry, format_checker=FormatChecker()).validate(event)
    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM topic_signal_events WHERE event_id = ?", (event["event_id"],))
    with pytest.raises(TopicSignalError) as error:
        reopened.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace-1",
                             idempotency_key="batch-restart", rows=[signal_row(source_ref="changed")])
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    reopened.close()


def test_json_and_csv_api_require_tenant_and_idempotency_context(tmp_path) -> None:
    service = TopicSignalImportService(tmp_path / "api.db")
    client = TestClient(create_app(topic_signal_service=service))
    org_id, actor_id = str(uuid4()), str(uuid4())
    headers = {"X-Org-Id": org_id, "X-Actor-Id": actor_id, "Idempotency-Key": "topic-api-1",
               "X-Trace-Id": "trace-api-1"}
    response = client.post("/internal/topic-signals:import", headers=headers, json=[signal_row()])
    assert response.status_code == 202
    assert response.json()["data"]["accepted"] == 1
    assert response.json()["trace_id"] == "trace-api-1"
    replay = client.post("/v1/topic-signals", headers=headers, json=[signal_row()])
    assert replay.json()["data"] == response.json()["data"]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(signal_row()))
    writer.writeheader()
    writer.writerow(signal_row(source_ref="csv-api", terms_snapshot_ref="", license_ref=""))
    csv_response = client.post("/internal/topic-signals:import",
                               headers={**headers, "Idempotency-Key": "topic-api-csv", "Content-Type": "text/csv"},
                               content=buffer.getvalue())
    assert csv_response.status_code == 202
    assert csv_response.json()["data"]["results"][0]["line_number"] == 2
    missing_actor = client.post("/internal/topic-signals:import", headers={"X-Org-Id": org_id,
                                "Idempotency-Key": "topic-api-2"}, json=[signal_row()])
    assert missing_actor.status_code == 400
    conflict = client.post("/internal/topic-signals:import", headers=headers,
                           json=[signal_row(source_ref="changed")])
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    service.close()
