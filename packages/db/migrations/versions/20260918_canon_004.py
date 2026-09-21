"""CANON-004 persist Claim, Evidence and RightsRecordVersion bindings."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_canon_004"
down_revision = "20260918_found_canon_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("canonical_claims") as batch:
        batch.add_column(sa.Column("claim_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("priority", sa.String(16), nullable=False, server_default=sa.text("'normal'")))
        batch.add_column(sa.Column("evidence_ids_json", sa.Text, nullable=False, server_default=sa.text("'[]'")))
        batch.add_column(sa.Column("rights_snapshot_ids_json", sa.Text, nullable=False, server_default=sa.text("'[]'")))
        batch.create_check_constraint("ck_canonical_claims_priority", "priority IN ('low', 'normal', 'high', 'urgent')")
    op.create_index("ix_canonical_claims_claim", "canonical_claims", ["org_id", "claim_id", "canonical_content_version_id"])


def downgrade() -> None:
    op.drop_index("ix_canonical_claims_claim", table_name="canonical_claims")
    with op.batch_alter_table("canonical_claims") as batch:
        batch.drop_constraint("ck_canonical_claims_priority", type_="check")
        batch.drop_column("rights_snapshot_ids_json")
        batch.drop_column("evidence_ids_json")
        batch.drop_column("priority")
        batch.drop_column("claim_id")
