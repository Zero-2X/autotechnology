"""OBS-CORE-001 adds durable, append-only audit facts and command responses."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_obs_core_001"
down_revision = "20260918_found_sched_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_index("audit_logs_trace", "audit_logs", ["org_id", "trace_id"])
    op.create_table(
        "audit_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for table in ("audit_logs", "audit_commands"):
            for operation in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'audit storage is append-only'); END"
                )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_audit_mutation() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'audit storage is append-only'; END;
            $$ LANGUAGE plpgsql
        """)
        for table in ("audit_logs", "audit_commands"):
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for table in ("audit_logs", "audit_commands"):
            for operation in ("UPDATE", "DELETE"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{operation.lower()}")
    elif op.get_bind().dialect.name == "postgresql":
        for table in ("audit_logs", "audit_commands"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        op.execute("DROP FUNCTION IF EXISTS reject_audit_mutation()")
    op.drop_table("audit_commands")
    op.drop_index("audit_logs_trace", table_name="audit_logs")
    op.drop_table("audit_logs")
