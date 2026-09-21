"""Store versioned GOV-010 vendor inventories without credentials."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_gov_010"
down_revision = "20260918_gov_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_inventory_versions",
        sa.Column("inventory_key", sa.String(length=128), nullable=False),
        sa.Column("inventory_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("inventory_json", sa.Text(), nullable=False),
        sa.Column("as_of", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("inventory_key", "inventory_version"),
        sa.CheckConstraint("inventory_version >= 1", name="ck_vendor_inventory_version"),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_vendor_inventory_status"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_vendor_inventory_hash"),
    )


def downgrade() -> None:
    op.drop_table("vendor_inventory_versions")
