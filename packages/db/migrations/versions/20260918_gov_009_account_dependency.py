"""Store versioned GOV-009 account dependency decisions, not credentials."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_gov_009"
down_revision = "20260918_gov_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_dependency_versions",
        sa.Column("dependency_key", sa.String(length=128), nullable=False),
        sa.Column("dependency_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("as_of", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("dependency_key", "dependency_version"),
        sa.CheckConstraint("dependency_version >= 1", name="ck_account_dependency_version"),
        sa.CheckConstraint("status IN ('unavailable', 'evidence_pending', 'verified')", name="ck_account_dependency_status"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_account_dependency_hash"),
    )


def downgrade() -> None:
    op.drop_table("account_dependency_versions")
