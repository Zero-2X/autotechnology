"""Mark FOUND-012A CI controls; CI policy is file-based and has no DB state."""

revision = "20260918_found_012a"
down_revision = "20260918_found_011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: lockfiles and CI workflow are repository artifacts."""


def downgrade() -> None:
    """No-op: no persistent state was added."""
