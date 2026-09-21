"""Store versioned GOV-007 data-processing policy snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_gov_007"
down_revision = "20260918_found_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_processing_policy_versions",
        sa.Column("policy_key", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("policy_key", "policy_version"),
        sa.CheckConstraint("policy_version >= 1", name="ck_data_processing_policy_version"),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_data_processing_policy_status"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_data_processing_policy_hash"),
    )


def downgrade() -> None:
    op.drop_table("data_processing_policy_versions")
