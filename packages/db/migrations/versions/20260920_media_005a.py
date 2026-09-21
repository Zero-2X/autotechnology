"""MEDIA-005A media visual/audio/subtitle/hash QA projections."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_005a"
down_revision = "20260920_media_004b"
branch_labels = None
depends_on = None


_APPEND_ONLY = ("media_qa_reports", "media_qa_findings", "media_qa_commands")
_SENSITIVE = (
    "'\"model\"'", "'\"provider\"'", "'\"credential\"'", "'\"token\"'", "'\"secret\"'",
    "'\"password\"'", "'\"authorization\"'", "'\"api_key\"'", "'\"raw_output\"'",
)


def _sqlite_guards() -> None:
    sensitive_report = " OR ".join(f"lower(NEW.{field}) LIKE '%{term[1:-1]}%'" for field in ("input_snapshot_json", "artifact_facts_json") for term in _SENSITIVE)
    op.execute(
        "CREATE TRIGGER media_qa_reports_validate BEFORE INSERT ON media_qa_reports "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.subject_type != 'media_render_job' OR NEW.subject_id != NEW.render_job_id "
        "OR NEW.status NOT IN ('passed', 'failed', 'needs_review') "
        "OR length(NEW.input_hash) != 64 OR NEW.input_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.report_hash) != 64 OR NEW.report_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NEW.finding_count < 0 OR json_valid(NEW.input_snapshot_json) = 0 OR json_valid(NEW.artifact_facts_json) = 0 "
        + ("OR " + sensitive_report if sensitive_report else "") +
        " BEGIN SELECT RAISE(ABORT, 'media QA report validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_qa_findings_validate BEFORE INSERT ON media_qa_findings "
        "WHEN NOT EXISTS (SELECT 1 FROM media_qa_reports r WHERE r.org_id = NEW.org_id AND r.id = NEW.report_id) "
        "OR NEW.sequence < 1 OR NEW.check_name NOT IN ('visual', 'audio', 'subtitle', 'file_hash', 'numbers', 'code', 'versions', 'ai_label', 'rights', 'general') "
        "OR NEW.severity NOT IN ('error', 'warning', 'info') OR length(NEW.code) < 1 "
        "OR json_valid(NEW.observed_json) = 0 OR json_valid(NEW.expected_json) = 0 "
        " BEGIN SELECT RAISE(ABORT, 'media QA finding validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_qa_commands_validate BEFORE INSERT ON media_qa_commands "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "OR lower(NEW.response_json) LIKE '%\"authorization\"%' OR lower(NEW.response_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        " BEGIN SELECT RAISE(ABORT, 'media QA command validation failed'); END"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_qa_005a_report_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.subject_type <> 'media_render_job' OR NEW.subject_id <> NEW.render_job_id "
        "OR NEW.status NOT IN ('passed', 'failed', 'needs_review') "
        "OR length(NEW.input_hash) <> 64 OR NEW.input_hash !~ '^[0-9A-Fa-f]+$' "
        "OR length(NEW.report_hash) <> 64 OR NEW.report_hash !~ '^[0-9A-Fa-f]+$' "
        "OR NEW.finding_count < 0 OR lower(NEW.input_snapshot_json) LIKE '%\"token\"%' "
        "OR lower(NEW.input_snapshot_json) LIKE '%\"secret\"%' OR lower(NEW.artifact_facts_json) LIKE '%\"raw_output\"%' THEN "
        "RAISE EXCEPTION 'media QA report validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_qa_reports_validate BEFORE INSERT ON media_qa_reports FOR EACH ROW EXECUTE FUNCTION media_qa_005a_report_guard()")
    op.execute(
        "CREATE FUNCTION media_qa_005a_finding_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_qa_reports r WHERE r.org_id = NEW.org_id AND r.id = NEW.report_id) "
        "OR NEW.sequence < 1 OR NEW.check_name NOT IN ('visual','audio','subtitle','file_hash','numbers','code','versions','ai_label','rights','general') "
        "OR NEW.severity NOT IN ('error','warning','info') THEN RAISE EXCEPTION 'media QA finding validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_qa_findings_validate BEFORE INSERT ON media_qa_findings FOR EACH ROW EXECUTE FUNCTION media_qa_005a_finding_guard()")
    op.execute(
        "CREATE FUNCTION media_qa_005a_command_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR length(NEW.request_hash) <> 64 OR NEW.request_hash !~ '^[0-9A-Fa-f]+$' "
        "OR lower(NEW.response_json) LIKE '%\"token\"%' OR lower(NEW.response_json) LIKE '%\"secret\"%' THEN "
        "RAISE EXCEPTION 'media QA command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_qa_commands_validate BEFORE INSERT ON media_qa_commands FOR EACH ROW EXECUTE FUNCTION media_qa_005a_command_guard()")
    op.execute(
        "CREATE FUNCTION media_qa_005a_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'media QA facts are append-only'; END; $$ LANGUAGE plpgsql"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION media_qa_005a_append_only_guard()")


def upgrade() -> None:
    op.create_table(
        "media_qa_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("report_hash", sa.String(64), nullable=False),
        sa.Column("finding_count", sa.Integer, nullable=False),
        sa.Column("input_snapshot_json", sa.Text, nullable=False),
        sa.Column("artifact_facts_json", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_qa_reports_org_id"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_qa_reports_job"),
        sa.CheckConstraint("finding_count >= 0", name="ck_media_qa_reports_finding_count"),
        sa.CheckConstraint("length(input_hash) = 64 AND length(report_hash) = 64", name="ck_media_qa_reports_hash"),
    )
    op.create_table(
        "media_qa_findings",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("check_name", sa.String(32), nullable=False),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.Column("observed_json", sa.Text, nullable=False),
        sa.Column("expected_json", sa.Text, nullable=False),
        sa.Column("artifact_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "report_id", "sequence"),
        sa.ForeignKeyConstraint(["org_id", "report_id"], ["media_qa_reports.org_id", "media_qa_reports.id"], name="fk_media_qa_findings_report"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_qa_findings_sequence"),
        sa.CheckConstraint("check_name IN ('visual', 'audio', 'subtitle', 'file_hash', 'numbers', 'code', 'versions', 'ai_label', 'rights', 'general')", name="ck_media_qa_findings_check"),
        sa.CheckConstraint("severity IN ('error', 'warning', 'info')", name="ck_media_qa_findings_severity"),
    )
    op.create_table(
        "media_qa_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_qa_commands_job"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_qa_commands_hash"),
    )
    op.create_index("ix_media_qa_reports_job", "media_qa_reports", ["org_id", "render_job_id", "created_at"])
    op.create_index("ix_media_qa_findings_report", "media_qa_findings", ["org_id", "report_id", "sequence"])
    op.create_index("ix_media_qa_commands_job", "media_qa_commands", ["org_id", "render_job_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for name in (
            "media_qa_reports_validate", "media_qa_findings_validate", "media_qa_commands_validate",
            "media_qa_reports_no_update", "media_qa_reports_no_delete", "media_qa_findings_no_update",
            "media_qa_findings_no_delete", "media_qa_commands_no_update", "media_qa_commands_no_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for table, trigger in (
            ("media_qa_reports", "media_qa_reports_validate"),
            ("media_qa_findings", "media_qa_findings_validate"),
            ("media_qa_commands", "media_qa_commands_validate"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for name in ("media_qa_005a_report_guard", "media_qa_005a_finding_guard", "media_qa_005a_command_guard", "media_qa_005a_append_only_guard"):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_qa_commands_job", "media_qa_commands"),
        ("ix_media_qa_findings_report", "media_qa_findings"),
        ("ix_media_qa_reports_job", "media_qa_reports"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_qa_commands")
    op.drop_table("media_qa_findings")
    op.drop_table("media_qa_reports")
