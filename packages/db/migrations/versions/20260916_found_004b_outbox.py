"""Add transactional business-state and Outbox tables for FOUND-004B."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_found_004b"
down_revision = "20260916_found_004a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_states",
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("state_payload", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "aggregate_type", "aggregate_id"),
        sa.CheckConstraint("aggregate_version >= 1", name="ck_business_states_version"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("event_schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.String(length=64), nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=256), nullable=False),
        sa.Column("correlation_id", sa.String(length=256), nullable=True),
        sa.Column("causation_id", sa.String(length=256), nullable=True),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("available_at", sa.String(length=64), nullable=False),
        sa.Column("lease_until", sa.String(length=64), nullable=True),
        sa.Column("locked_by", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_outbox_org_idempotency"),
        sa.CheckConstraint("event_schema_version >= 1", name="ck_outbox_schema_version"),
        sa.CheckConstraint("aggregate_version >= 1", name="ck_outbox_aggregate_version"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_attempt_count"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_outbox_payload_hash"),
        sa.CheckConstraint(
            "actor_type IN ('user', 'service', 'system', 'worker')",
            name="ck_outbox_actor_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'publishing', 'published', 'failed', 'dead_letter')",
            name="ck_outbox_status",
        ),
    )
    op.create_index(
        "idx_outbox_dispatch_ready",
        "outbox_events",
        ["status", "available_at", "event_id"],
    )
    op.create_index(
        "idx_outbox_aggregate_order",
        "outbox_events",
        ["org_id", "aggregate_type", "aggregate_id", "aggregate_version"],
    )


def downgrade() -> None:
    op.drop_index("idx_outbox_aggregate_order", table_name="outbox_events")
    op.drop_index("idx_outbox_dispatch_ready", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("business_states")
