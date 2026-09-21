import json
import sqlite3
from pathlib import Path
from urllib.parse import urljoin
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from modules.provenance import SourceError, SourceService


def _ingest(service: SourceService, *, org_id=None, actor_id=None, key="source-ingest", content=None):
    return service.ingest(
        org_id=org_id or uuid4(),
        actor_id=actor_id or uuid4(),
        trace_id="trace-source",
        idempotency_key=key,
        source_type="url",
        fetch_method="url",
        canonical_url=f"https://example.test/{key}",
        content=content if content is not None else {"title": "private source"},
        confidence=0.87,
    )


def test_ingest_hashes_content_keeps_storage_private_and_replays_idempotently() -> None:
    service = SourceService()
    org_id, actor_id = uuid4(), uuid4()
    first = _ingest(service, org_id=org_id, actor_id=actor_id, key="source-ingest-1", content="原文内容")
    replay = _ingest(service, org_id=org_id, actor_id=actor_id, key="source-ingest-1", content="原文内容")

    assert replay == first
    snapshot = first["snapshot"]
    assert len(snapshot["content_hash"]) == 64
    assert snapshot["storage_object_ref"].startswith("private://")
    assert "原文内容" not in json.dumps(service._connection.execute(
        "SELECT payload FROM source_snapshots WHERE id = ?", (snapshot["id"],)
    ).fetchone()[0], ensure_ascii=False)
    assert service.verify_snapshot(
        org_id=org_id, snapshot_id=snapshot["id"], content="原文内容", actor_id=actor_id,
        trace_id="trace-verify", idempotency_key="source-verify-1",
    )["verified"] is True
    with pytest.raises(SourceError) as error:
        _ingest(service, org_id=org_id, actor_id=actor_id, key="source-ingest-1", content="changed")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"
    service.close()


def test_snapshot_state_machine_uses_optimistic_versions_and_requires_terminal_reasons() -> None:
    service = SourceService()
    org_id, actor_id = uuid4(), uuid4()
    created = _ingest(service, org_id=org_id, actor_id=actor_id, key="source-state-1")
    snapshot_id = created["snapshot"]["id"]

    quarantined = service.transition_snapshot(
        org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
        idempotency_key="source-state-2", action="quarantine", expected_version=0,
    )
    usable = service.transition_snapshot(
        org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
        idempotency_key="source-state-3", action="mark_usable", expected_version=1,
    )
    expired = service.transition_snapshot(
        org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
        idempotency_key="source-state-4", action="expire", expected_version=2, reason="stale terms",
    )
    assert quarantined["snapshot"]["status"] == "quarantined"
    assert usable["snapshot"]["status"] == "usable"
    assert expired["snapshot"]["status"] == "expired"
    assert expired["snapshot"]["status"] == service.get_snapshot(org_id=org_id, snapshot_id=snapshot_id)["status"]
    with pytest.raises(SourceError) as error:
        service.transition_snapshot(
            org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
            idempotency_key="source-state-stale", action="revoke", expected_version=2, reason="stale",
        )
    assert error.value.code == "VERSION_CONFLICT"
    with pytest.raises(SourceError) as error:
        service.transition_snapshot(
            org_id=org_id, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
            idempotency_key="source-state-no-reason", action="block", expected_version=3,
        )
    assert error.value.code == "REASON_REQUIRED"
    service.close()


def test_tenant_scope_append_only_and_immutable_snapshot_guards() -> None:
    service = SourceService()
    org_id, actor_id, other_org = uuid4(), uuid4(), uuid4()
    created = _ingest(service, org_id=org_id, actor_id=actor_id, key="source-guard-1")
    source_id, snapshot_id = created["source"]["id"], created["snapshot"]["id"]
    with pytest.raises(SourceError) as error:
        service.get_source(org_id=other_org, source_id=source_id)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(SourceError) as error:
        service.transition_snapshot(
            org_id=other_org, snapshot_id=snapshot_id, actor_id=actor_id, trace_id="trace",
            idempotency_key="source-guard-2", action="quarantine", expected_version=0,
        )
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(sqlite3.DatabaseError):
        service._connection.execute(
            "UPDATE source_snapshots SET content_hash = ? WHERE id = ?",
            ("0" * 64, snapshot_id),
        )
    service._connection.rollback()
    event_id = created["event"]["event_id"]
    with pytest.raises(sqlite3.DatabaseError):
        service._connection.execute("DELETE FROM source_events WHERE event_id = ?", (event_id,))
    service._connection.rollback()
    service.close()


def test_event_envelopes_validate_against_registered_source_event_schemas() -> None:
    root = Path(__file__).resolve().parents[3]
    envelope = json.loads((root / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
    event_files = {
        "source.ingested": "source-ingested.schema.json",
        "source.snapshot.quarantined": "source-snapshot-quarantined.schema.json",
        "source.snapshot.usable": "source-snapshot-usable.schema.json",
    }
    registry = Registry().with_resource(envelope["$id"], Resource.from_contents(envelope))
    # Event schemas use a relative reference under ``events/`` while the
    # shared envelope keeps its canonical top-level URI; register both forms.
    registry = registry.with_resource(
        "https://schemas.ai-content-workflow.local/events/event-envelope.schema.json",
        Resource.from_contents(envelope),
    )
    for filename in event_files.values():
        schema = json.loads((root / "packages/contracts/events" / filename).read_text(encoding="utf-8"))
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    service = SourceService()
    org_id, actor_id = uuid4(), uuid4()
    created = _ingest(service, org_id=org_id, actor_id=actor_id, key="source-event-1")
    quarantined = service.transition_snapshot(
        org_id=org_id, snapshot_id=created["snapshot"]["id"], actor_id=actor_id, trace_id="trace",
        idempotency_key="source-event-2", action="quarantine", expected_version=0,
    )
    usable = service.transition_snapshot(
        org_id=org_id, snapshot_id=created["snapshot"]["id"], actor_id=actor_id, trace_id="trace",
        idempotency_key="source-event-3", action="mark_usable", expected_version=1,
    )
    for event in (created["event"], quarantined["event"], usable["event"]):
        schema = json.loads((root / "packages/contracts/events" / (
            event["event_type"].replace(".", "-") + ".schema.json"
        )).read_text(encoding="utf-8"))
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(event)
    service.close()
