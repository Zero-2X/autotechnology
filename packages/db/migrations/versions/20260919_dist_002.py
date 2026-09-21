"""DIST-002 records the separated distribution port boundary."""

revision = "20260919_found_dist_002"
down_revision = "20260919_found_dist_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: port and capability projections are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
