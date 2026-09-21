"""TOPIC-004 adds versioned briefs and append-only brief events."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_004"
down_revision = "20260918_found_topic_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_briefs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("opportunity_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lock_hash", sa.String(64), nullable=True),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "opportunity_id", "version_no", name="uq_topic_brief_version"),
        sa.ForeignKeyConstraint(["org_id", "opportunity_id"],
                                ["topic_opportunities.org_id", "topic_opportunities.id"]),
        sa.CheckConstraint("version_no >= 1", name="ck_topic_brief_version"),
        sa.CheckConstraint("status IN ('draft', 'locked', 'approved', 'superseded', 'cancelled')",
                           name="ck_topic_brief_status"),
    )
    op.create_index("ix_topic_briefs_current", "topic_briefs",
                    ["org_id", "opportunity_id", "version_no", "status"])
    op.create_table(
        "topic_brief_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )
    op.create_table(
        "topic_brief_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.CheckConstraint("event_type IN ('topic.brief.created', 'topic.brief.approved', 'topic.brief.superseded')",
                           name="ck_topic_brief_event_type"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER topic_brief_events_no_{action.lower()} BEFORE {action} ON topic_brief_events "
                "BEGIN SELECT RAISE(ABORT, 'topic brief events are append-only'); END"
            )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_brief_events_immutable() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'topic brief events are append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER topic_brief_events_no_mutation BEFORE UPDATE OR DELETE ON topic_brief_events "
                   "FOR EACH ROW EXECUTE FUNCTION topic_brief_events_immutable()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS topic_brief_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS topic_brief_events_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS topic_brief_events_no_mutation ON topic_brief_events")
        op.execute("DROP FUNCTION IF EXISTS topic_brief_events_immutable()")
    op.drop_table("topic_brief_events")
    op.drop_table("topic_brief_commands")
    op.drop_index("ix_topic_briefs_current", table_name="topic_briefs")
    op.drop_table("topic_briefs")
