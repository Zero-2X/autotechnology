"""MEDIA-005B protected-token, disclosure and rights QA evidence projection."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_005b"
down_revision = "20260920_media_005a"
branch_labels = None
depends_on = None


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_qa_content_evaluations_validate BEFORE INSERT ON media_qa_content_evaluations "
        "WHEN NOT EXISTS (SELECT 1 FROM media_qa_reports r WHERE r.org_id = NEW.org_id AND r.id = NEW.report_id) "
        "OR NEW.sequence < 1 OR NEW.check_name NOT IN ('numbers', 'code', 'versions', 'ai_label', 'rights') "
        "OR length(NEW.source_hash) != 64 OR NEW.source_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR (NEW.observed_hash IS NOT NULL AND (length(NEW.observed_hash) != 64 OR NEW.observed_hash GLOB '*[^0-9A-Fa-f]*')) "
        "OR length(NEW.rights_snapshot_hash) != 64 OR NEW.rights_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.evidence_json) = 0 "
        "OR lower(NEW.evidence_json) LIKE '%\"token\"%' OR lower(NEW.evidence_json) LIKE '%\"secret\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media content QA evidence validation failed'); END"
    )
    op.execute("CREATE TRIGGER media_qa_content_evaluations_no_update BEFORE UPDATE ON media_qa_content_evaluations BEGIN SELECT RAISE(ABORT, 'media content QA evidence is append-only'); END")
    op.execute("CREATE TRIGGER media_qa_content_evaluations_no_delete BEFORE DELETE ON media_qa_content_evaluations BEGIN SELECT RAISE(ABORT, 'media content QA evidence is append-only'); END")


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_qa_005b_evaluation_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_qa_reports r WHERE r.org_id = NEW.org_id AND r.id = NEW.report_id) "
        "OR NEW.sequence < 1 OR NEW.check_name NOT IN ('numbers','code','versions','ai_label','rights') "
        "OR length(NEW.source_hash) <> 64 OR NEW.source_hash !~ '^[0-9A-Fa-f]+$' "
        "OR (NEW.observed_hash IS NOT NULL AND (length(NEW.observed_hash) <> 64 OR NEW.observed_hash !~ '^[0-9A-Fa-f]+$')) "
        "OR length(NEW.rights_snapshot_hash) <> 64 OR NEW.rights_snapshot_hash !~ '^[0-9A-Fa-f]+$' "
        "OR lower(NEW.evidence_json) LIKE '%\"token\"%' OR lower(NEW.evidence_json) LIKE '%\"secret\"%' THEN "
        "RAISE EXCEPTION 'media content QA evidence validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_qa_content_evaluations_validate BEFORE INSERT ON media_qa_content_evaluations FOR EACH ROW EXECUTE FUNCTION media_qa_005b_evaluation_guard()")
    op.execute(
        "CREATE FUNCTION media_qa_005b_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'media content QA evidence is append-only'; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_qa_content_evaluations_no_mutation BEFORE UPDATE OR DELETE ON media_qa_content_evaluations FOR EACH ROW EXECUTE FUNCTION media_qa_005b_append_only_guard()")


def upgrade() -> None:
    op.create_table(
        "media_qa_content_evaluations",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("report_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("check_name", sa.String(32), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("observed_hash", sa.String(64), nullable=True),
        sa.Column("rights_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "report_id", "sequence"),
        sa.ForeignKeyConstraint(["org_id", "report_id"], ["media_qa_reports.org_id", "media_qa_reports.id"], name="fk_media_qa_content_evaluations_report"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_qa_content_evaluations_sequence"),
        sa.CheckConstraint("check_name IN ('numbers', 'code', 'versions', 'ai_label', 'rights')", name="ck_media_qa_content_evaluations_check"),
        sa.CheckConstraint("length(source_hash) = 64 AND length(rights_snapshot_hash) = 64", name="ck_media_qa_content_evaluations_hash"),
    )
    op.create_index("ix_media_qa_content_evaluations_report", "media_qa_content_evaluations", ["org_id", "report_id", "sequence"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for name in ("media_qa_content_evaluations_validate", "media_qa_content_evaluations_no_update", "media_qa_content_evaluations_no_delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for trigger in ("media_qa_content_evaluations_validate", "media_qa_content_evaluations_no_mutation"):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON media_qa_content_evaluations")
        for name in ("media_qa_005b_evaluation_guard", "media_qa_005b_append_only_guard"):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    op.drop_index("ix_media_qa_content_evaluations_report", table_name="media_qa_content_evaluations")
    op.drop_table("media_qa_content_evaluations")
