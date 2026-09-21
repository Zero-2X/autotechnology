import csv
from io import StringIO
from uuid import uuid4

import pytest

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


def test_mixed_rows_are_independent_and_rejections_emit_redacted_events() -> None:
    service = TopicSignalImportService()
    org_id, actor_id = uuid4(), uuid4()
    result = service.import_json(
        org_id=org_id, actor_id=actor_id, trace_id="trace-1", idempotency_key="topic-batch-1",
        rows=[signal_row(), {**signal_row(source_ref="bad"), "confidence": 1.2},
              signal_row(source_ref="publish", usage_rights_status="verified",
                         terms_snapshot_ref="terms:2026", permitted_use="editorial")],
    )
    assert (result["accepted"], result["rejected"], result["duplicate"]) == (2, 1, 0)
    assert [item["status"] for item in result["results"]] == ["accepted", "rejected", "accepted"]
    assert result["results"][1]["error_code"] == "INVALID_CONFIDENCE"
    assert len(service.list(org_id=org_id)) == 2
    assert [item["source_ref"] for item in service.list_publishable(org_id=org_id)] == ["publish"]
    event, = service.rejection_events(org_id=org_id)
    assert event["event_type"] == "topic_signal.rejected"
    assert event["payload"]["line_number"] == 2
    assert event["payload"]["reason_code"] == "INVALID_CONFIDENCE"
    assert event["trace_id"] == "trace-1" and event["actor_id"] == str(actor_id)
    assert "source_ref" not in str(event)
    service.close()


def test_duplicate_dedupe_key_and_tenant_scope() -> None:
    service = TopicSignalImportService()
    org_id, other_org, actor_id = uuid4(), uuid4(), uuid4()
    first = service.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="batch-one",
                                rows=[signal_row()])
    duplicate = service.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="batch-two",
                                    rows=[signal_row(title="New title")])
    assert duplicate["results"][0]["status"] == "duplicate"
    assert duplicate["results"][0]["signal_id"] == first["results"][0]["signal_id"]
    assert len(service.list(org_id=org_id)) == 1
    other = service.import_json(org_id=other_org, actor_id=actor_id, trace_id="trace", idempotency_key="batch-one",
                                rows=[signal_row()])
    assert other["results"][0]["signal_id"] != first["results"][0]["signal_id"]
    with pytest.raises(TopicSignalError) as error:
        service.get(org_id=other_org, signal_id=first["results"][0]["signal_id"])
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    service.close()


def test_invalid_rows_and_verified_rights_without_evidence_are_not_publishable() -> None:
    service = TopicSignalImportService()
    org_id, actor_id = uuid4(), uuid4()
    rows = [
        {key: value for key, value in signal_row().items() if key != "source_ref"},
        signal_row(source_ref="bad-time", captured_at="2026-09-18T08:00:00+08:00"),
        signal_row(source_ref="bad-evidence", usage_rights_status="verified", permitted_use="commercial"),
        signal_row(source_ref="restricted", usage_rights_status="restricted", permitted_use="commercial"),
        signal_row(source_ref="bad-type", source_type=[]),
        signal_row(source_ref="bad-json-number", confidence="0.7"),
    ]
    result = service.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="batch-invalid",
                                 rows=rows)
    assert [item["error_code"] for item in result["results"]] == [
        "MISSING_REQUIRED_FIELD", "INVALID_CAPTURED_AT", "RIGHTS_EVIDENCE_REQUIRED", None,
        "INVALID_SOURCE_TYPE", "INVALID_CONFIDENCE",
    ]
    assert result["accepted"] == 1 and result["rejected"] == 5
    assert service.list_publishable(org_id=org_id) == ()
    assert len(service.rejection_events(org_id=org_id)) == 5
    service.close()


def test_csv_import_uses_physical_line_numbers_and_limits_batch() -> None:
    service = TopicSignalImportService()
    org_id, actor_id = uuid4(), uuid4()
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(signal_row()))
    writer.writeheader()
    writer.writerow(signal_row(source_ref="csv:1", terms_snapshot_ref="", license_ref=""))
    writer.writerow(signal_row(source_ref="csv:2", captured_at="bad", terms_snapshot_ref="", license_ref=""))
    result = service.import_csv(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="batch-csv",
                                content=buffer.getvalue().encode())
    assert [item["line_number"] for item in result["results"]] == [2, 3]
    assert [item["status"] for item in result["results"]] == ["accepted", "rejected"]
    with pytest.raises(TopicSignalError) as error:
        service.import_json(org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="batch-big",
                            rows=[signal_row()] * 1001)
    assert error.value.code == "BATCH_TOO_LARGE"
    service.close()
