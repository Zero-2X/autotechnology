"""SQLite persistence primitives owned by the canonical_content module."""

from __future__ import annotations


def _append_only(connection, table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
            f"BEFORE {action} ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def initialize(connection) -> None:
    """Create the local canonical write model.

    The service is also used in isolated unit tests before the provenance or
    topic schemas are installed.  References to those aggregates are therefore
    checked by the service and are deliberately not hard SQLite foreign keys in
    this bootstrap schema.  The Alembic revision adds the same tenant-scoped
    columns and constraints for a real database.
    """
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_contents ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, topic_brief_id TEXT NOT NULL, "
        "stable_key TEXT NOT NULL, current_version_id TEXT, status TEXT NOT NULL, "
        "created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "payload TEXT NOT NULL, UNIQUE(org_id, id), UNIQUE(org_id, stable_key), "
        "CHECK(status IN ('draft', 'in_review', 'approved', 'archived')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_content_versions ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_content_id TEXT NOT NULL, "
        "topic_brief_id TEXT NOT NULL, version_no INTEGER NOT NULL, title TEXT NOT NULL, "
        "abstract TEXT NOT NULL, sections_json TEXT NOT NULL, claims_json TEXT NOT NULL, "
        "code_blocks_json TEXT NOT NULL, examples_json TEXT NOT NULL, limitations_json TEXT NOT NULL, "
        "source_snapshot_refs_json TEXT NOT NULL, knowledge_core_version_id TEXT, "
        "topic_brief_status TEXT NOT NULL DEFAULT 'approved', topic_brief_lock_hash TEXT, "
        "input_snapshot_hash TEXT NOT NULL, content_hash TEXT NOT NULL, rights_snapshot_ids_json TEXT NOT NULL, "
        "supersedes_version_id TEXT, freshness_status TEXT NOT NULL DEFAULT 'fresh', "
        "freshness_checked_at TEXT, freshness_expires_at TEXT, conflict_set_ids_json TEXT NOT NULL DEFAULT '[]', "
        "refresh_required INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
        "payload TEXT NOT NULL, UNIQUE(org_id, id), UNIQUE(org_id, canonical_content_id, version_no), "
        "CHECK(version_no >= 1), CHECK(status IN ('draft', 'evidence_pending', 'fact_checked', 'approved', 'superseded', 'withdrawn')), "
        "CHECK(length(input_snapshot_hash) = 64), CHECK(length(content_hash) = 64), "
        "FOREIGN KEY(org_id, canonical_content_id) REFERENCES canonical_contents(org_id, id))"
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(canonical_content_versions)").fetchall()}
    for name, declaration in (("topic_brief_status", "TEXT NOT NULL DEFAULT 'approved'"), ("topic_brief_lock_hash", "TEXT")):
        if name not in columns:
            connection.execute(f"ALTER TABLE canonical_content_versions ADD COLUMN {name} {declaration}")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(canonical_content_versions)").fetchall()}
    for name, declaration in (
        ("freshness_status", "TEXT NOT NULL DEFAULT 'fresh'"),
        ("freshness_checked_at", "TEXT"),
        ("freshness_expires_at", "TEXT"),
        ("conflict_set_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("refresh_required", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in columns:
            connection.execute(f"ALTER TABLE canonical_content_versions ADD COLUMN {name} {declaration}")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_claims ("
        "org_id TEXT NOT NULL, canonical_content_version_id TEXT NOT NULL, claim_key TEXT NOT NULL, "
        "claim_id TEXT, priority TEXT NOT NULL DEFAULT 'normal', evidence_ids_json TEXT NOT NULL DEFAULT '[]', "
        "rights_snapshot_ids_json TEXT NOT NULL DEFAULT '[]', position INTEGER NOT NULL, claim_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
        "PRIMARY KEY(org_id, canonical_content_version_id, claim_key), "
        "FOREIGN KEY(org_id, canonical_content_version_id) REFERENCES canonical_content_versions(org_id, id), "
        "CHECK(position >= 1), CHECK(priority IN ('low', 'normal', 'high', 'urgent')))"
    )
    claim_columns = {row[1] for row in connection.execute("PRAGMA table_info(canonical_claims)").fetchall()}
    for name, declaration in (
        ("claim_id", "TEXT"), ("priority", "TEXT NOT NULL DEFAULT 'normal'"),
        ("evidence_ids_json", "TEXT NOT NULL DEFAULT '[]'"), ("rights_snapshot_ids_json", "TEXT NOT NULL DEFAULT '[]'"),
    ):
        if name not in claim_columns:
            connection.execute(f"ALTER TABLE canonical_claims ADD COLUMN {name} {declaration}")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_content_version_diffs ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_content_id TEXT NOT NULL, "
        "from_version_id TEXT NOT NULL, to_version_id TEXT NOT NULL, diff_hash TEXT NOT NULL, "
        "created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, canonical_content_id, from_version_id, to_version_id), "
        "CHECK(length(diff_hash) = 64), "
        "FOREIGN KEY(org_id, canonical_content_id) REFERENCES canonical_contents(org_id, id), "
        "FOREIGN KEY(org_id, from_version_id) REFERENCES canonical_content_versions(org_id, id), "
        "FOREIGN KEY(org_id, to_version_id) REFERENCES canonical_content_versions(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key), CHECK(length(payload_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, "
        "aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, sequence INTEGER NOT NULL, envelope TEXT NOT NULL, "
        "UNIQUE(org_id, aggregate_type, aggregate_id, sequence))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_freshness_checks ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_content_id TEXT NOT NULL, "
        "canonical_content_version_id TEXT NOT NULL, freshness_status TEXT NOT NULL, "
        "checked_at TEXT NOT NULL, expires_at TEXT, conflict_set_ids_json TEXT NOT NULL, "
        "reason TEXT NOT NULL, created_by TEXT NOT NULL, trace_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), CHECK(freshness_status IN ('fresh', 'review_due', 'stale', 'expired', 'conflict', 'withdrawn')), "
        "FOREIGN KEY(org_id, canonical_content_id) REFERENCES canonical_contents(org_id, id), "
        "FOREIGN KEY(org_id, canonical_content_version_id) REFERENCES canonical_content_versions(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_refresh_queue ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_content_id TEXT NOT NULL, "
        "canonical_content_version_id TEXT NOT NULL, reason TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 50, "
        "status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL, "
        "lease_owner TEXT, lease_until TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), CHECK(status IN ('queued', 'claimed', 'completed', 'cancelled')), CHECK(priority BETWEEN 0 AND 100), CHECK(attempts >= 0), "
        "FOREIGN KEY(org_id, canonical_content_id) REFERENCES canonical_contents(org_id, id), "
        "FOREIGN KEY(org_id, canonical_content_version_id) REFERENCES canonical_content_versions(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS canonical_lineage_queries ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
        "request_hash TEXT NOT NULL, query_hash TEXT NOT NULL, subject_type TEXT NOT NULL, "
        "subject_id TEXT NOT NULL, actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, "
        "created_at TEXT NOT NULL, response TEXT NOT NULL, "
        "UNIQUE(org_id, idempotency_key), CHECK(length(request_hash) = 64), "
        "CHECK(length(query_hash) = 64), CHECK(subject_type IN ('canonical_content', 'canonical_content_version')))"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_contents_org_status ON canonical_contents(org_id, status, updated_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_versions_current ON canonical_content_versions(org_id, canonical_content_id, version_no, status)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_claims_version ON canonical_claims(org_id, canonical_content_version_id, position)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_claims_claim ON canonical_claims(org_id, claim_id, canonical_content_version_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_diffs_root ON canonical_content_version_diffs(org_id, canonical_content_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_events_aggregate ON canonical_events(org_id, aggregate_type, aggregate_id, sequence)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_freshness_version ON canonical_freshness_checks(org_id, canonical_content_version_id, checked_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_refresh_queue_ready ON canonical_refresh_queue(org_id, status, available_at, priority)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_canonical_lineage_subject ON canonical_lineage_queries(org_id, subject_type, subject_id, created_at)")
    for table in ("canonical_content_versions", "canonical_claims", "canonical_content_version_diffs", "canonical_commands", "canonical_events", "canonical_freshness_checks", "canonical_lineage_queries"):
        _append_only(connection, table)
    # A root can advance its status and current pointer, but its identity and
    # tenant ownership are immutable once created.
    connection.execute(
        "CREATE TRIGGER IF NOT EXISTS canonical_contents_immutable_identity "
        "BEFORE " + "UPDATE " + "ON canonical_contents "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id "
        "OR NEW.topic_brief_id != OLD.topic_brief_id OR NEW.stable_key != OLD.stable_key "
        "OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
        "BEGIN SELECT RAISE(ABORT, 'canonical content identity is immutable'); END"
    )
    connection.commit()


__all__ = ["initialize"]
