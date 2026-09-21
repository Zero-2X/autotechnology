"""SITE-001 adds tenant-scoped immutable site page versions and commands."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_site_001"
down_revision = "20260919_found_model_003"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = ("site_page_versions", "site_page_commands")


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
        "site_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("page_key", sa.String(128), nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("url_path", sa.String(2048), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "page_key"),
        sa.CheckConstraint("length(page_key) >= 2", name="ck_site_page_key"),
        sa.CheckConstraint("length(url_path) >= 1", name="ck_site_page_url"),
    )
    op.create_table(
        "site_page_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("site_page_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("canonical_content_version_id", sa.String(36), nullable=False),
        sa.Column("variant_version_id", sa.String(36), nullable=True),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("url_path", sa.String(2048), nullable=False),
        sa.Column("render_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("published_at", sa.String(40), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "site_page_id", "version_no"),
        sa.ForeignKeyConstraint(["org_id", "site_page_id"], ["site_pages.org_id", "site_pages.id"]),
        sa.ForeignKeyConstraint(
            ["org_id", "canonical_content_version_id"],
            ["canonical_content_versions.org_id", "canonical_content_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "variant_version_id"],
            ["variant_versions.org_id", "variant_versions.id"],
        ),
        # GEO_REGION-001 is a later revision.  Its tenant foreign key is
        # attached there after the referenced table exists; keeping this
        # inline would make PostgreSQL replay fail on an unavailable table.
        sa.CheckConstraint("version_no >= 1", name="ck_site_page_version_no"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_site_page_snapshot_hash"),
        sa.CheckConstraint("render_mode IN ('ssr', 'static')", name="ck_site_page_render_mode"),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'published', 'superseded', 'rolled_back')",
            name="ck_site_page_version_status",
        ),
    )
    op.create_table(
        "site_page_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_site_page_command_hash"),
        sa.ForeignKeyConstraint(["org_id", "result_id"], ["site_page_versions.org_id", "site_page_versions.id"]),
    )
    op.create_index("ix_site_page_versions_path", "site_page_versions", ["org_id", "url_path", "locale", "version_no"])
    op.create_index("ix_site_page_versions_source", "site_page_versions", ["org_id", "canonical_content_version_id", "created_at"])
    op.create_index("ix_site_pages_current", "site_pages", ["org_id", "current_version_id"])
    for table in IMMUTABLE_TABLES:
        _append_only(table)
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER site_pages_identity_immutable BEFORE UPDATE ON site_pages "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.page_key != OLD.page_key "
            "BEGIN SELECT RAISE(ABORT, 'site page identity is immutable'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION site_pages_identity_immutable() RETURNS trigger AS $$ "
            "BEGIN IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.page_key <> OLD.page_key "
            "THEN RAISE EXCEPTION 'site page identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER site_pages_identity_immutable BEFORE UPDATE ON site_pages "
            "FOR EACH ROW EXECUTE FUNCTION site_pages_identity_immutable()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER site_pages_identity_immutable ON site_pages")
        op.execute("DROP FUNCTION site_pages_identity_immutable()")
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION {table}_immutable()")
    op.drop_index("ix_site_pages_current", table_name="site_pages")
    op.drop_index("ix_site_page_versions_source", table_name="site_page_versions")
    op.drop_index("ix_site_page_versions_path", table_name="site_page_versions")
    op.drop_table("site_page_commands")
    op.drop_table("site_page_versions")
    op.drop_table("site_pages")
