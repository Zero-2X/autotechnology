"""DIST-001 records the deterministic distribution projection boundary."""

revision = "20260919_found_dist_001"
down_revision = "20260919_found_approval_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: DIST-001 projections are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
