"""PROV-003 adds rights enforcement decisions, expiry reminders, and lineage blocks."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_prov_003"
down_revision = "20260918_found_prov_002"
branch_labels = None
depends_on = None


def _sqlite_append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_no_{action.lower()} "
            f"BEFORE {action} ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def _postgres_append_only(table: str) -> None:
    op.execute(
        f"CREATE FUNCTION {table}_immutable() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
    )


def upgrade() -> None:
    op.create_table(
        "rights_guard_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_rights_guard_commands_hash"),
    )
    op.create_table(
        "rights_guard_decisions",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("rights_record_version_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.Text, nullable=False),
        sa.Column("requested_scope", sa.Text, nullable=False),
        sa.Column("checked_at", sa.String(64), nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "rights_record_version_id", "checked_at", "decision", name="uq_rights_guard_decision"),
        sa.ForeignKeyConstraint(
            ["org_id", "rights_record_version_id"],
            ["rights_record_versions.org_id", "rights_record_versions.id"],
            name="fk_rights_guard_decision_version",
        ),
        sa.CheckConstraint("decision IN ('allowed', 'blocked')", name="ck_rights_guard_decision"),
    )
    op.create_table(
        "rights_expiry_reminders",
        sa.Column("reminder_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("rights_record_version_id", sa.String(36), nullable=False),
        sa.Column("valid_to", sa.String(64), nullable=False),
        sa.Column("remind_at", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "rights_record_version_id", "remind_at", name="uq_rights_expiry_reminder"),
        sa.ForeignKeyConstraint(
            ["org_id", "rights_record_version_id"],
            ["rights_record_versions.org_id", "rights_record_versions.id"],
            name="fk_rights_expiry_reminder_version",
        ),
        sa.CheckConstraint("status IN ('scheduled', 'acknowledged', 'cancelled')", name="ck_rights_expiry_status"),
    )
    op.create_table(
        "rights_lineage_edges",
        sa.Column("edge_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("rights_record_version_id", sa.String(36), nullable=False),
        sa.Column("parent_derived_type", sa.String(128), nullable=True),
        sa.Column("parent_derived_id", sa.String(36), nullable=True),
        sa.Column("derived_type", sa.String(128), nullable=False),
        sa.Column("derived_id", sa.String(36), nullable=False),
        sa.Column("relation", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "edge_id", name="uq_rights_lineage_org_edge"),
        sa.UniqueConstraint("org_id", "rights_record_version_id", "derived_type", "derived_id", name="uq_rights_lineage_target"),
        sa.UniqueConstraint("org_id", "derived_type", "derived_id", "parent_derived_type", "parent_derived_id", name="uq_rights_lineage_parent"),
        sa.ForeignKeyConstraint(
            ["org_id", "rights_record_version_id"],
            ["rights_record_versions.org_id", "rights_record_versions.id"],
            name="fk_rights_lineage_version",
        ),
    )
    op.create_index("ix_rights_lineage_parent", "rights_lineage_edges", ["org_id", "parent_derived_type", "parent_derived_id"])
    op.create_index("ix_rights_lineage_rights", "rights_lineage_edges", ["org_id", "rights_record_version_id", "derived_type", "derived_id"])
    op.create_table(
        "rights_derivative_blocks",
        sa.Column("block_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("edge_id", sa.String(36), nullable=False),
        sa.Column("rights_record_version_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(2048), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=True),
        sa.Column("blocked_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "edge_id", "reason", name="uq_rights_derivative_block"),
        sa.ForeignKeyConstraint(
            ["org_id", "edge_id"], ["rights_lineage_edges.org_id", "rights_lineage_edges.edge_id"],
            name="fk_rights_derivative_block_edge",
        ),
        sa.CheckConstraint("length(reason) > 0", name="ck_rights_derivative_block_reason"),
    )
    op.create_index("ix_rights_blocks_org_version", "rights_derivative_blocks", ["org_id", "rights_record_version_id", "blocked_at"])

    dialect = op.get_bind().dialect.name
    tables = (
        "rights_guard_commands", "rights_guard_decisions", "rights_expiry_reminders",
        "rights_lineage_edges", "rights_derivative_blocks",
    )
    if dialect == "sqlite":
        for table in tables:
            _sqlite_append_only(table)
    elif dialect == "postgresql":
        for table in tables:
            _postgres_append_only(table)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    tables = (
        "rights_guard_commands", "rights_guard_decisions", "rights_expiry_reminders",
        "rights_lineage_edges", "rights_derivative_blocks",
    )
    if dialect == "sqlite":
        for table in tables:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
    elif dialect == "postgresql":
        for table in tables:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
    op.drop_index("ix_rights_blocks_org_version", table_name="rights_derivative_blocks")
    op.drop_table("rights_derivative_blocks")
    op.drop_index("ix_rights_lineage_rights", table_name="rights_lineage_edges")
    op.drop_index("ix_rights_lineage_parent", table_name="rights_lineage_edges")
    op.drop_table("rights_lineage_edges")
    op.drop_table("rights_expiry_reminders")
    op.drop_table("rights_guard_decisions")
    op.drop_table("rights_guard_commands")
