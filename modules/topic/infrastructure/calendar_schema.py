"""SQLite tables for versioned editorial calendar assignments."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_editorial_plans ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, "
        "version_no INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, opportunity_id, version_no), "
        "FOREIGN KEY(org_id, opportunity_id) REFERENCES topic_opportunities(org_id, id))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_topic_editorial_plans_current ON "
        "topic_editorial_plans(org_id, opportunity_id, version_no, status)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_editorial_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_editorial_audit ("
        "audit_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, occurred_at TEXT NOT NULL, audit_seq INTEGER NOT NULL, envelope TEXT NOT NULL)"
    )
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS topic_editorial_audit_no_{action.lower()} "
            f"BEFORE {action} ON topic_editorial_audit BEGIN "
            "SELECT RAISE(ABORT, 'editorial calendar audit is append-only'); END"
        )
    connection.commit()
