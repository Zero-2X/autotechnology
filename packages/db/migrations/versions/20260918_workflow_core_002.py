"""WORKFLOW-CORE-002 records workflow run, step, and human-task state surfaces."""

revision = "20260918_found_workflow_core_002"
down_revision = "20260918_found_workflow_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Declare the expand-phase ownership without connecting a live database."""


def downgrade() -> None:
    """Keep the revision chain reversible for the synthetic foundation slice."""
