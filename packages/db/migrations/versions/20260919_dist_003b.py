"""DIST-003B records private ExportPackage storage and download lifecycle."""

revision = "20260919_found_dist_003b"
down_revision = "20260919_found_dist_003a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: private package storage is in-memory in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
