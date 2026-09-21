"""MODEL-001 records the optional approved-provider routing slice."""

revision = "20260919_found_model_001"
down_revision = "20260919_found_agent_core_005e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: model config and call ledgers already exist."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
