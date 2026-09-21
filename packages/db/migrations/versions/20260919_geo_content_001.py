"""GEO_CONTENT-001 assessment projection and idempotency records.

The rule engine itself is a read-only application service.  These tables keep
the reproducible assessment and command evidence without becoming a source of
content facts; all source/claim/evidence records remain owned by their
predecessor modules.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_geo_content_001"
down_revision = "20260919_found_site_003"
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
        "geo_content_checks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("rule_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_geo_content_check_input_hash"),
        sa.CheckConstraint("length(output_hash) = 64", name="ck_geo_content_check_output_hash"),
        sa.CheckConstraint("score >= 0 AND score <= 1", name="ck_geo_content_check_score"),
        sa.CheckConstraint("status IN ('pass', 'review', 'fail')", name="ck_geo_content_check_status"),
    )
    op.create_table(
        "geo_content_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_geo_content_command_hash"),
    )
    op.create_index(
        "ix_geo_content_checks_status",
        "geo_content_checks",
        ["org_id", "status", "created_at"],
    )
    op.create_index(
        "ix_geo_content_checks_input",
        "geo_content_checks",
        ["org_id", "input_hash", "created_at"],
    )
    _append_only("geo_content_checks")
    _append_only("geo_content_commands")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in ("geo_content_commands", "geo_content_checks"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
    op.drop_index("ix_geo_content_checks_input", table_name="geo_content_checks")
    op.drop_index("ix_geo_content_checks_status", table_name="geo_content_checks")
    op.drop_table("geo_content_commands")
    op.drop_table("geo_content_checks")
