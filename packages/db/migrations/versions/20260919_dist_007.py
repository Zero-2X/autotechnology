"""DIST-007 records the four delivery-mode routing boundaries."""

revision = "20260919_found_dist_007"
down_revision = "20260919_found_dist_006c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: mode routing projections remain in memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
