"""OBS-CORE-002 records the synthetic recovery-drill ownership boundary."""

from alembic import op
import sqlalchemy as sa

revision = "20260918_found_obs_core_002"
down_revision = "20260918_found_obs_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_recovery_queue_pauses",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("queue_name", sa.String(128), nullable=False),
        sa.Column("restore_id", sa.String(36), nullable=False),
        sa.Column("paused", sa.Boolean, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "queue_name"),
    )


def downgrade() -> None:
    op.drop_table("audit_recovery_queue_pauses")
