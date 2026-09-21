"""AGENT-CORE-002 runner records are kept in the credential-free slice."""

revision = "20260918_found_agent_core_002"
down_revision = "20260918_found_agent_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production agent-run tables or external tools are connected."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
