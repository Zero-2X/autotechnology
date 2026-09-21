"""PROD-002 stable ContentVariant roots, immutable versions, and audit records."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_prod_002"
down_revision = "20260919_found_prod_001"
branch_labels = None
depends_on = None


def _append_only(table: str) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
            )
    elif dialect == "postgresql":
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
        "content_variants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(64), nullable=False),
        sa.Column("market", sa.String(64), nullable=False),
        sa.Column("audience", sa.String(256), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "canonical_content_id", "locale", "market", "audience"),
        sa.ForeignKeyConstraint(["org_id", "canonical_content_id"], ["canonical_contents.org_id", "canonical_contents.id"]),
        sa.CheckConstraint("status IN ('draft', 'active', 'withdrawn', 'retired')", name="ck_content_variant_status"),
    )
    op.create_table(
        "variant_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("content_variant_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_version_id", sa.String(36), nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("source_map_json", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "content_variant_id", "version_no"),
        sa.ForeignKeyConstraint(["org_id", "content_variant_id"], ["content_variants.org_id", "content_variants.id"]),
        sa.ForeignKeyConstraint(["org_id", "canonical_content_version_id"], ["canonical_content_versions.org_id", "canonical_content_versions.id"]),
        sa.CheckConstraint("version_no >= 1", name="ck_variant_version_no"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_variant_snapshot_hash"),
        sa.CheckConstraint("status IN ('planned', 'draft', 'localized', 'qa_pending', 'approved', 'withdrawn')", name="ck_variant_version_status"),
    )
    op.create_table(
        "variant_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_variant_command_hash"),
    )
    op.create_table(
        "variant_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
    )
    op.create_index("ix_variants_source", "content_variants", ["org_id", "canonical_content_id", "locale", "market"])
    op.create_index("ix_variant_versions_canonical", "variant_versions", ["org_id", "canonical_content_version_id", "created_at"])
    for table in ("variant_versions", "variant_commands", "variant_events"):
        _append_only(table)
    if op.get_bind().dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER content_variants_immutable_identity BEFORE " + "UPDATE " + "ON content_variants "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR "
            "NEW.canonical_content_id != OLD.canonical_content_id OR NEW.locale != OLD.locale OR "
            "NEW.market != OLD.market OR NEW.audience != OLD.audience "
            "BEGIN SELECT RAISE(ABORT, 'variant identity is immutable'); END"
        )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION content_variants_identity_immutable() RETURNS trigger AS $$ "
            "BEGIN IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR "
            "NEW.canonical_content_id <> OLD.canonical_content_id OR NEW.locale <> OLD.locale OR "
            "NEW.market <> OLD.market OR NEW.audience <> OLD.audience THEN "
            "RAISE EXCEPTION 'variant identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER content_variants_immutable_identity BEFORE UPDATE ON content_variants "
            "FOR EACH ROW EXECUTE FUNCTION content_variants_identity_immutable()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER content_variants_immutable_identity ON content_variants")
        op.execute("DROP FUNCTION content_variants_identity_immutable()")
    for table in ("variant_versions", "variant_commands", "variant_events"):
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION {table}_immutable()")
    op.drop_index("ix_variant_versions_canonical", table_name="variant_versions")
    op.drop_index("ix_variants_source", table_name="content_variants")
    op.drop_table("variant_events")
    op.drop_table("variant_commands")
    op.drop_table("variant_versions")
    op.drop_table("content_variants")
