"""Mark FOUND-003C optional Redis capability; no business tables are created."""

revision = "20260918_found_003c"
down_revision = "20260918_found_013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: Redis capability is configured and tested through ports."""


def downgrade() -> None:
    """No-op: no persistent state was added."""
