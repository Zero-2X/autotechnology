"""APPROVAL-001 keeps approval projections append-only."""

revision = "20260919_found_approval_001"
down_revision = "20260919_found_policy_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: Approval and ApprovalDecision are in-memory projections in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
