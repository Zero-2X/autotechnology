"""PROD-001 defines an in-memory Variant draft and a replaceable TransformPort."""

revision = "20260919_found_prod_001"
down_revision = "20260919_found_agent_core_005a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """PROD-002 owns persistent ContentVariant and VariantVersion tables."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
