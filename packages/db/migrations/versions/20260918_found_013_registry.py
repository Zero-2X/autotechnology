"""Mark FOUND-013 registry validation; registry state is a repository artifact."""

revision = "20260918_found_013"
down_revision = "20260918_found_012a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: task registry validation does not create database state."""


def downgrade() -> None:
    """No-op: no persistent state was added."""
