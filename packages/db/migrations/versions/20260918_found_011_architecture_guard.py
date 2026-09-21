"""Mark FOUND-011 static architecture gate; no persistent state is created."""

revision = "20260918_found_011"
down_revision = "20260918_gov_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: architecture and smoke rules are file-based."""


def downgrade() -> None:
    """No-op: no table or data was added."""
