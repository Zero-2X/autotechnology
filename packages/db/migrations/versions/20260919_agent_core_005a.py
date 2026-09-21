"""AGENT-CORE-005A adds a planner use case over existing in-memory agent contracts."""

revision = "20260919_found_agent_core_005a"
down_revision = "20260919_found_canon_006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production planner table is connected in this account-free slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
