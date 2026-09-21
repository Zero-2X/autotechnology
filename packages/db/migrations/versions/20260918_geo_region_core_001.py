"""GEO_REGION-CORE-001 region profiles are validated in the local slice."""

revision = "20260918_found_geo_region_core_001"
down_revision = "20260918_found_account_core_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No production region tables are created by this contract slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
