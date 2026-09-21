"""DIST-005B records quota and retry classification policy boundary."""

revision = "20260919_found_dist_005b"
down_revision = "20260919_found_dist_005a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: retry policy projections are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
