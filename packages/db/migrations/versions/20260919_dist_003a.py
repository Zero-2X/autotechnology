"""DIST-003A records the deterministic manual export adapter boundary."""

revision = "20260919_found_dist_003a"
down_revision = "20260919_found_dist_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: manual export artifacts are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
