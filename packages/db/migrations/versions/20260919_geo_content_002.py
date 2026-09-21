"""GEO_CONTENT-002 immutable prompt/query fixture projection.

Commands, transition events, and compliance samples are application ports in
the account-free slice.  This revision owns only the durable fixture facts;
GEO_CONTENT-003 owns ``geo_runs`` in its later revision.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_geo_content_002"
down_revision = "20260919_geo_content_001"
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
        "geo_query_fixtures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("region", sa.String(128), nullable=False),
        sa.Column("expected_entities", sa.Text, nullable=False),
        sa.Column("expected_claim_ids", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("fixture_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.String(40), nullable=True),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "fixture_hash"),
        sa.CheckConstraint("status IN ('created', 'active', 'retired')", name="ck_geo_query_fixture_status"),
        sa.CheckConstraint("version >= 1", name="ck_geo_query_fixture_version"),
        sa.CheckConstraint("length(fixture_hash) = 64", name="ck_geo_query_fixture_hash"),
    )
    op.create_index(
        "ix_geo_query_fixtures_status",
        "geo_query_fixtures",
        ["org_id", "status", "created_at"],
    )
    op.create_index(
        "ix_geo_query_fixtures_lookup",
        "geo_query_fixtures",
        ["org_id", "locale", "region", "status"],
    )
    _append_only("geo_query_fixtures")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS geo_query_fixtures_no_mutation ON geo_query_fixtures")
        op.execute("DROP FUNCTION IF EXISTS geo_query_fixtures_immutable()")
    op.drop_index("ix_geo_query_fixtures_lookup", table_name="geo_query_fixtures")
    op.drop_index("ix_geo_query_fixtures_status", table_name="geo_query_fixtures")
    op.drop_table("geo_query_fixtures")
