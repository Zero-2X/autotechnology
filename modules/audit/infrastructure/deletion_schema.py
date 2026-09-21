"""SQLite tables for deletion requests, stage confirmations and manual review."""


def initialize(connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS audit_deletion_requests (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS audit_deletion_stages (request_id TEXT NOT NULL, stage TEXT NOT NULL, "
        "payload TEXT NOT NULL, PRIMARY KEY(request_id, stage))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS audit_deletion_manual_tasks (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, "
        "request_id TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS audit_deletion_commands (org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
        "payload_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(org_id, idempotency_key))"
    )
    connection.commit()
