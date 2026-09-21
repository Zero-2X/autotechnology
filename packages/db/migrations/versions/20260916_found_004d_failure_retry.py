"""Add append-only task failures and review tasks for retry decisions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_found_004d"
down_revision = "20260916_found_004c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_failures",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_class", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=False),
        sa.Column("message_redacted", sa.String(length=512), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("trace_id", sa.String(length=256), nullable=False),
        sa.Column("occurred_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_count", "error_code", name="uq_task_failures_attempt_code"),
        sa.CheckConstraint(
            "error_class IN ('deterministic', 'transient', 'unknown')",
            name="ck_task_failures_error_class",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_task_failures_attempt_count"),
    )
    op.create_index("idx_task_failures_job", "task_failures", ["org_id", "job_id", "attempt_count"])
    op.create_table(
        "human_tasks",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=64), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("assigned_to", sa.String(length=64), nullable=True),
        sa.Column("claim_lease_until", sa.String(length=64), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("sla_policy_id", sa.String(length=64), nullable=True),
        sa.Column("due_at", sa.String(length=64), nullable=True),
        sa.Column("input_snapshot", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("completed_by", sa.String(length=64), nullable=True),
        sa.Column("override_expires_at", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.Column("completed_at", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "task_type", "aggregate_id", "input_version", name="uq_human_task_unknown_input"),
        sa.CheckConstraint(
            "task_type IN ('approval', 'rights_review', 'policy_review', 'unknown_result', 'support_escalation')",
            name="ck_human_tasks_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'assigned', 'claimed', 'in_progress', 'submitted', 'completed', 'escalated', 'rejected', 'expired', 'cancelled')",
            name="ck_human_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_human_tasks_priority",
        ),
    )
    op.create_index("idx_human_tasks_queue", "human_tasks", ["org_id", "status", "priority", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_human_tasks_queue", table_name="human_tasks")
    op.drop_table("human_tasks")
    op.drop_index("idx_task_failures_job", table_name="task_failures")
    op.drop_table("task_failures")
