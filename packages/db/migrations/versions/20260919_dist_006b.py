"""DIST-006B records publication status reconciliation boundaries."""

revision = "20260919_found_dist_006b"
down_revision = "20260919_found_dist_006a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: reconciliation projections are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
