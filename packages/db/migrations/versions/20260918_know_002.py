"""KNOW-002 KnowledgeCore immutable versions and conflict sets."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_know_002"
down_revision = "20260918_found_know_001"
branch_labels = None
depends_on = None


def _sqlite_append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN "
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
        "knowledge_cores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("topic_brief_id", sa.String(36), nullable=True),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("needs_review", sa.Boolean, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_knowledge_cores_org_id"),
        sa.CheckConstraint("status IN ('draft', 'validated', 'stale', 'archived')", name="ck_knowledge_cores_status"),
        sa.CheckConstraint("needs_review IN (0, 1)", name="ck_knowledge_cores_needs_review"),
    )
    op.create_index("ix_knowledge_cores_org_status", "knowledge_cores", ["org_id", "status", "updated_at"])

    op.create_table(
        "knowledge_core_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("knowledge_core_id", sa.String(36), nullable=False),
        sa.Column("topic_brief_id", sa.String(36), nullable=True),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("entity_ids_json", sa.Text, nullable=False),
        sa.Column("claim_ids_json", sa.Text, nullable=False),
        sa.Column("evidence_ids_json", sa.Text, nullable=False),
        sa.Column("conflict_set_ids_json", sa.Text, nullable=False),
        sa.Column("freshness_checked_at", sa.String(64), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_knowledge_core_versions_org_id"),
        sa.UniqueConstraint("org_id", "knowledge_core_id", "version_no", name="uq_knowledge_core_versions_no"),
        sa.ForeignKeyConstraint(["org_id", "knowledge_core_id"], ["knowledge_cores.org_id", "knowledge_cores.id"], name="fk_knowledge_core_versions_core"),
        sa.CheckConstraint("version_no >= 1", name="ck_knowledge_core_versions_no"),
        sa.CheckConstraint("status IN ('draft', 'verified', 'superseded', 'withdrawn', 'needs_review')", name="ck_knowledge_core_versions_status"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_knowledge_core_versions_snapshot_hash"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_knowledge_core_versions_content_hash"),
    )
    op.create_index("ix_knowledge_core_versions_current", "knowledge_core_versions", ["org_id", "knowledge_core_id", "version_no", "status"])

    op.create_table(
        "knowledge_conflict_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("conflict_key", sa.String(512), nullable=False),
        sa.Column("claim_ids_json", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_knowledge_conflict_sets_org_id"),
        sa.UniqueConstraint("org_id", "conflict_key", name="uq_knowledge_conflict_sets_key"),
        sa.CheckConstraint("status IN ('needs_review', 'resolved', 'dismissed')", name="ck_knowledge_conflict_sets_status"),
    )
    op.create_index("ix_knowledge_conflict_sets_org_status", "knowledge_conflict_sets", ["org_id", "status", "created_at"])

    op.create_table(
        "knowledge_core_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_knowledge_core_commands_hash"),
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("knowledge_core_versions", "knowledge_conflict_sets", "knowledge_core_commands"):
            _sqlite_append_only(table)
        op.execute(
            "CREATE TRIGGER knowledge_cores_immutable_fields BEFORE UPDATE ON knowledge_cores "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.topic_brief_id IS NOT OLD.topic_brief_id "
            "OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
            "BEGIN SELECT RAISE(ABORT, 'knowledge core identity is immutable'); END"
        )
    elif dialect == "postgresql":
        for table in ("knowledge_core_versions", "knowledge_conflict_sets", "knowledge_core_commands"):
            _postgres_append_only(table)
        op.execute("CREATE FUNCTION knowledge_cores_immutable_fields() RETURNS trigger AS $$ BEGIN IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.topic_brief_id IS DISTINCT FROM OLD.topic_brief_id OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at THEN RAISE EXCEPTION 'knowledge core identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER knowledge_cores_immutable_fields BEFORE UPDATE ON knowledge_cores FOR EACH ROW EXECUTE FUNCTION knowledge_cores_immutable_fields()")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("knowledge_core_versions", "knowledge_conflict_sets", "knowledge_core_commands"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute("DROP TRIGGER IF EXISTS knowledge_cores_immutable_fields")
    elif dialect == "postgresql":
        for table in ("knowledge_core_versions", "knowledge_conflict_sets", "knowledge_core_commands"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        op.execute("DROP TRIGGER IF EXISTS knowledge_cores_immutable_fields ON knowledge_cores")
        op.execute("DROP FUNCTION IF EXISTS knowledge_cores_immutable_fields()")
    op.drop_table("knowledge_core_commands")
    op.drop_index("ix_knowledge_conflict_sets_org_status", table_name="knowledge_conflict_sets")
    op.drop_table("knowledge_conflict_sets")
    op.drop_index("ix_knowledge_core_versions_current", table_name="knowledge_core_versions")
    op.drop_table("knowledge_core_versions")
    op.drop_index("ix_knowledge_cores_org_status", table_name="knowledge_cores")
    op.drop_table("knowledge_cores")
