"""SQLite tables owned by Production for stable Variant roots and versions."""


def initialize(connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS content_variants ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, canonical_content_id TEXT NOT NULL, "
        "locale TEXT NOT NULL, market TEXT NOT NULL, audience TEXT NOT NULL, "
        "current_version_id TEXT, status TEXT NOT NULL, created_by TEXT NOT NULL, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), UNIQUE(org_id, canonical_content_id, locale, market, audience), "
        "CHECK(status IN ('draft', 'active', 'withdrawn', 'retired')), "
        "FOREIGN KEY(org_id, canonical_content_id) REFERENCES canonical_contents(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS variant_versions ("
        "id TEXT PRIMARY KEY, org_id TEXT NOT NULL, content_variant_id TEXT NOT NULL, "
        "canonical_content_version_id TEXT NOT NULL, region_profile_version_id TEXT NOT NULL, "
        "version_no INTEGER NOT NULL, status TEXT NOT NULL, snapshot_hash TEXT NOT NULL, "
        "source_map_json TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, id), UNIQUE(org_id, content_variant_id, version_no), "
        "CHECK(version_no >= 1), CHECK(length(snapshot_hash) = 64), "
        "CHECK(status IN ('planned', 'draft', 'localized', 'qa_pending', 'approved', 'withdrawn')), "
        "FOREIGN KEY(org_id, content_variant_id) REFERENCES content_variants(org_id, id), "
        "FOREIGN KEY(org_id, canonical_content_version_id) REFERENCES canonical_content_versions(org_id, id))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS variant_commands ("
        "org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, trace_id TEXT NOT NULL, response TEXT NOT NULL, "
        "PRIMARY KEY(org_id, idempotency_key), CHECK(length(request_hash) = 64))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS variant_events ("
        "event_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, aggregate_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    connection.execute("CREATE INDEX IF NOT EXISTS ix_variants_source ON content_variants(org_id, canonical_content_id, locale, market)")
    connection.execute("CREATE INDEX IF NOT EXISTS ix_variant_versions_canonical ON variant_versions(org_id, canonical_content_version_id, created_at)")
    for table in ("variant_versions", "variant_commands", "variant_events"):
        for action in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                f"BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    connection.execute(
        "CREATE TRIGGER IF NOT EXISTS content_variants_immutable_identity BEFORE " + "UPDATE " + "ON content_variants "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR "
        "NEW.canonical_content_id != OLD.canonical_content_id OR NEW.locale != OLD.locale OR "
        "NEW.market != OLD.market OR NEW.audience != OLD.audience "
        "BEGIN SELECT RAISE(ABORT, 'variant identity is immutable'); END"
    )
    connection.commit()


__all__ = ["initialize"]
