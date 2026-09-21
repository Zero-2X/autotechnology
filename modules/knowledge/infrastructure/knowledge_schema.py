"""SQLite persistence primitives for the KNOW-001 knowledge facts.

The tables in this module are deliberately boring: business state lives in
the service payloads, while relation tables are the write-side source of truth
for Entity↔Claim and Claim↔Evidence links.  Every audit/relation table is
append-only; stateful records only permit the state projection to advance.
"""

from __future__ import annotations


def _append_only(connection, table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
            f"BEFORE {action} ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def initialize(connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS entities ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_key TEXT NOT NULL, "
        "canonical_name TEXT NOT NULL, aliases_json TEXT NOT NULL, entity_type TEXT NOT NULL, "
        "status TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL, "
        "created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), UNIQUE(org_id, canonical_key), "
        "CHECK(status IN ('draft', 'active', 'retired')), CHECK(version >= 0), CHECK(length(content_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS claims ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, statement TEXT NOT NULL, fact_type TEXT NOT NULL, "
        "entity_ids_json TEXT NOT NULL, applicable_versions_json TEXT NOT NULL, "
        "applicable_regions_json TEXT NOT NULL, applicable_locales_json TEXT NOT NULL, "
        "valid_from TEXT, valid_to TEXT, review_due_at TEXT, supersedes_claim_id TEXT, "
        "freshness_status TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL, "
        "content_hash TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(org_id, id), "
        "CHECK(status IN ('draft', 'verified', 'withdrawn')), "
        "CHECK(freshness_status IN ('fresh', 'review_due', 'stale', 'withdrawn')), "
        "CHECK(version >= 0), CHECK(length(content_hash) = 64), "
        "FOREIGN KEY(org_id, supersedes_claim_id) REFERENCES claims(org_id, id))"
    )
    # Standalone unit callers may initialize Knowledge before the provenance
    # service.  SQLite cannot enforce a foreign key to a table that does not
    # exist at insert time, so only add the external FKs when their owners are
    # already present; the Alembic migration always includes both constraints.
    source_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_snapshots'"
    ).fetchone() is not None
    rights_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'rights_record_versions'"
    ).fetchone() is not None
    evidence_sql = (
        "CREATE TABLE IF NOT EXISTS evidences ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, source_snapshot_id TEXT NOT NULL, "
        "claim_id TEXT, rights_record_version_id TEXT, evidence_type TEXT NOT NULL, quote TEXT NOT NULL, "
        "locator TEXT, applicable_versions_json TEXT NOT NULL, applicable_regions_json TEXT NOT NULL, "
        "applicable_locales_json TEXT NOT NULL, valid_from TEXT, valid_to TEXT, review_due_at TEXT, "
        "captured_at TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL, content_hash TEXT NOT NULL, "
        "created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(org_id, id), "
        "CHECK(status IN ('captured', 'valid', 'expired', 'revoked')), CHECK(version >= 0), "
        "CHECK(length(content_hash) = 64), "
        "FOREIGN KEY(org_id, claim_id) REFERENCES claims(org_id, id)"
    )
    if source_table:
        evidence_sql += ", FOREIGN KEY(org_id, source_snapshot_id) REFERENCES source_snapshots(org_id, id)"
    if rights_table:
        evidence_sql += ", FOREIGN KEY(org_id, rights_record_version_id) REFERENCES rights_record_versions(org_id, id)"
    evidence_sql += ")"
    connection.execute(evidence_sql)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS entity_claims ("
        "org_id TEXT NOT NULL, entity_id TEXT NOT NULL, claim_id TEXT NOT NULL, "
        "created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(org_id, entity_id, claim_id), "
        "FOREIGN KEY(org_id, entity_id) REFERENCES entities(org_id, id), "
        "FOREIGN KEY(org_id, claim_id) REFERENCES claims(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS claim_evidences ("
        "org_id TEXT NOT NULL, claim_id TEXT NOT NULL, evidence_id TEXT NOT NULL, "
        "relation_type TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "PRIMARY KEY(org_id, claim_id, evidence_id), "
        "FOREIGN KEY(org_id, claim_id) REFERENCES claims(org_id, id), "
        "FOREIGN KEY(org_id, evidence_id) REFERENCES evidences(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key), CHECK(length(payload_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, "
        "aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, sequence INTEGER NOT NULL, envelope TEXT NOT NULL, "
        "UNIQUE(org_id, aggregate_type, aggregate_id, sequence))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_cores ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, topic_brief_id TEXT, current_version_id TEXT, "
        "status TEXT NOT NULL, needs_review INTEGER NOT NULL, created_by TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(org_id, id), "
        "CHECK(status IN ('draft', 'validated', 'stale', 'archived')), CHECK(needs_review IN (0, 1)))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_core_versions ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, knowledge_core_id TEXT NOT NULL, topic_brief_id TEXT, "
        "version_no INTEGER NOT NULL, entity_ids_json TEXT NOT NULL, claim_ids_json TEXT NOT NULL, "
        "evidence_ids_json TEXT NOT NULL, conflict_set_ids_json TEXT NOT NULL, freshness_checked_at TEXT, "
        "snapshot_hash TEXT NOT NULL, content_hash TEXT NOT NULL, status TEXT NOT NULL, "
        "supersedes_version_id TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), UNIQUE(org_id, knowledge_core_id, version_no), "
        "FOREIGN KEY(org_id, knowledge_core_id) REFERENCES knowledge_cores(org_id, id), "
        "CHECK(version_no >= 1), CHECK(status IN ('draft', 'verified', 'superseded', 'withdrawn', 'needs_review')), "
        "CHECK(length(snapshot_hash) = 64), CHECK(length(content_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_conflict_sets ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, conflict_key TEXT NOT NULL, claim_ids_json TEXT NOT NULL, "
        "reason TEXT NOT NULL, status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), UNIQUE(org_id, conflict_key), CHECK(status IN ('needs_review', 'resolved', 'dismissed')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_core_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key), CHECK(length(payload_hash) = 64))"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ix_entities_org_status ON entities(org_id, status, canonical_key)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_claims_org_status ON claims(org_id, status, freshness_status)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_claims_org_validity ON claims(org_id, valid_from, valid_to)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_evidences_org_status ON evidences(org_id, status, captured_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_entity_claims_claim ON entity_claims(org_id, claim_id, entity_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_claim_evidences_claim ON claim_evidences(org_id, claim_id, evidence_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_events_aggregate ON knowledge_events(org_id, aggregate_type, aggregate_id, sequence)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_cores_org_status ON knowledge_cores(org_id, status, updated_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_core_versions_current ON knowledge_core_versions(org_id, knowledge_core_id, version_no, status)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_conflict_sets_org_status ON knowledge_conflict_sets(org_id, status, created_at)")

    for table in ("entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"):
        _append_only(connection, table)
    for table in ("knowledge_core_versions", "knowledge_conflict_sets", "knowledge_core_commands"):
        _append_only(connection, table)

    connection.execute(
        "CREATE TRIGGER IF NOT EXISTS knowledge_cores_immutable_fields BEFORE " + "UPDATE " + "ON knowledge_cores "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id "
        "OR NEW.topic_brief_id IS NOT OLD.topic_brief_id OR NEW.created_by != OLD.created_by "
        "OR NEW.created_at != OLD.created_at "
        "OR json_extract(NEW.payload, '$.id') IS NOT OLD.id "
        "OR json_extract(NEW.payload, '$.org_id') IS NOT OLD.org_id "
        "OR json_extract(NEW.payload, '$.topic_brief_id') IS NOT OLD.topic_brief_id "
        "BEGIN SELECT RAISE(ABORT, 'knowledge core identity is immutable'); END"
    )

    # Entity and Claim are state projections.  Their identity/content fields
    # cannot be rewritten while a transition may still update status/version.
    connection.execute(
        "CREATE TRIGGER IF NOT EXISTS entities_immutable_fields BEFORE " + "UPDATE " + "ON entities "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.canonical_key != OLD.canonical_key "
        "OR NEW.canonical_name != OLD.canonical_name OR NEW.aliases_json != OLD.aliases_json "
        "OR NEW.entity_type != OLD.entity_type OR NEW.created_by != OLD.created_by "
        "OR NEW.created_at != OLD.created_at OR NEW.content_hash != OLD.content_hash "
        "OR json_extract(NEW.payload, '$.id') IS NOT OLD.id "
        "OR json_extract(NEW.payload, '$.org_id') IS NOT OLD.org_id "
        "OR json_extract(NEW.payload, '$.canonical_name') IS NOT OLD.canonical_name "
        "OR json_extract(NEW.payload, '$.entity_type') IS NOT OLD.entity_type "
        "BEGIN SELECT RAISE(ABORT, 'entity identity is immutable'); END"
    )
    connection.execute(
        "CREATE TRIGGER IF NOT EXISTS claims_immutable_fields BEFORE " + "UPDATE " + "ON claims "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.statement != OLD.statement "
        "OR NEW.fact_type != OLD.fact_type OR NEW.entity_ids_json != OLD.entity_ids_json "
        "OR NEW.applicable_versions_json != OLD.applicable_versions_json "
        "OR NEW.applicable_regions_json != OLD.applicable_regions_json "
        "OR NEW.applicable_locales_json != OLD.applicable_locales_json "
        "OR NEW.valid_from IS NOT OLD.valid_from OR NEW.valid_to IS NOT OLD.valid_to "
        "OR NEW.review_due_at IS NOT OLD.review_due_at "
        "OR NEW.supersedes_claim_id IS NOT OLD.supersedes_claim_id "
        "OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
        "OR NEW.content_hash != OLD.content_hash "
        "OR json_extract(NEW.payload, '$.id') IS NOT OLD.id "
        "OR json_extract(NEW.payload, '$.org_id') IS NOT OLD.org_id "
        "OR json_extract(NEW.payload, '$.statement') IS NOT OLD.statement "
        "OR json_extract(NEW.payload, '$.fact_type') IS NOT OLD.fact_type "
        "BEGIN SELECT RAISE(ABORT, 'claim identity is immutable'); END"
    )
    connection.execute(
        "CREATE TRIGGER IF NOT EXISTS evidences_immutable_fields BEFORE " + "UPDATE " + "ON evidences "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.source_snapshot_id != OLD.source_snapshot_id "
        "OR NEW.rights_record_version_id IS NOT OLD.rights_record_version_id "
        "OR NEW.evidence_type != OLD.evidence_type OR NEW.quote != OLD.quote "
        "OR NEW.locator IS NOT OLD.locator OR NEW.applicable_versions_json != OLD.applicable_versions_json "
        "OR NEW.applicable_regions_json != OLD.applicable_regions_json "
        "OR NEW.applicable_locales_json != OLD.applicable_locales_json "
        "OR NEW.valid_from IS NOT OLD.valid_from OR NEW.valid_to IS NOT OLD.valid_to "
        "OR NEW.review_due_at IS NOT OLD.review_due_at OR NEW.captured_at != OLD.captured_at "
        "OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
        "OR NEW.content_hash != OLD.content_hash "
        "OR json_extract(NEW.payload, '$.id') IS NOT OLD.id "
        "OR json_extract(NEW.payload, '$.org_id') IS NOT OLD.org_id "
        "OR json_extract(NEW.payload, '$.source_snapshot_id') IS NOT OLD.source_snapshot_id "
        "OR json_extract(NEW.payload, '$.quote') IS NOT OLD.quote "
        "BEGIN SELECT RAISE(ABORT, 'evidence identity is immutable'); END"
    )
    for action in ("UPDATE", "DELETE"):
        connection.execute(
            f"CREATE TRIGGER IF NOT EXISTS evidences_no_{action.lower()}_delete "
            f"BEFORE {action} ON evidences "
            + ("BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END" if action == "DELETE" else "")
        ) if action == "DELETE" else None
    connection.commit()


__all__ = ["initialize"]
