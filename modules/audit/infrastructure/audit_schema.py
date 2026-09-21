"""Local SQLite audit storage, shared by fixtures and durable offline service."""

TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS audit_logs (id TEXT PRIMARY KEY, org_id TEXT NOT NULL, "
    "trace_id TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS audit_logs_trace ON audit_logs (org_id, trace_id)",
    "CREATE TABLE IF NOT EXISTS audit_commands (org_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
    "payload_hash TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY (org_id, idempotency_key))",
)


def initialize(connection) -> None:
    for sql in TABLE_SQL:
        connection.execute(sql)
    for table in ("audit_logs", "audit_commands"):
        for operation in ("UPDATE", "DELETE"):
            connection.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'audit storage is append-only'); END"
            )
    connection.commit()
