"""DIST-009 records the first no-account Canonical-to-Manual-Export slice."""

revision = "20260919_found_dist_009"
down_revision = "20260919_found_dist_008b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: the vertical slice composes existing projections."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
