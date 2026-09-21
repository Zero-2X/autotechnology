from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "docs/tasks/FOUND-004B.md"
OUTBOX_SCHEMA = ROOT / "packages/contracts/jsonschema/outbox-event.schema.json"
ENVELOPE_SCHEMA = ROOT / "packages/contracts/events/event-envelope.schema.json"
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_004b_outbox.py"


def _event(*, org_id: str, key: str = "command-1", payload: dict | None = None):
    from datetime import datetime, timezone

    from infra.foundation.outbox import EventEnvelope

    return EventEnvelope.create(
        event_type="content.updated",
        event_schema_version=1,
        occurred_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        org_id=org_id,
        trace_id=f"trace-{key}",
        aggregate_type="Content",
        aggregate_id=str(uuid4()),
        aggregate_version=1,
        actor_type="service",
        actor_id=None,
        idempotency_key=key,
        payload=payload or {"state": "ready"},
    )


def _migrated_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from alembic import command
    from alembic.config import Config
    import sqlite3

    database = tmp_path / "outbox.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return sqlite3.connect(database)


def test_outbox_contract_and_task_card_are_explicit() -> None:
    schema = json.loads(OUTBOX_SCHEMA.read_text(encoding="utf-8"))
    envelope = json.loads(ENVELOPE_SCHEMA.read_text(encoding="utf-8"))
    task = TASK.read_text(encoding="utf-8")
    assert set(schema["required"]) == {
        "event_id", "event_type", "event_schema_version", "occurred_at", "org_id", "trace_id",
        "correlation_id", "causation_id", "aggregate_type", "aggregate_id", "aggregate_version",
        "actor_type", "actor_id", "idempotency_key", "payload", "payload_hash", "published_at",
        "attempt_count", "last_error", "status", "available_at", "lease_until", "locked_by",
    }
    assert set(envelope["required"]) >= {
        "event_id", "event_type", "event_schema_version", "trace_id", "org_id", "occurred_at",
        "aggregate_type", "aggregate_id", "aggregate_version", "payload_hash",
    }
    assert "same database transaction" in task or "同一个 `BEGIN/COMMIT` 边界" in task
    assert "20260916_found_004b_outbox.py" in task


def test_event_envelope_is_deterministic_and_rejects_invalid_input() -> None:
    from datetime import datetime, timezone

    from infra.foundation.outbox import EventEnvelope, OutboxValidationError

    org_id = str(uuid4())
    event = _event(org_id=org_id)
    assert event.as_contract()["payload_hash"] == event.payload_hash
    assert len(event.payload_hash) == 64
    assert event.as_contract()["event_id"] == event.event_id
    with pytest.raises(OutboxValidationError):
        EventEnvelope.create(
            event_type="INVALID TYPE",
            event_schema_version=1,
            occurred_at=datetime.now(timezone.utc),
            org_id=org_id,
            trace_id="trace",
            aggregate_type="Content",
            aggregate_id=str(uuid4()),
            aggregate_version=1,
            actor_type="service",
            idempotency_key="key",
            payload={},
        )

    assert json.loads(OUTBOX_SCHEMA.read_text(encoding="utf-8"))["properties"]["payload"]["additionalProperties"] is True


def test_transactional_state_and_outbox_commit_or_rollback_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.foundation.outbox import OutboxStore

    connection = _migrated_connection(tmp_path, monkeypatch)
    store = OutboxStore(connection)
    org_id = str(uuid4())
    aggregate_id = str(uuid4())
    event = _event(org_id=org_id)

    def write_state(db) -> None:
        db.execute(
            "INSERT INTO business_states VALUES (?, ?, ?, ?, ?, ?, ?)",
            (org_id, "Content", aggregate_id, 1, "ready", '{"ok":true}', event.occurred_at),
        )

    committed = store.commit_state_and_event(write_state, event)
    assert committed.status == "pending"
    assert connection.execute("SELECT COUNT(*) FROM business_states").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM outbox_events").fetchone()[0] == 1

    failing_event = _event(org_id=org_id, key="failing")

    def fail_after_state(db) -> None:
        db.execute(
            "UPDATE business_states SET state = 'broken' WHERE org_id = ?",
            (org_id,),
        )
        raise RuntimeError("synthetic state failure")

    with pytest.raises(RuntimeError):
        store.commit_state_and_event(fail_after_state, failing_event)
    assert connection.execute("SELECT state FROM business_states WHERE org_id = ?", (org_id,)).fetchone()[0] == "ready"
    assert connection.execute("SELECT COUNT(*) FROM outbox_events WHERE idempotency_key = 'failing'").fetchone()[0] == 0


