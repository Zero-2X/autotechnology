"""Add durable short-lived claim tokens for the legacy task_jobs table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_found_004c"
down_revision = "20260916_found_004b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The accepted FOUND-003D SQL baseline owns task_jobs.  Keeping lease
    # tokens in a separate table lets this revision extend that baseline
    # without rewriting it or requiring a live PostgreSQL connection in CI.
    op.create_table(
        "task_job_leases",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("worker_id", sa.String(length=256), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=False),
        sa.Column("lease_until", sa.String(length=64), nullable=False),
        sa.Column("claimed_at", sa.String(length=64), nullable=False),
        sa.Column("heartbeat_at", sa.String(length=64), nullable=False),
        sa.Column("claim_version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("lease_token", name="uq_task_job_leases_token"),
        sa.CheckConstraint("claim_version >= 1", name="ck_task_job_leases_version"),
    )
    op.create_index(
        "idx_task_job_leases_expiry",
        "task_job_leases",
        ["org_id", "lease_until", "job_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_task_job_leases_expiry", table_name="task_job_leases")
    op.drop_table("task_job_leases")
