"""MODEL-CORE-002 call records remain an in-memory fake-provider slice."""

revision = "20260918_found_model_core_002"
down_revision = "20260918_found_model_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No provider credentials or production model tables are connected."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
