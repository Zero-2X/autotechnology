"""SQLite persistence for rights guard decisions, reminders, and lineage."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_guard_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key), CHECK(length(payload_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_guard_decisions ("
        "decision_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, rights_record_version_id TEXT NOT NULL, "
        "decision TEXT NOT NULL, reason_codes TEXT NOT NULL, requested_scope TEXT NOT NULL, "
        "checked_at TEXT NOT NULL, envelope TEXT NOT NULL, "
        "UNIQUE(org_id, rights_record_version_id, checked_at, decision), "
        "FOREIGN KEY(org_id, rights_record_version_id) REFERENCES rights_record_versions(org_id, id), "
        "CHECK(decision IN ('allowed', 'blocked')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_expiry_reminders ("
        "reminder_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, rights_record_version_id TEXT NOT NULL, "
        "valid_to TEXT NOT NULL, remind_at TEXT NOT NULL, status TEXT NOT NULL, "
        "idempotency_key TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, rights_record_version_id, remind_at), "
        "FOREIGN KEY(org_id, rights_record_version_id) REFERENCES rights_record_versions(org_id, id), "
        "CHECK(status IN ('scheduled', 'acknowledged', 'cancelled')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_lineage_edges ("
        "edge_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, rights_record_version_id TEXT NOT NULL, "
        "parent_derived_type TEXT, parent_derived_id TEXT, derived_type TEXT NOT NULL, "
        "derived_id TEXT NOT NULL, relation TEXT NOT NULL, created_by TEXT NOT NULL, "
        "created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, edge_id), UNIQUE(org_id, rights_record_version_id, derived_type, derived_id), "
        "FOREIGN KEY(org_id, rights_record_version_id) REFERENCES rights_record_versions(org_id, id), "
        "UNIQUE(org_id, derived_type, derived_id, parent_derived_type, parent_derived_id))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_rights_lineage_parent ON rights_lineage_edges "
        "(org_id, parent_derived_type, parent_derived_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_rights_lineage_rights ON rights_lineage_edges "
        "(org_id, rights_record_version_id, derived_type, derived_id)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_derivative_blocks ("
        "block_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, edge_id TEXT NOT NULL, "
        "rights_record_version_id TEXT NOT NULL, reason TEXT NOT NULL, source_event_id TEXT, "
        "blocked_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, edge_id, reason), "
        "FOREIGN KEY(org_id, edge_id) REFERENCES rights_lineage_edges(org_id, edge_id))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_rights_blocks_org_version ON rights_derivative_blocks "
        "(org_id, rights_record_version_id, blocked_at)"
    )
    for table in ("rights_guard_commands", "rights_guard_decisions", "rights_expiry_reminders",
                  "rights_lineage_edges", "rights_derivative_blocks"):
        for action in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                f"BEFORE {action} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    connection.commit()
