"""Store versioned GOV-008 operational target policies."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_gov_008"
down_revision = "20260918_gov_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_target_versions",
        sa.Column("policy_key", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("policy_key", "policy_version"),
        sa.CheckConstraint("policy_version >= 1", name="ck_operational_target_version"),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_operational_target_status"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_operational_target_hash"),
    )


def downgrade() -> None:
    op.drop_table("operational_target_versions")
