"""Add FOUND-008 feature flags, global kill switch, and control audit facts."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_008"
down_revision = "20260916_found_007d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "foundation_feature_flags",
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("flag_key", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "flag_key"),
        sa.CheckConstraint("version >= 1", name="ck_foundation_feature_flags_version"),
    )
    op.create_table(
        "foundation_kill_switch",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("changed_by", sa.String(length=64), nullable=False),
        sa.Column("changed_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("scope = 'global'", name="ck_foundation_kill_switch_scope"),
        sa.CheckConstraint("status IN ('active', 'paused')", name="ck_foundation_kill_switch_status"),
        sa.CheckConstraint("version >= 1", name="ck_foundation_kill_switch_version"),
    )
    op.create_table(
        "foundation_control_commands",
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("command_type", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_foundation_control_commands_hash"),
    )
    op.create_table(
        "foundation_control_audit",
        sa.Column("audit_id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=256), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=True),
        sa.Column("output_version", sa.Integer(), nullable=True),
        sa.Column("policy_snapshot", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("cost_amount", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
        sa.UniqueConstraint("org_id", "action", "idempotency_key", name="uq_foundation_control_audit_command"),
        sa.CheckConstraint("decision IN ('allow', 'reject', 'changed')", name="ck_foundation_control_audit_decision"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_foundation_control_audit_duration"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_foundation_control_audit_hash"),
    )
    op.create_index(
        "idx_foundation_control_audit_subject",
        "foundation_control_audit",
        ["org_id", "subject_type", "subject_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_foundation_control_audit_subject", table_name="foundation_control_audit")
    op.drop_table("foundation_control_audit")
    op.drop_table("foundation_control_commands")
    op.drop_table("foundation_kill_switch")
    op.drop_table("foundation_feature_flags")
