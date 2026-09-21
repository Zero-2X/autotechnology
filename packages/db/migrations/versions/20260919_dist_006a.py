"""DIST-006A records intent and delivery idempotency boundaries."""

revision = "20260919_found_dist_006a"
down_revision = "20260919_found_dist_005b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: idempotency projections are in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
