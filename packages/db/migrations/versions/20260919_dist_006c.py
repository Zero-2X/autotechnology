"""DIST-006C records delivery unknown, dead-letter and manual replay boundaries."""

revision = "20260919_found_dist_006c"
down_revision = "20260919_found_dist_006b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: this slice keeps projections in memory."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
