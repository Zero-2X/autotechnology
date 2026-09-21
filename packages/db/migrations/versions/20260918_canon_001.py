"""CANON-001 canonical content roots and immutable editorial versions."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_canon_001"
down_revision = "20260918_found_know_002"
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
        "canonical_contents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("topic_brief_id", sa.String(36), nullable=False),
        sa.Column("stable_key", sa.String(256), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_canonical_contents_org_id"),
        sa.UniqueConstraint("org_id", "stable_key", name="uq_canonical_contents_stable_key"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'archived')", name="ck_canonical_contents_status"),
    )
    op.create_index("ix_canonical_contents_org_status", "canonical_contents", ["org_id", "status", "updated_at"])

    op.create_table(
        "canonical_content_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_id", sa.String(36), nullable=False),
        sa.Column("topic_brief_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("abstract", sa.Text, nullable=False),
        sa.Column("sections_json", sa.Text, nullable=False),
        sa.Column("claims_json", sa.Text, nullable=False),
        sa.Column("code_blocks_json", sa.Text, nullable=False),
        sa.Column("examples_json", sa.Text, nullable=False),
        sa.Column("limitations_json", sa.Text, nullable=False),
        sa.Column("source_snapshot_refs_json", sa.Text, nullable=False),
        sa.Column("knowledge_core_version_id", sa.String(36), nullable=True),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("rights_snapshot_ids_json", sa.Text, nullable=False),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_canonical_versions_org_id"),
        sa.UniqueConstraint("org_id", "canonical_content_id", "version_no", name="uq_canonical_versions_no"),
        sa.ForeignKeyConstraint(["org_id", "canonical_content_id"], ["canonical_contents.org_id", "canonical_contents.id"], name="fk_canonical_versions_root"),
        sa.CheckConstraint("version_no >= 1", name="ck_canonical_versions_no"),
        sa.CheckConstraint("status IN ('draft', 'evidence_pending', 'fact_checked', 'approved', 'superseded', 'withdrawn')", name="ck_canonical_versions_status"),
        sa.CheckConstraint("length(input_snapshot_hash) = 64", name="ck_canonical_versions_input_hash"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_canonical_versions_content_hash"),
    )
    op.create_index("ix_canonical_versions_current", "canonical_content_versions", ["org_id", "canonical_content_id", "version_no", "status"])

    op.create_table(
        "canonical_claims",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_version_id", sa.String(36), nullable=False),
        sa.Column("claim_key", sa.String(256), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("claim_json", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "canonical_content_version_id", "claim_key"),
        sa.ForeignKeyConstraint(["org_id", "canonical_content_version_id"], ["canonical_content_versions.org_id", "canonical_content_versions.id"], name="fk_canonical_claims_version"),
        sa.CheckConstraint("position >= 1", name="ck_canonical_claims_position"),
    )
    op.create_index("ix_canonical_claims_version", "canonical_claims", ["org_id", "canonical_content_version_id", "position"])

    op.create_table(
        "canonical_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_canonical_commands_hash"),
    )
    op.create_table(
        "canonical_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("aggregate_type", sa.String(128), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "aggregate_type", "aggregate_id", "sequence", name="uq_canonical_events_sequence"),
    )
    op.create_index("ix_canonical_events_aggregate", "canonical_events", ["org_id", "aggregate_type", "aggregate_id", "sequence"])

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("canonical_content_versions", "canonical_claims", "canonical_commands", "canonical_events"):
            _sqlite_append_only(table)
        op.execute(
            "CREATE TRIGGER canonical_contents_immutable_identity BEFORE UPDATE ON canonical_contents "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.topic_brief_id != OLD.topic_brief_id "
            "OR NEW.stable_key != OLD.stable_key OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
            "BEGIN SELECT RAISE(ABORT, 'canonical content identity is immutable'); END"
        )
    elif dialect == "postgresql":
        for table in ("canonical_content_versions", "canonical_claims", "canonical_commands", "canonical_events"):
            _postgres_append_only(table)
        op.execute(
            "CREATE FUNCTION canonical_contents_immutable_identity() RETURNS trigger AS $$ BEGIN "
            "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.topic_brief_id <> OLD.topic_brief_id "
            "OR NEW.stable_key <> OLD.stable_key OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at "
            "THEN RAISE EXCEPTION 'canonical content identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER canonical_contents_immutable_identity BEFORE UPDATE ON canonical_contents "
            "FOR EACH ROW EXECUTE FUNCTION canonical_contents_immutable_identity()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("canonical_content_versions", "canonical_claims", "canonical_commands", "canonical_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute("DROP TRIGGER IF EXISTS canonical_contents_immutable_identity")
    elif dialect == "postgresql":
        for table in ("canonical_content_versions", "canonical_claims", "canonical_commands", "canonical_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        op.execute("DROP TRIGGER IF EXISTS canonical_contents_immutable_identity ON canonical_contents")
        op.execute("DROP FUNCTION IF EXISTS canonical_contents_immutable_identity()")
    op.drop_index("ix_canonical_events_aggregate", table_name="canonical_events")
    op.drop_table("canonical_events")
    op.drop_table("canonical_commands")
    op.drop_index("ix_canonical_claims_version", table_name="canonical_claims")
    op.drop_table("canonical_claims")
    op.drop_index("ix_canonical_versions_current", table_name="canonical_content_versions")
    op.drop_table("canonical_content_versions")
    op.drop_index("ix_canonical_contents_org_status", table_name="canonical_contents")
    op.drop_table("canonical_contents")
