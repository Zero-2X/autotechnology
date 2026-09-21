"""DIST-011 records the credential-free fixture webhook ingress boundary."""

revision = "20260919_found_dist_011"
down_revision = "20260919_found_dist_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: fixture ingress uses existing contract projections."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
