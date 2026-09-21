"""AGENT-CORE-005B records the candidate-only Research Agent slice."""

revision = "20260919_found_agent_core_005b"
down_revision = "20260919_found_feedback_core_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: AgentRunner and the append-only ledger already exist."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
