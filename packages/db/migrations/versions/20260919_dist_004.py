"""DIST-004 records the credential-free FakeOfficialAdapter boundary."""

revision = "20260919_found_dist_004"
down_revision = "20260919_found_dist_003b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: fake platform projections are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
