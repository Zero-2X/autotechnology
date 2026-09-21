"""AGENT-CORE-001 registry is a credential-free versioned contract slice."""

revision = "20260918_found_agent_core_001"
down_revision = "20260918_found_model_core_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production agent tables or tool credentials are connected."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
