"""CANON-003 persist the locked/approved TopicBrief input snapshot on versions."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_canon_003"
down_revision = "20260918_found_canon_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("canonical_content_versions") as batch:
        batch.add_column(sa.Column("topic_brief_status", sa.String(16), nullable=False, server_default=sa.text("'approved'")))
        batch.add_column(sa.Column("topic_brief_lock_hash", sa.String(64), nullable=True))
        batch.create_check_constraint(
            "ck_canonical_versions_brief_status",
            "topic_brief_status IN ('locked', 'approved')",
        )


def downgrade() -> None:
    # Batch mode keeps the rollback usable on SQLite versions that do not
    # support ALTER TABLE DROP COLUMN directly.
    with op.batch_alter_table("canonical_content_versions") as batch:
        batch.drop_constraint("ck_canonical_versions_brief_status", type_="check")
        batch.drop_column("topic_brief_lock_hash")
        batch.drop_column("topic_brief_status")
