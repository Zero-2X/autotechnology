"""Create the append-only migration framework baseline.

This is the first Alembic revision. The previously accepted SQL files are the
legacy database baseline and are intentionally not rewritten into this revision.
New schema changes must add a new revision and follow expand/contract rules.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260916_found_004a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "migration_framework_baselines",
        sa.Column("baseline_key", sa.String(length=64), nullable=False),
        sa.Column("baseline_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("tool", sa.String(length=32), nullable=False),
        sa.Column("revision_naming", sa.String(length=128), nullable=False),
        sa.Column("expand_contract_policy", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("baseline_key", "baseline_version"),
        sa.CheckConstraint(
            "baseline_key = 'migration-framework'",
            name="ck_migration_framework_baseline_key",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_migration_framework_baseline_status",
        ),
        sa.CheckConstraint("tool = 'alembic'", name="ck_migration_framework_tool"),
        sa.CheckConstraint(
            "expand_contract_policy = 'expand_then_contract'",
            name="ck_migration_framework_policy",
        ),
    )
    table = sa.table(
        "migration_framework_baselines",
        sa.column("baseline_key", sa.String()),
        sa.column("baseline_version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("tool", sa.String()),
        sa.column("revision_naming", sa.String()),
        sa.column("expand_contract_policy", sa.String()),
        sa.column("created_at", sa.String()),
    )
    op.bulk_insert(
        table,
        [
            {
                "baseline_key": "migration-framework",
                "baseline_version": 1,
                "status": "active",
                "tool": "alembic",
                "revision_naming": "YYYYMMDD_<task-id>_<slug>.py",
                "expand_contract_policy": "expand_then_contract",
                "created_at": "2026-09-16T00:00:00+08:00",
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("migration_framework_baselines")
