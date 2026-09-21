"""SCHED-001 records scheduler-job ownership and lease lifecycle."""

revision = "20260918_found_sched_001"
down_revision = "20260918_found_feedback_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep scheduling state changes reversible and account-free."""


def downgrade() -> None:
    """No destructive operation is needed for the synthetic scheduler slice."""
