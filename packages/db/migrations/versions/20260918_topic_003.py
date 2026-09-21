"""TOPIC-003 adds versioned scoring and tenant-scoped opportunities."""

from hashlib import sha256
import json

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_003"
down_revision = "20260918_found_topic_002"
branch_labels = None
depends_on = None

WEIGHTS = {
    "demand": 0.25, "relevance": 0.25, "evidence_availability": 0.20,
    "differentiation": 0.15, "timeliness": 0.15, "cost": 0.15, "risk": 0.25,
}


def upgrade() -> None:
    op.create_table(
        "topic_scoring_versions",
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("weights_json", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "topic_opportunities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_key", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_topic_opportunities_org_id"),
        sa.CheckConstraint("status IN ('proposed', 'shortlisted', 'rejected', 'expired')", name="ck_topic_opportunity_status"),
        sa.CheckConstraint("version >= 0", name="ck_topic_opportunity_version"),
    )
    op.create_index("ix_topic_opportunities_active", "topic_opportunities",
                    ["org_id", "canonical_key", "status", "expires_at"])
    op.create_table(
        "topic_score_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("opportunity_id", sa.String(36), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["org_id", "opportunity_id"],
                                ["topic_opportunities.org_id", "topic_opportunities.id"]),
    )
    op.create_table(
        "topic_opportunity_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )
    op.create_table(
        "topic_opportunity_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.CheckConstraint("event_type = 'topic.opportunity.scored'", name="ck_topic_opportunity_event_type"),
    )
    encoded = json.dumps(WEIGHTS, sort_keys=True, separators=(",", ":"))
    op.execute(
        sa.text("INSERT INTO topic_scoring_versions (version, weights_json, content_hash) "
                "VALUES (:version, :weights, :digest)").bindparams(
                    version="topic-score-v1", weights=encoded, digest=sha256(encoded.encode()).hexdigest()
                )
    )
    if op.get_bind().dialect.name == "sqlite":
        for table in ("topic_scoring_versions", "topic_opportunity_events"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_immutable_rows() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'topic rows are append-only'; END; $$ LANGUAGE plpgsql")
        for table in ("topic_scoring_versions", "topic_opportunity_events"):
            op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
                       "FOR EACH ROW EXECUTE FUNCTION topic_immutable_rows()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for table in ("topic_scoring_versions", "topic_opportunity_events"):
            for action in ("UPDATE", "DELETE"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{action.lower()}")
    elif op.get_bind().dialect.name == "postgresql":
        for table in ("topic_scoring_versions", "topic_opportunity_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        op.execute("DROP FUNCTION IF EXISTS topic_immutable_rows()")
    op.drop_table("topic_opportunity_events")
    op.drop_table("topic_opportunity_commands")
    op.drop_table("topic_score_snapshots")
    op.drop_index("ix_topic_opportunities_active", table_name="topic_opportunities")
    op.drop_table("topic_opportunities")
    op.drop_table("topic_scoring_versions")
