"""DIST-008A records Target and TargetVersion immutability boundaries."""

revision = "20260919_found_dist_008a"
down_revision = "20260919_found_dist_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: immutable snapshots and lifecycle projections remain in memory."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
