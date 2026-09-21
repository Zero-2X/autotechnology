"""TOPIC-007 adds durable verification results for immutable score snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_007"
down_revision = "20260918_found_topic_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_score_snapshot_verifications",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "snapshot_id", "idempotency_key"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["topic_score_snapshots.id"]),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_topic_snapshot_verification_hash"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER topic_score_snapshot_verifications_no_{action.lower()} "
                f"BEFORE {action} ON topic_score_snapshot_verifications BEGIN "
                "SELECT RAISE(ABORT, 'topic score snapshot verifications are append-only'); END"
            )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_score_snapshot_verifications_immutable() RETURNS trigger AS $$ "
                   "BEGIN RAISE EXCEPTION 'topic score snapshot verifications are append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER topic_score_snapshot_verifications_no_mutation "
                   "BEFORE UPDATE OR DELETE ON topic_score_snapshot_verifications FOR EACH ROW "
                   "EXECUTE FUNCTION topic_score_snapshot_verifications_immutable()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS topic_score_snapshot_verifications_no_update")
        op.execute("DROP TRIGGER IF EXISTS topic_score_snapshot_verifications_no_delete")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS topic_score_snapshot_verifications_no_mutation ON topic_score_snapshot_verifications")
        op.execute("DROP FUNCTION IF EXISTS topic_score_snapshot_verifications_immutable()")
    op.drop_table("topic_score_snapshot_verifications")
