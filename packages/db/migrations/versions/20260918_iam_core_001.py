"""IAM-CORE-001 synthetic IAM is in-memory; no production tables yet."""

revision = "20260918_found_iam_core_001"
down_revision = "20260918_found_012b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No database objects are created by the synthetic identity slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
