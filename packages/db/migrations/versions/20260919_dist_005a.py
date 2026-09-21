"""DIST-005A records capability matrix and adapter field mapping boundary."""

revision = "20260919_found_dist_005a"
down_revision = "20260919_found_dist_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: capability matrices are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
