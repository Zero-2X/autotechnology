"""CANON-005 add immutable freshness checks and an operational refresh queue."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_canon_005"
down_revision = "20260918_found_canon_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("canonical_content_versions") as batch:
        batch.add_column(sa.Column("freshness_status", sa.String(16), nullable=False, server_default=sa.text("'fresh'")))
        batch.add_column(sa.Column("freshness_checked_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("freshness_expires_at", sa.String(40), nullable=True))
        batch.add_column(sa.Column("conflict_set_ids_json", sa.Text, nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("refresh_required", sa.Integer, nullable=False, server_default=sa.text("0")))
    op.create_table(
        "canonical_freshness_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_version_id", sa.String(36), nullable=False),
        sa.Column("freshness_status", sa.String(16), nullable=False),
        sa.Column("checked_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=True),
        sa.Column("conflict_set_ids_json", sa.Text, nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.CheckConstraint("freshness_status IN ('fresh', 'review_due', 'stale', 'expired', 'conflict', 'withdrawn')", name="ck_canonical_freshness_status"),
    )
    op.create_table(
        "canonical_refresh_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_version_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("50")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("available_at", sa.String(40), nullable=False),
        sa.Column("lease_owner", sa.String(256), nullable=True),
        sa.Column("lease_until", sa.String(40), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.CheckConstraint("status IN ('queued', 'claimed', 'completed', 'cancelled')", name="ck_canonical_refresh_queue_status"),
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_canonical_refresh_queue_priority"),
        sa.CheckConstraint("attempts >= 0", name="ck_canonical_refresh_queue_attempts"),
    )
    op.create_index("ix_canonical_freshness_version", "canonical_freshness_checks", ["org_id", "canonical_content_version_id", "checked_at"])
    op.create_index("ix_canonical_refresh_queue_ready", "canonical_refresh_queue", ["org_id", "status", "available_at", "priority"])


def downgrade() -> None:
    op.drop_index("ix_canonical_refresh_queue_ready", table_name="canonical_refresh_queue")
    op.drop_table("canonical_refresh_queue")
    op.drop_index("ix_canonical_freshness_version", table_name="canonical_freshness_checks")
    op.drop_table("canonical_freshness_checks")
    with op.batch_alter_table("canonical_content_versions") as batch:
        batch.drop_column("refresh_required")
        batch.drop_column("conflict_set_ids_json")
        batch.drop_column("freshness_expires_at")
        batch.drop_column("freshness_checked_at")
        batch.drop_column("freshness_status")
