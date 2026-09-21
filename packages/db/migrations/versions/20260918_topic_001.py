"""TOPIC-001 adds tenant-scoped taxonomy and idempotent command storage."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_topic_001"
down_revision = "20260918_found_obs_core_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic_taxonomies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("taxonomy_key", sa.String(256), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "taxonomy_key"),
    )
    op.create_table(
        "topic_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("topic_commands")
    op.drop_table("topic_taxonomies")
