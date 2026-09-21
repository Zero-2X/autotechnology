"""WORKFLOW-CORE-003 records outbox dispatch and task-job lifecycle ownership."""

revision = "20260918_found_workflow_core_003"
down_revision = "20260918_found_workflow_core_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep the expand-phase migration credential-free and reversible."""


def downgrade() -> None:
    """No destructive operation is needed for the synthetic slice."""
