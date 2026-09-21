"""OBS-CORE-003 records deletion propagation and manual review ownership."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_obs_core_003"
down_revision = "20260918_found_obs_core_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_deletion_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_table(
        "audit_deletion_stages",
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("request_id", "stage"),
    )
    op.create_table(
        "audit_deletion_manual_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_table(
        "audit_deletion_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("audit_deletion_commands")
    op.drop_table("audit_deletion_manual_tasks")
    op.drop_table("audit_deletion_stages")
    op.drop_table("audit_deletion_requests")
