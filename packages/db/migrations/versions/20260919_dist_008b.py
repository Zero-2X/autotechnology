"""DIST-008B records Intent mode and scoped kill-switch boundaries."""

revision = "20260919_found_dist_008b"
down_revision = "20260919_found_dist_008a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: mode gates and kill-switch projections remain in memory."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
