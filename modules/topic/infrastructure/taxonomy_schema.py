"""Local SQLite tables for taxonomy snapshots and idempotent commands."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_taxonomies (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, "
        "taxonomy_key TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, "
        "UNIQUE(org_id, taxonomy_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS topic_commands (org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
        "payload_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.commit()
