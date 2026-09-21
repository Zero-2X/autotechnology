"""FEEDBACK-CORE-002 records fake/manual observation recommendations."""

revision = "20260919_found_feedback_core_002"
down_revision = "20260919_found_dist_011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: the local slice composes existing feedback contracts."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
