"""SQLite storage for tenant-scoped signal imports and rejection events."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_signals ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, dedupe_key TEXT NOT NULL, "
        "usage_rights_status TEXT NOT NULL, permitted_use TEXT NOT NULL, "
        "terms_snapshot_ref TEXT, license_ref TEXT, payload TEXT NOT NULL, "
        "UNIQUE(org_id, dedupe_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_signal_imports ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, policy_snapshot_ref TEXT NOT NULL, "
        "duration_ms INTEGER NOT NULL, cost_usd TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_signal_events ("
        "event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, org_id TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL, envelope TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_topic_signal_events_org ON topic_signal_events(org_id, idempotency_key)"
    )
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS topic_signal_events_no_{action.lower()} "
            f"BEFORE {action} ON topic_signal_events BEGIN "
            "SELECT RAISE(ABORT, 'topic signal events are append-only'); END"
        )
    connection.commit()
