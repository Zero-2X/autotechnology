"""ACCOUNT-CORE-001 credential-free account references are in-memory."""

revision = "20260918_found_account_core_001"
down_revision = "20260918_found_iam_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No external-account tables or credentials are created."""


def downgrade() -> None:
    """Keep the linear revision chain reversible."""
