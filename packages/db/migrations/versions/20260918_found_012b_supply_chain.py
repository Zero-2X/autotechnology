"""FOUND-012B supply-chain evidence is repository metadata, not business data."""

revision = "20260918_found_012b"
down_revision = "20260918_found_003c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No database objects are required for CI supply-chain evidence."""


def downgrade() -> None:
    """Keep the no-op migration reversible for the linear revision chain."""
