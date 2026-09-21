"""AGENT-CORE-004 ledger contract is credential-free and append-only in this slice."""

revision = "20260918_found_agent_core_004"
down_revision = "20260918_found_agent_core_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production agent or model tables are connected yet."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
