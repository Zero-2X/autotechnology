"""GEO_CONTENT-003 immutable offline multi-sample run projection."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_geo_content_003"
down_revision = "20260919_geo_content_002"
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
        "geo_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("page_version_id", sa.String(36), nullable=False),
        sa.Column("query_fixture_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("region", sa.String(128), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("mention_count", sa.Integer, nullable=False),
        sa.Column("citation_count", sa.Integer, nullable=False),
        sa.Column("position_values", sa.Text, nullable=False),
        sa.Column("correctness_values", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("data_quality", sa.String(16), nullable=False),
        sa.Column("fixture_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        # Kept nullable for migration compatibility.  It is deliberately
        # restricted to the empty object below: the public GeoRun contract is
        # exactly the 17 columns above and raw answer bodies never belong in
        # this table.
        sa.Column("payload", sa.Text, nullable=True),
        sa.UniqueConstraint("org_id", "id"),
        sa.ForeignKeyConstraint(
            ["org_id", "page_version_id"],
            ["site_page_versions.org_id", "site_page_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "query_fixture_id"],
            ["geo_query_fixtures.org_id", "geo_query_fixtures.id"],
        ),
        sa.CheckConstraint(
            "sample_count >= 2 AND sample_count <= 100",
            name="ck_geo_run_sample_count",
        ),
        sa.CheckConstraint(
            "mention_count >= 0 AND mention_count <= sample_count",
            name="ck_geo_run_mention_count",
        ),
        sa.CheckConstraint(
            "citation_count >= 0 AND citation_count <= sample_count",
            name="ck_geo_run_citation_count",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_geo_run_confidence",
        ),
        sa.CheckConstraint(
            "data_quality = 'estimated'",
            name="ck_geo_run_data_quality",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'running', 'succeeded', 'failed')",
            name="ck_geo_run_status",
        ),
        sa.CheckConstraint("length(fixture_hash) = 64", name="ck_geo_run_fixture_hash"),
        sa.CheckConstraint(
            "payload IS NULL OR payload = '{}'",
            name="ck_geo_run_payload_empty",
        ),
    )
    op.create_index(
        "ix_geo_runs_fixture",
        "geo_runs",
        ["org_id", "query_fixture_id", "created_at"],
    )
    op.create_index(
        "ix_geo_runs_page_status",
        "geo_runs",
        ["org_id", "page_version_id", "status", "created_at"],
    )
    _append_only("geo_runs")
    # SQLite leaves declared foreign keys disabled unless every connection
    # opts into PRAGMA enforcement.  These insert guards keep the tenant
    # boundary effective in disposable/local databases as well as PostgreSQL.
    if op.get_bind().dialect.name == "sqlite":
        # ``INSERT OR REPLACE`` can internally delete a conflicting row while
        # SQLite recursive delete triggers are disabled.  An explicit insert
        # guard closes that replacement path as well.
        op.execute(
            "CREATE TRIGGER geo_runs_no_replace BEFORE INSERT ON geo_runs "
            "WHEN EXISTS (SELECT 1 FROM geo_runs WHERE id = NEW.id) "
            "BEGIN SELECT RAISE(ABORT, 'geo_runs is append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER geo_runs_require_page_version BEFORE INSERT ON geo_runs "
            "WHEN NOT EXISTS (SELECT 1 FROM site_page_versions "
            "WHERE org_id = NEW.org_id AND id = NEW.page_version_id AND locale = NEW.locale "
            "AND status IN ('ready', 'published')) "
            "BEGIN SELECT RAISE(ABORT, 'geo_runs page version tenant reference invalid'); END"
        )
        op.execute(
            "CREATE TRIGGER geo_runs_require_query_fixture BEFORE INSERT ON geo_runs "
            "WHEN NOT EXISTS (SELECT 1 FROM geo_query_fixtures "
            "WHERE org_id = NEW.org_id AND id = NEW.query_fixture_id "
            "AND fixture_hash = NEW.fixture_hash AND locale = NEW.locale "
            "AND region = NEW.region AND status = 'active') "
            "BEGIN SELECT RAISE(ABORT, 'geo_runs query fixture tenant reference invalid'); END"
        )
        op.execute(
            "CREATE TRIGGER geo_runs_require_json_arrays BEFORE INSERT ON geo_runs "
            "WHEN json_valid(NEW.position_values) = 0 "
            "OR json_type(NEW.position_values) != 'array' "
            "OR EXISTS (SELECT 1 FROM json_each(NEW.position_values) "
            "WHERE type != 'integer' OR value < 1) "
            "OR (SELECT count(*) FROM json_each(NEW.position_values)) != "
            "(SELECT count(DISTINCT value) FROM json_each(NEW.position_values)) "
            "OR EXISTS (SELECT 1 FROM json_each(NEW.position_values) AS current "
            "JOIN json_each(NEW.position_values) AS previous "
            "ON CAST(previous.key AS INTEGER) = CAST(current.key AS INTEGER) - 1 "
            "WHERE current.value <= previous.value) "
            "OR json_valid(NEW.correctness_values) = 0 "
            "OR json_type(NEW.correctness_values) != 'array' "
            "OR json_array_length(NEW.correctness_values) < 1 "
            "OR EXISTS (SELECT 1 FROM json_each(NEW.correctness_values) "
            "WHERE type != 'text' OR value NOT IN ('correct', 'incorrect', 'unknown')) "
            "OR (SELECT count(*) FROM json_each(NEW.correctness_values)) != "
            "(SELECT count(DISTINCT value) FROM json_each(NEW.correctness_values)) "
            "OR NEW.data_quality != 'estimated' "
            "OR (NEW.payload IS NOT NULL AND (json_valid(NEW.payload) = 0 OR NEW.payload != '{}')) "
            "BEGIN SELECT RAISE(ABORT, 'geo_runs JSON projection invalid'); END"
        )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION geo_runs_validate_binding() RETURNS trigger AS $$ "
            "BEGIN "
            "IF NEW.data_quality <> 'estimated' THEN "
            "RAISE EXCEPTION 'geo_runs data quality must be estimated'; END IF; "
            "IF NOT EXISTS (SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
            "AND id = NEW.page_version_id AND locale = NEW.locale "
            "AND status IN ('ready', 'published')) THEN "
            "RAISE EXCEPTION 'geo_runs page version tenant reference invalid'; END IF; "
            "IF NOT EXISTS (SELECT 1 FROM geo_query_fixtures WHERE org_id = NEW.org_id "
            "AND id = NEW.query_fixture_id AND fixture_hash = NEW.fixture_hash "
            "AND locale = NEW.locale AND region = NEW.region AND status = 'active') THEN "
            "RAISE EXCEPTION 'geo_runs query fixture tenant reference invalid'; END IF; "
            "IF jsonb_typeof(NEW.position_values::jsonb) <> 'array' "
            "OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.position_values::jsonb) AS item "
            "WHERE jsonb_typeof(item) <> 'number' OR (item::text !~ '^[1-9][0-9]*$')) "
            "OR EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.position_values::jsonb) WITH ORDINALITY AS current(item, ord) "
            "JOIN jsonb_array_elements(NEW.position_values::jsonb) WITH ORDINALITY AS previous(item, ord) "
            "ON previous.ord = current.ord - 1 WHERE (current.item::text)::integer <= (previous.item::text)::integer) "
            "OR jsonb_typeof(NEW.correctness_values::jsonb) <> 'array' "
            "OR jsonb_array_length(NEW.correctness_values::jsonb) < 1 "
            "OR jsonb_array_length(NEW.correctness_values::jsonb) > 3 "
            "OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(NEW.correctness_values::jsonb) AS item "
            "WHERE item NOT IN ('correct', 'incorrect', 'unknown')) "
            "OR (SELECT count(*) FROM jsonb_array_elements_text(NEW.correctness_values::jsonb)) <> "
            "(SELECT count(DISTINCT item) FROM jsonb_array_elements_text(NEW.correctness_values::jsonb)) "
            "OR (NEW.payload IS NOT NULL AND NEW.payload <> '{}') THEN "
            "RAISE EXCEPTION 'geo_runs JSON projection invalid'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER geo_runs_validate_binding BEFORE INSERT ON geo_runs "
            "FOR EACH ROW EXECUTE FUNCTION geo_runs_validate_binding()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS geo_runs_validate_binding ON geo_runs")
        op.execute("DROP FUNCTION IF EXISTS geo_runs_validate_binding()")
        op.execute("DROP TRIGGER IF EXISTS geo_runs_no_mutation ON geo_runs")
        op.execute("DROP FUNCTION IF EXISTS geo_runs_immutable()")
    op.drop_index("ix_geo_runs_page_status", table_name="geo_runs")
    op.drop_index("ix_geo_runs_fixture", table_name="geo_runs")
    op.drop_table("geo_runs")
