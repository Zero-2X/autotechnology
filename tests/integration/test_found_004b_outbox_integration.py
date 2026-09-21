from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from infra.foundation.outbox import (
    EventEnvelope,
    OutboxDispatcher,
    OutboxPublishError,
    OutboxStore,
    PublishResult,
    TenantScopeViolation,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "packages/db/migrations/versions/20260916_found_004b_outbox.py"


def _event(org_id: str, key: str) -> EventEnvelope:
    return EventEnvelope.create(
        event_type="content.updated",
        event_schema_version=1,
        occurred_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        org_id=org_id,
        trace_id=f"trace-{key}",
        aggregate_type="Content",
        aggregate_id=str(uuid4()),
        aggregate_version=1,
        actor_type="worker",
        actor_id=None,
        idempotency_key=key,
        payload={"key": key},
    )


def _store(synthetic_database_connection):
    # Execute the revision's upgrade function against the existing SQLite fixture.
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import importlib.util
    import sqlalchemy as sa

    spec = importlib.util.spec_from_file_location("found_004b", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:", poolclass=sa.pool.StaticPool)
    sqlalchemy_connection = engine.connect()
    context = MigrationContext.configure(sqlalchemy_connection)
    operations = Operations(context)
    original_op = module.op
    module.op = operations
    try:
        module.upgrade()
    finally:
        module.op = original_op
    raw_connection = sqlalchemy_connection.connection.driver_connection
    store = OutboxStore(raw_connection, max_attempts=2, lease_seconds=5, retry_base_seconds=1)
    store._keepalive = (sqlalchemy_connection, engine)  # type: ignore[attr-defined]
    return store


def test_dispatcher_retry_dead_letter_and_lease_recovery(synthetic_database_connection) -> None:
    store = _store(synthetic_database_connection)
    org_id = str(uuid4())
    first = store.append(_event(org_id, "retry"), available_at=datetime(2026, 9, 16, tzinfo=timezone.utc))

    class FlakyPublisher:
        calls = 0

        def publish(self, envelope):
            self.calls += 1
            if self.calls == 1:
                raise OutboxPublishError("temporary downstream unavailable")
            return PublishResult()

    publisher = FlakyPublisher()
    dispatcher = OutboxDispatcher(store, publisher)
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    failed = dispatcher.dispatch_once(worker_id="worker-1", org_id=org_id, now=now)
    assert failed[0].status == "failed"
    assert failed[0].code == "OUTBOX_PUBLISH_RETRYABLE"
    retried = dispatcher.dispatch_once(worker_id="worker-1", org_id=org_id, now=now + timedelta(seconds=2))
    assert retried[0].status == "published"
    assert publisher.calls == 2

    second = store.append(_event(org_id, "lease"), available_at=now)
    store.connection.commit()
    claimed = store.claim(worker_id="crashed-worker", now=now, limit=1, org_id=org_id)
    assert claimed[0].event_id == second.event_id
    recovered = store.claim(worker_id="recovery-worker", now=now + timedelta(seconds=6), limit=1, org_id=org_id)
    assert recovered[0].event_id == second.event_id
    assert recovered[0].locked_by == "recovery-worker"


def test_unknown_publish_result_preserves_lease_for_manual_reconciliation(synthetic_database_connection) -> None:
    store = _store(synthetic_database_connection)
    org_id = str(uuid4())
    store.append(_event(org_id, "unknown"), available_at=datetime(2026, 9, 16, tzinfo=timezone.utc))

    class UnknownPublisher:
        def publish(self, envelope):
            return PublishResult(status="unknown", message="provider acknowledgement unavailable")

    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    result = OutboxDispatcher(store, UnknownPublisher()).dispatch_once(
        worker_id="worker", org_id=org_id, now=now
    )
    assert result[0].status == "publishing"
    assert result[0].code == "OUTBOX_PUBLISH_UNKNOWN"
    assert store.connection.execute(
        "SELECT status, locked_by FROM outbox_events WHERE org_id = ?", (org_id,)
    ).fetchone() == ("publishing", "worker")


def test_dispatcher_terminal_error_dead_letters_without_network(synthetic_database_connection) -> None:
    store = _store(synthetic_database_connection)
    org_id = str(uuid4())
    store.append(_event(org_id, "terminal"), available_at=datetime(2026, 9, 16, tzinfo=timezone.utc))

    class TerminalPublisher:
        def publish(self, envelope):
            raise OutboxPublishError("poison event", retryable=False)

    result = OutboxDispatcher(store, TerminalPublisher()).dispatch_once(
        worker_id="worker", org_id=org_id, now=datetime(2026, 9, 16, tzinfo=timezone.utc)
    )
    assert result[0].status == "dead_letter"
    assert result[0].code == "OUTBOX_DEAD_LETTER"


def test_outbox_get_rejects_cross_tenant_access(synthetic_database_connection) -> None:
    store = _store(synthetic_database_connection)
    owner = str(uuid4())
    other = str(uuid4())
    event = store.append(_event(owner, "tenant"))
    try:
        store.get(event.event_id, org_id=other)
    except TenantScopeViolation as exc:
        assert exc.code == "TENANT_SCOPE_VIOLATION"
    else:  # pragma: no cover - assertion gives a clearer failure than pytest.raises here
        raise AssertionError("cross-tenant event access was not rejected")
