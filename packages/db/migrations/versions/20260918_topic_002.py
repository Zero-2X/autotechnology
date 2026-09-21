"""TOPIC-002 adds durable TopicSignal imports and row rejection events."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_002"
down_revision = "20260918_found_topic_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("usage_rights_status", sa.String(16), nullable=False),
        sa.Column("permitted_use", sa.String(16), nullable=False),
        sa.Column("terms_snapshot_ref", sa.Text, nullable=True),
        sa.Column("license_ref", sa.Text, nullable=True),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "dedupe_key", name="uq_topic_signals_org_dedupe"),
        sa.CheckConstraint(
            "usage_rights_status IN ('unknown', 'verified', 'restricted', 'rejected')",
            name="ck_topic_signals_rights",
        ),
        sa.CheckConstraint(
            "permitted_use IN ('research', 'editorial', 'commercial', 'none')",
            name="ck_topic_signals_use",
        ),
    )
    op.create_table(
        "topic_signal_imports",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("policy_snapshot_ref", sa.String(128), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.String(32), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )
    op.create_table(
        "topic_signal_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.CheckConstraint("event_type = 'topic_signal.rejected'", name="ck_topic_signal_event_type"),
    )
    op.create_index("ix_topic_signal_events_org", "topic_signal_events", ["org_id", "idempotency_key"])
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER topic_signal_events_no_{action.lower()} "
                f"BEFORE {action} ON topic_signal_events BEGIN "
                "SELECT RAISE(ABORT, 'topic signal events are append-only'); END"
            )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_signal_events_immutable() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'topic signal events are append-only'; END; "
                   "$$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER topic_signal_events_no_mutation BEFORE UPDATE OR DELETE "
                   "ON topic_signal_events FOR EACH ROW EXECUTE FUNCTION topic_signal_events_immutable()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS topic_signal_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS topic_signal_events_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS topic_signal_events_no_mutation ON topic_signal_events")
        op.execute("DROP FUNCTION IF EXISTS topic_signal_events_immutable()")
    op.drop_index("ix_topic_signal_events_org", table_name="topic_signal_events")
    op.drop_table("topic_signal_events")
    op.drop_table("topic_signal_imports")
    op.drop_table("topic_signals")
