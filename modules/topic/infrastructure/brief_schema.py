"""Tables for versioned, tenant-scoped TopicBrief records and commands."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_briefs ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, opportunity_id TEXT NOT NULL, "
        "version_no INTEGER NOT NULL, status TEXT NOT NULL, lock_hash TEXT, "
        "input_snapshot_hash TEXT, locked_at TEXT, locked_by TEXT, supersedes_version_id TEXT, "
        "created_by TEXT, created_at TEXT, payload TEXT NOT NULL, "
        "UNIQUE(org_id, opportunity_id, version_no), "
        "CHECK(status IN ('draft', 'locked', 'approved', 'superseded', 'cancelled')), "
        "FOREIGN KEY(org_id, opportunity_id) REFERENCES topic_opportunities(org_id, id))"
    )
    # Keep locally persisted fixtures created by TOPIC-004 readable while the
    # expanded version columns roll out. New writes always populate them.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(topic_briefs)").fetchall()}
    for name, declaration in (
        ("input_snapshot_hash", "TEXT"), ("locked_at", "TEXT"), ("locked_by", "TEXT"),
        ("supersedes_version_id", "TEXT"), ("created_by", "TEXT"), ("created_at", "TEXT"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE topic_briefs ADD COLUMN {name} {declaration}")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_topic_briefs_current ON "
        "topic_briefs(org_id, opportunity_id, version_no, status)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_brief_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_brief_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, event_type TEXT NOT NULL, envelope TEXT NOT NULL)"
    )
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS topic_brief_events_no_{action.lower()} "
            f"BEFORE {action} ON topic_brief_events BEGIN "
            "SELECT RAISE(ABORT, 'topic brief events are append-only'); END"
        )
    for action in ("UPDATE", "DELETE"):
        condition = (
            "WHEN OLD.status IN ('locked', 'approved', 'superseded') "
            "AND NOT (OLD.status IN ('locked', 'approved') AND NEW.status = 'superseded') "
            if action == "UPDATE" else
            "WHEN OLD.status IN ('locked', 'approved', 'superseded') "
        )
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS topic_briefs_immutable_{action.lower()} "
            f"BEFORE {action} ON topic_briefs {condition} "
            "BEGIN SELECT RAISE(ABORT, 'approved topic brief versions are immutable'); END"
        )
    connection.commit()
