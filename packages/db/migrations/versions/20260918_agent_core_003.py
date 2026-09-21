"""AGENT-CORE-003 external evidence boundary has no business tables."""

revision = "20260918_found_agent_core_003"
down_revision = "20260918_found_agent_core_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No external connector or prompt-injection path is enabled."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