def test_outbox_idempotency_and_duplicate_event_id_are_distinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infra.foundation.outbox import IdempotencyKeyReusedError, OutboxDuplicateError, OutboxStore

    connection = _migrated_connection(tmp_path, monkeypatch)
    store = OutboxStore(connection)
    org_id = str(uuid4())
    first = store.append(_event(org_id=org_id, key="same", payload={"value": 1}))
    replay = store.append(_event(org_id=org_id, key="same", payload={"value": 1}))
    assert replay.event_id == first.event_id
    with pytest.raises(IdempotencyKeyReusedError):
        store.append(_event(org_id=org_id, key="same", payload={"value": 2}))
    with pytest.raises(OutboxDuplicateError):
        store.append(_event(org_id=org_id, key="different", payload={"value": 1}).__class__(**{**first.envelope.__dict__}))


def test_dispatcher_publishes_once_and_scopes_by_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from infra.foundation.outbox import OutboxDispatcher, OutboxStore

    connection = _migrated_connection(tmp_path, monkeypatch)
    store = OutboxStore(connection)
    org_a, org_b = str(uuid4()), str(uuid4())
    available_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
    first = store.append(_event(org_id=org_a, key="a"), available_at=available_at)
    store.append(_event(org_id=org_b, key="b"), available_at=available_at)
    published: list[str] = []

    class Publisher:
        def publish(self, envelope):
            published.append(envelope.event_id)

    dispatcher = OutboxDispatcher(store, Publisher())
    result = dispatcher.dispatch_once(
        worker_id="worker-a", org_id=org_a, now=datetime(2026, 9, 16, tzinfo=timezone.utc)
    )
    assert result[0].status == "published"
    assert published == [first.event_id]
    assert dispatcher.dispatch_once(worker_id="worker-a", org_id=org_a)[0:1] == ()
    assert connection.execute("SELECT status FROM outbox_events WHERE event_id = ?", (first.event_id,)).fetchone()[0] == "published"


def test_outbox_publish_transition_checks_the_conditional_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone
    from unittest.mock import Mock

    from infra.foundation.outbox import OutboxLeaseLostError, OutboxStore

    connection = _migrated_connection(tmp_path, monkeypatch)
    store = OutboxStore(connection)
    event = store.append(
        _event(org_id=str(uuid4()), key="lost-lease"),
        available_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    connection.commit()
    claimed = store.claim(
        worker_id="worker-a", now=datetime(2026, 9, 16, tzinfo=timezone.utc)
    )[0]
    original_execute = store._execute

    def execute_with_lost_update(sql, parameters=()):
        if sql.startswith("UPDATE outbox_events SET status = 'published'"):
            return Mock(rowcount=0)
        return original_execute(sql, parameters)

    monkeypatch.setattr(store, "_execute", execute_with_lost_update)
    with pytest.raises(OutboxLeaseLostError):
        store.mark_published(
            event.event_id,
            worker_id="worker-a",
            now=datetime(2026, 9, 16, tzinfo=timezone.utc),
        )
    assert claimed.status == "publishing"


def test_internal_dispatch_command_is_worker_only_and_account_free() -> None:
    from fastapi.testclient import TestClient

    from apps.api.main import create_app

    client = TestClient(create_app())
    assert client.post("/internal/outbox/dispatch", json={}).status_code == 403
    response = client.post(
        "/internal/outbox/dispatch",
        headers={"X-Worker-Id": "worker"},
        json={"limit": 1},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "OUTBOX_NOT_CONFIGURED"


def test_found_004b_alembic_downgrade_removes_only_task_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alembic import command
    from alembic.config import Config
    import sqlalchemy as sa

    database = tmp_path / "outbox-downgrade.db"
    url = f"sqlite:///{database.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    command.downgrade(config, "20260916_found_004a")
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert not inspector.has_table("business_states")
        assert not inspector.has_table("outbox_events")
        assert inspector.has_table("migration_framework_baselines")
