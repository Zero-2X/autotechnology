"""SQLite storage for tenant-scoped Sources and immutable SourceSnapshots."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS sources ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, source_type TEXT NOT NULL, "
        "fetch_method TEXT NOT NULL, canonical_url TEXT, status TEXT NOT NULL, "
        "current_snapshot_id TEXT, confidence REAL NOT NULL, version INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), UNIQUE(org_id, canonical_url))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS source_snapshots ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, source_id TEXT NOT NULL, "
        "captured_at TEXT NOT NULL, content_hash TEXT NOT NULL, storage_object_ref TEXT NOT NULL, "
        "terms_snapshot_ref TEXT, confidence REAL NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), "
        "FOREIGN KEY(org_id, source_id) REFERENCES sources(org_id, id), "
        "CHECK(length(content_hash) = 64), CHECK(storage_object_ref LIKE 'private://%'), "
        "CHECK(confidence >= 0 AND confidence <= 1))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_source_snapshots_current ON "
        "source_snapshots(org_id, source_id, version, status)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS source_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS source_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, "
        "aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, sequence INTEGER NOT NULL, envelope TEXT NOT NULL, "
        "UNIQUE(org_id, aggregate_type, aggregate_id, sequence))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS source_snapshot_state_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, snapshot_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, sequence INTEGER NOT NULL, envelope TEXT NOT NULL, "
        "UNIQUE(org_id, snapshot_id, sequence), "
        "FOREIGN KEY(org_id, snapshot_id) REFERENCES source_snapshots(org_id, id))"
    )
    for table in ("source_commands", "source_events", "source_snapshot_state_events"):
        for action in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                f"BEFORE {action} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS source_snapshots_no_{action.lower()} "
            f"BEFORE {action} ON source_snapshots "
            + (
                "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.source_id != OLD.source_id "
                "OR NEW.captured_at != OLD.captured_at OR NEW.content_hash != OLD.content_hash "
                "OR NEW.storage_object_ref != OLD.storage_object_ref "
                "OR NEW.terms_snapshot_ref IS NOT OLD.terms_snapshot_ref "
                "OR NEW.confidence != OLD.confidence OR NEW.created_at != OLD.created_at "
                if action == "UPDATE" else ""
            )
            + "BEGIN SELECT RAISE(ABORT, 'source snapshots are immutable'); END"
        )
    connection.commit()
