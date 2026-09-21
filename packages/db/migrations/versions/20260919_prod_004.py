"""PROD-004 deterministic region preflight is a read-only decision projection."""

revision = "20260919_found_prod_004"
down_revision = "20260919_found_prod_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: decisions are kept by the caller's audit projection."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
