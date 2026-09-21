"""SITE-004 append-only site quality report projections."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_site_004"
down_revision = "20260920_geo_region_002"
branch_labels = None
depends_on = None


def _sqlite_triggers() -> None:
    op.execute(
        "CREATE TRIGGER site_quality_reports_no_replace BEFORE INSERT ON site_quality_reports "
        "WHEN EXISTS (SELECT 1 FROM site_quality_reports WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'site_quality_reports is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER site_quality_reports_no_update BEFORE UPDATE ON site_quality_reports "
        "BEGIN SELECT RAISE(ABORT, 'site_quality_reports is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER site_quality_reports_no_delete BEFORE DELETE ON site_quality_reports "
        "BEGIN SELECT RAISE(ABORT, 'site_quality_reports is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER site_quality_reports_require_page BEFORE INSERT ON site_quality_reports "
        "WHEN NOT EXISTS (SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.site_page_version_id AND status IN ('ready', 'published')) "
        "BEGIN SELECT RAISE(ABORT, 'site quality page tenant reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER site_quality_reports_validate_json BEFORE INSERT ON site_quality_reports "
        "WHEN json_valid(NEW.thresholds_json) = 0 OR json_type(NEW.thresholds_json) != 'object' "
        "OR json_valid(NEW.metrics_json) = 0 OR json_type(NEW.metrics_json) != 'object' "
        "OR json_valid(NEW.checks_json) = 0 OR json_type(NEW.checks_json) != 'array' "
        "OR json_valid(NEW.findings_json) = 0 OR json_type(NEW.findings_json) != 'array' "
        "OR json_valid(NEW.summary_json) = 0 OR json_type(NEW.summary_json) != 'object' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"html\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"body\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"payload\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"dom\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"headers\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"cookies\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"authorization\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"token\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"secret\"%' "
        "OR lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "LIKE '%\"password\"%' "
        "BEGIN SELECT RAISE(ABORT, 'site quality JSON contains raw content or credentials'); END"
    )
    op.execute(
        "CREATE TRIGGER site_quality_reports_validate_hashes BEFORE INSERT ON site_quality_reports "
        "WHEN length(NEW.input_snapshot_hash) != 64 OR NEW.input_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.source_html_hash) != 64 OR NEW.source_html_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR (NEW.dynamic_html_hash IS NOT NULL AND (length(NEW.dynamic_html_hash) != 64 OR NEW.dynamic_html_hash GLOB '*[^0-9A-Fa-f]*')) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.report_hash) != 64 OR NEW.report_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'site quality hash projection invalid'); END"
    )


def _postgres_triggers() -> None:
    op.execute(
        "CREATE FUNCTION site_quality_reports_guard() RETURNS trigger AS $$ "
        "BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN "
        "RAISE EXCEPTION 'site_quality_reports is append-only'; END IF; "
        "IF NOT EXISTS (SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.site_page_version_id AND status IN ('ready', 'published')) THEN "
        "RAISE EXCEPTION 'site quality page tenant reference invalid'; END IF; "
        "IF jsonb_typeof(NEW.thresholds_json::jsonb) <> 'object' "
        "OR jsonb_typeof(NEW.metrics_json::jsonb) <> 'object' "
        "OR jsonb_typeof(NEW.checks_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.findings_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.summary_json::jsonb) <> 'object' THEN "
        "RAISE EXCEPTION 'site quality JSON projection invalid'; END IF; "
        "IF NEW.input_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR NEW.source_html_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR (NEW.dynamic_html_hash IS NOT NULL AND NEW.dynamic_html_hash !~ '^[0-9A-Fa-f]{64}$') "
        "OR NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR NEW.report_hash !~ '^[0-9A-Fa-f]{64}$' THEN "
        "RAISE EXCEPTION 'site quality hash projection invalid'; END IF; "
        "IF lower(NEW.thresholds_json || NEW.metrics_json || NEW.checks_json || NEW.findings_json || NEW.summary_json) "
        "~ '\"(html|body|payload|dom|headers|cookies|authorization|token|secret|password)\"' THEN "
        "RAISE EXCEPTION 'site quality JSON contains raw content or credentials'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER site_quality_reports_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON site_quality_reports "
        "FOR EACH ROW EXECUTE FUNCTION site_quality_reports_guard()"
    )


def upgrade() -> None:
    op.create_table(
        "site_quality_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("site_page_version_id", sa.String(36), nullable=False),
        sa.Column("page_key", sa.String(512), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("threshold_version", sa.String(128), nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("source_html_hash", sa.String(64), nullable=False),
        sa.Column("dynamic_html_hash", sa.String(64), nullable=True),
        sa.Column("thresholds_json", sa.Text, nullable=False),
        sa.Column("metrics_json", sa.Text, nullable=False),
        sa.Column("checks_json", sa.Text, nullable=False),
        sa.Column("findings_json", sa.Text, nullable=False),
        sa.Column("summary_json", sa.Text, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("evaluated_at", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "idempotency_key", name="uq_site_quality_reports_idempotency"),
        sa.ForeignKeyConstraint(
            ["org_id", "site_page_version_id"],
            ["site_page_versions.org_id", "site_page_versions.id"],
            name="fk_site_quality_reports_page_version",
        ),
        sa.CheckConstraint("status IN ('passed', 'blocked', 'manual_review')", name="ck_site_quality_report_status"),
        sa.CheckConstraint("rule_version = 'site-004.v1'", name="ck_site_quality_rule_version"),
        sa.CheckConstraint("length(input_snapshot_hash) = 64", name="ck_site_quality_input_hash"),
        sa.CheckConstraint("length(source_html_hash) = 64", name="ck_site_quality_html_hash"),
        sa.CheckConstraint("dynamic_html_hash IS NULL OR length(dynamic_html_hash) = 64", name="ck_site_quality_dynamic_hash"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_site_quality_request_hash"),
        sa.CheckConstraint("length(report_hash) = 64", name="ck_site_quality_report_hash"),
    )
    op.create_index(
        "ix_site_quality_reports_page",
        "site_quality_reports",
        ["org_id", "site_page_version_id", "evaluated_at"],
    )
    op.create_index(
        "ix_site_quality_reports_status",
        "site_quality_reports",
        ["org_id", "status", "evaluated_at"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _sqlite_triggers()
    elif dialect == "postgresql":
        _postgres_triggers()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for name in (
            "site_quality_reports_validate_hashes",
            "site_quality_reports_validate_json",
            "site_quality_reports_require_page",
            "site_quality_reports_no_delete",
            "site_quality_reports_no_update",
            "site_quality_reports_no_replace",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS site_quality_reports_guard ON site_quality_reports")
        op.execute("DROP FUNCTION IF EXISTS site_quality_reports_guard()")
    op.drop_index("ix_site_quality_reports_status", table_name="site_quality_reports")
    op.drop_index("ix_site_quality_reports_page", table_name="site_quality_reports")
    op.drop_table("site_quality_reports")
