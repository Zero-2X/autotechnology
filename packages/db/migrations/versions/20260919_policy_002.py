"""POLICY-002 lifecycle decisions remain a policy projection."""

revision = "20260919_found_policy_002"
down_revision = "20260919_found_policy_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: lifecycle decisions and review tasks are in-memory projections in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
