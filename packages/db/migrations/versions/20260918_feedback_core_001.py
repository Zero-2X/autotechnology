"""FEEDBACK-CORE-001 records the account-free observation and feedback contract slice."""

revision = "20260918_found_feedback_core_001"
down_revision = "20260918_found_workflow_core_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep contract-only feedback migration reversible and credential-free."""


def downgrade() -> None:
    """No destructive operation is needed for this contract-only slice."""
