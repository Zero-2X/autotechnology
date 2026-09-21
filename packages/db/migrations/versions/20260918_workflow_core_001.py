"""WORKFLOW-CORE-001 state machine is delivered as a credential-free slice."""

revision = "20260918_found_workflow_core_001"
down_revision = "20260918_found_agent_core_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production workflow tables or scheduler side effects are connected."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
