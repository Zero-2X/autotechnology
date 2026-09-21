"""QA-003 sandbox runs are retained by the existing QA evidence projection."""

revision = "20260919_found_qa_003"
down_revision = "20260919_found_qa_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: this slice retains sandbox evidence in the service projection."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
