"""POLICY-001 keeps deterministic decisions in the policy projection."""

revision = "20260919_found_policy_001"
down_revision = "20260919_found_qa_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No business table: PolicyDecision is an append-only projection in this slice."""


def downgrade() -> None:
    """Keep the revision chain reversible."""
