"""QA-001 deterministic checks are a read-only report projection."""

revision = "20260919_found_qa_001"
down_revision = "20260919_found_prod_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: QA reports remain an account-free projection in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
