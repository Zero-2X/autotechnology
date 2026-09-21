"""SITE-002 adds the tenant-scoped site publication projection."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_site_002"
down_revision = "20260919_found_site_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("site_page_id", sa.String(36), nullable=False),
        sa.Column("site_page_version_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("artifact_hashes", sa.Text, nullable=False),
        sa.Column("manifest", sa.Text, nullable=False),
        sa.Column("generated_at", sa.String(40), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "site_page_version_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "site_page_id"], ["site_pages.org_id", "site_pages.id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_page_version_id"],
            ["site_page_versions.org_id", "site_page_versions.id"],
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_site_publication_version_no"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_site_publication_snapshot_hash"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_site_publication_request_hash"),
        sa.CheckConstraint("status IN ('rendered', 'stale', 'withdrawn')", name="ck_site_publication_status"),
    )
    op.create_index(
        "ix_site_publications_route",
        "site_publications",
        ["org_id", "canonical_url", "locale", "status"],
    )
    op.create_index(
        "ix_site_publications_source",
        "site_publications",
        ["org_id", "site_page_version_id", "generated_at"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER site_publications_identity_immutable BEFORE UPDATE ON site_publications "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR "
            "NEW.site_page_id != OLD.site_page_id OR NEW.site_page_version_id != OLD.site_page_version_id "
            "BEGIN SELECT RAISE(ABORT, 'site publication identity is immutable'); END"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION site_publications_identity_immutable() RETURNS trigger AS $$ "
            "BEGIN IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR "
            "NEW.site_page_id <> OLD.site_page_id OR NEW.site_page_version_id <> OLD.site_page_version_id "
            "THEN RAISE EXCEPTION 'site publication identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER site_publications_identity_immutable BEFORE UPDATE ON site_publications "
            "FOR EACH ROW EXECUTE FUNCTION site_publications_identity_immutable()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS site_publications_identity_immutable ON site_publications")
        op.execute("DROP FUNCTION IF EXISTS site_publications_identity_immutable()")
    op.drop_index("ix_site_publications_source", table_name="site_publications")
    op.drop_index("ix_site_publications_route", table_name="site_publications")
    op.drop_table("site_publications")
