"""APPROVAL-002 keeps reviewer decisions immutable in the approval projection."""

revision = "20260919_found_approval_002"
down_revision = "20260919_found_approval_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: decision uniqueness is enforced by the service projection in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
