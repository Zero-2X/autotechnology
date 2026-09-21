"""TOPIC-005 adds versioned editorial calendar assignments."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_005"
down_revision = "20260918_found_topic_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_editorial_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("opportunity_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "opportunity_id", "version_no", name="uq_topic_editorial_plan_version"),
        sa.ForeignKeyConstraint(["org_id", "opportunity_id"],
                                ["topic_opportunities.org_id", "topic_opportunities.id"]),
        sa.CheckConstraint("version_no >= 1", name="ck_topic_editorial_plan_version"),
        sa.CheckConstraint("status IN ('active', 'superseded', 'cancelled')", name="ck_topic_editorial_plan_status"),
    )
    op.create_index("ix_topic_editorial_plans_current", "topic_editorial_plans",
                    ["org_id", "opportunity_id", "version_no", "status"])
    op.create_table(
        "topic_editorial_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )
    op.create_table(
        "topic_editorial_audit",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("opportunity_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.String(64), nullable=False),
        sa.Column("audit_seq", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.CheckConstraint("event_type IN ('topic.editorial_plan.scheduled', 'topic.editorial_plan.overridden')",
                           name="ck_topic_editorial_audit_event"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER topic_editorial_audit_no_{action.lower()} BEFORE {action} ON topic_editorial_audit "
                "BEGIN SELECT RAISE(ABORT, 'editorial calendar audit is append-only'); END"
            )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_editorial_audit_immutable() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'editorial calendar audit is append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER topic_editorial_audit_no_mutation BEFORE UPDATE OR DELETE ON topic_editorial_audit "
                   "FOR EACH ROW EXECUTE FUNCTION topic_editorial_audit_immutable()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS topic_editorial_audit_no_update")
        op.execute("DROP TRIGGER IF EXISTS topic_editorial_audit_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS topic_editorial_audit_no_mutation ON topic_editorial_audit")
        op.execute("DROP FUNCTION IF EXISTS topic_editorial_audit_immutable()")
    op.drop_table("topic_editorial_audit")
    op.drop_table("topic_editorial_commands")
    op.drop_index("ix_topic_editorial_plans_current", table_name="topic_editorial_plans")
    op.drop_table("topic_editorial_plans")
