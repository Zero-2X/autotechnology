"""MODEL-CORE-001 provider Port is credential-free and has no business tables."""

revision = "20260918_found_model_core_001"
down_revision = "20260918_found_geo_region_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production model provider or database object is connected here."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
