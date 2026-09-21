"""Mark FOUND-009 deterministic testkit delivery; no database objects are added."""

revision = "20260918_found_009"
down_revision = "20260918_found_008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: FOUND-009 contains only account-free test infrastructure."""


def downgrade() -> None:
    """No-op: there is no persistent state to remove."""
