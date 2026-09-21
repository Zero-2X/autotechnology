"""SQLite persistence for rights identities, immutable versions, and events."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_records ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, source_id TEXT NOT NULL, "
        "current_version_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(org_id, id), "
        "FOREIGN KEY(org_id, source_id) REFERENCES sources(org_id, id), "
        "CHECK(status IN ('pending', 'verified', 'expired', 'revoked', 'complaint_hold')))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_record_versions ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, rights_record_id TEXT NOT NULL, "
        "version_no INTEGER NOT NULL, source_snapshot_ids TEXT NOT NULL, license_ref TEXT, "
        "contract_ref TEXT, evidence_object_refs TEXT NOT NULL, terms_snapshot_hash TEXT, "
        "rights_holder TEXT NOT NULL, permitted_regions TEXT NOT NULL, permitted_locales TEXT NOT NULL, "
        "permitted_media TEXT NOT NULL, permitted_use TEXT NOT NULL, valid_from TEXT, valid_to TEXT, "
        "status TEXT NOT NULL, policy_rule_version TEXT NOT NULL, verified_by TEXT, verified_at TEXT, "
        "verification_reason TEXT, supersedes_version_id TEXT, snapshot_hash TEXT NOT NULL, "
        "created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, rights_record_id, version_no), UNIQUE(org_id, id), "
        "FOREIGN KEY(org_id, rights_record_id) REFERENCES rights_records(org_id, id), "
        "CHECK(version_no >= 1), CHECK(permitted_use IN ('research', 'derivative', 'commercial')), "
        "CHECK(status IN ('pending', 'verified', 'expired', 'revoked', 'complaint_hold')), "
        "CHECK(length(snapshot_hash) = 64), "
        "CHECK(terms_snapshot_hash IS NULL OR length(terms_snapshot_hash) = 64))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_rights_records_current ON rights_records(org_id, source_id, status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_rights_record_versions_current ON "
        "rights_record_versions(org_id, rights_record_id, version_no, status)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key), CHECK(length(payload_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rights_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, "
        "aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, sequence INTEGER NOT NULL, "
        "envelope TEXT NOT NULL, UNIQUE(org_id, aggregate_type, aggregate_id, sequence), "
        "CHECK(event_type IN ('rights.version.created', 'rights.version.verified', "
        "'rights.version.expired', 'rights.version.revoked', 'rights.version.complaint_hold')), "
        "CHECK(sequence >= 1))"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_rights_events_org_aggregate ON rights_events(org_id, aggregate_id, sequence)"
    )
    for table in ("rights_commands", "rights_events"):
        for action in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                f"BEFORE {action} ON {table} BEGIN "
                f"SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    table = "rights_record_versions"
    delete_action, update_action = "DELETE", "UPDATE"
    connection.execute(
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete "
        f"BEFORE {delete_action} ON {table} BEGIN "
        "SELECT RAISE(ABORT, 'rights record versions are immutable'); END"
    )
    connection.execute(
        f"CREATE TRIGGER IF NOT EXISTS {table}_immutable_fields "
        f"BEFORE {update_action} ON {table} "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.rights_record_id != OLD.rights_record_id "
        "OR NEW.version_no != OLD.version_no OR NEW.source_snapshot_ids != OLD.source_snapshot_ids "
        "OR NEW.license_ref IS NOT OLD.license_ref OR NEW.contract_ref IS NOT OLD.contract_ref "
        "OR NEW.evidence_object_refs != OLD.evidence_object_refs "
        "OR NEW.terms_snapshot_hash IS NOT OLD.terms_snapshot_hash "
        "OR NEW.rights_holder != OLD.rights_holder OR NEW.permitted_regions != OLD.permitted_regions "
        "OR NEW.permitted_locales != OLD.permitted_locales OR NEW.permitted_media != OLD.permitted_media "
        "OR NEW.permitted_use != OLD.permitted_use OR NEW.valid_from IS NOT OLD.valid_from "
        "OR NEW.valid_to IS NOT OLD.valid_to OR NEW.policy_rule_version != OLD.policy_rule_version "
        "OR NEW.supersedes_version_id IS NOT OLD.supersedes_version_id "
        "OR NEW.snapshot_hash != OLD.snapshot_hash OR NEW.created_by != OLD.created_by "
        "OR NEW.created_at != OLD.created_at "
        "OR json_extract(NEW.payload, '$.rights_record_id') IS NOT json_extract(OLD.payload, '$.rights_record_id') "
        "OR json_extract(NEW.payload, '$.version_no') IS NOT json_extract(OLD.payload, '$.version_no') "
        "OR json_extract(NEW.payload, '$.source_snapshot_ids') IS NOT json_extract(OLD.payload, '$.source_snapshot_ids') "
        "OR json_extract(NEW.payload, '$.rights_holder') IS NOT json_extract(OLD.payload, '$.rights_holder') "
        "OR json_extract(NEW.payload, '$.permitted_use') IS NOT json_extract(OLD.payload, '$.permitted_use') "
        "OR json_extract(NEW.payload, '$.snapshot_hash') IS NOT json_extract(OLD.payload, '$.snapshot_hash') "
        "OR (OLD.status IN ('expired', 'revoked', 'complaint_hold') AND NEW.status != OLD.status) "
        "OR (OLD.status = 'pending' AND NEW.status NOT IN ('pending', 'verified', 'expired', 'revoked', 'complaint_hold')) "
        "OR (OLD.status = 'verified' AND NEW.status NOT IN ('verified', 'expired', 'revoked', 'complaint_hold')) "
        "BEGIN SELECT RAISE(ABORT, 'rights record version identity is immutable'); END"
    )
    connection.commit()
