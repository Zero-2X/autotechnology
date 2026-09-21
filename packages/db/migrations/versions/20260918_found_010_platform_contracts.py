"""Mark FOUND-010 platform contracts; persistence belongs to later owners."""

revision = "20260918_found_010"
down_revision = "20260918_found_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: this task freezes contracts and ports only."""


def downgrade() -> None:
    """No-op: no persistent state was created."""
