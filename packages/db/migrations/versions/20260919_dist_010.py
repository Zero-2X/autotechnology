"""DIST-010 records the credential-free Fake Adapter delivery workflow."""

revision = "20260919_found_dist_010"
down_revision = "20260919_found_dist_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: the workflow composes existing projections."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
