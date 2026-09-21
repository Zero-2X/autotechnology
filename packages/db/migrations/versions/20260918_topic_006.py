"""TOPIC-006 adds append-only opportunity state transition events."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_006"
down_revision = "20260918_found_topic_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_opportunity_state_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("opportunity_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "opportunity_id", "sequence", name="uq_topic_opportunity_state_sequence"),
        sa.ForeignKeyConstraint(["org_id", "opportunity_id"],
                                ["topic_opportunities.org_id", "topic_opportunities.id"]),
        sa.CheckConstraint(
            "event_type IN ('topic.opportunity.reject', 'topic.opportunity.defer', "
            "'topic.opportunity.expire', 'topic.opportunity.resume')",
            name="ck_topic_opportunity_state_event_type",
        ),
    )
    op.create_index("ix_topic_opportunity_state_events_org", "topic_opportunity_state_events",
                    ["org_id", "opportunity_id", "sequence"])
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER topic_opportunity_state_events_no_{action.lower()} "
                f"BEFORE {action} ON topic_opportunity_state_events BEGIN "
                "SELECT RAISE(ABORT, 'opportunity state events are append-only'); END"
            )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_opportunity_state_events_immutable() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'opportunity state events are append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER topic_opportunity_state_events_no_mutation "
                   "BEFORE UPDATE OR DELETE ON topic_opportunity_state_events FOR EACH ROW "
                   "EXECUTE FUNCTION topic_opportunity_state_events_immutable()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS topic_opportunity_state_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS topic_opportunity_state_events_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS topic_opportunity_state_events_no_mutation ON topic_opportunity_state_events")
        op.execute("DROP FUNCTION IF EXISTS topic_opportunity_state_events_immutable()")
    op.drop_index("ix_topic_opportunity_state_events_org", table_name="topic_opportunity_state_events")
    op.drop_table("topic_opportunity_state_events")
