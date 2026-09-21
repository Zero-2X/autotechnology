"""CANON-006 record immutable lineage query snapshots and audit context."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_canon_006"
down_revision = "20260918_found_canon_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_lineage_queries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_canonical_lineage_request_hash"),
        sa.CheckConstraint("length(query_hash) = 64", name="ck_canonical_lineage_query_hash"),
        sa.CheckConstraint("subject_type IN ('canonical_content', 'canonical_content_version')", name="ck_canonical_lineage_subject_type"),
    )
    op.create_index("ix_canonical_lineage_subject", "canonical_lineage_queries", ["org_id", "subject_type", "subject_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_canonical_lineage_subject", table_name="canonical_lineage_queries")
    op.drop_table("canonical_lineage_queries")
