"""AGENT-CORE-005C records the extraction-only Rights/Provenance Agent slice."""

revision = "20260919_found_agent_core_005c"
down_revision = "20260919_found_agent_core_005b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: AgentRunner and the append-only ledger already exist."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
