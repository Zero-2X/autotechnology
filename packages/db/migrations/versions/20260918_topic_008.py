"""TOPIC-008 adds explicit immutable TopicBrief version metadata."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_008"
down_revision = "20260918_found_topic_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable additions keep already-created TOPIC-004 drafts readable; all
    # new service writes populate these fields atomically with the payload.
    op.add_column("topic_briefs", sa.Column("input_snapshot_hash", sa.String(64), nullable=True))
    op.add_column("topic_briefs", sa.Column("locked_at", sa.String(64), nullable=True))
    op.add_column("topic_briefs", sa.Column("locked_by", sa.String(36), nullable=True))
    op.add_column("topic_briefs", sa.Column("supersedes_version_id", sa.String(36), nullable=True))
    op.add_column("topic_briefs", sa.Column("created_by", sa.String(36), nullable=True))
    op.add_column("topic_briefs", sa.Column("created_at", sa.String(64), nullable=True))
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER topic_briefs_immutable_after_approval "
            "BEFORE UPDATE ON topic_briefs "
            "WHEN OLD.status IN ('locked', 'approved', 'superseded') "
            "AND NOT (OLD.status IN ('locked', 'approved') AND NEW.status = 'superseded') "
            "BEGIN SELECT RAISE(ABORT, 'approved topic brief versions are immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER topic_briefs_no_delete_after_approval "
            "BEFORE DELETE ON topic_briefs "
            "WHEN OLD.status IN ('locked', 'approved', 'superseded') "
            "BEGIN SELECT RAISE(ABORT, 'approved topic brief versions are immutable'); END"
        )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE FUNCTION topic_briefs_immutable_after_approval() RETURNS trigger AS $$ "
                   "BEGIN IF OLD.status IN ('locked', 'approved', 'superseded') "
                   "AND NOT (OLD.status IN ('locked', 'approved') AND NEW.status = 'superseded') "
                   "THEN RAISE EXCEPTION 'approved topic brief versions are immutable'; END IF; RETURN NEW; END; "
                   "$$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER topic_briefs_immutable_after_approval "
                   "BEFORE UPDATE ON topic_briefs FOR EACH ROW "
                   "EXECUTE FUNCTION topic_briefs_immutable_after_approval()")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS topic_briefs_immutable_after_approval")
        op.execute("DROP TRIGGER IF EXISTS topic_briefs_no_delete_after_approval")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS topic_briefs_immutable_after_approval ON topic_briefs")
        op.execute("DROP FUNCTION IF EXISTS topic_briefs_immutable_after_approval()")
    for name in ("created_at", "created_by", "supersedes_version_id", "locked_by", "locked_at", "input_snapshot_hash"):
        op.drop_column("topic_briefs", name)
