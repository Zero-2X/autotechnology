"""PROD-003 immutable terminology versions and approved translation memory."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_prod_003"
down_revision = "20260919_found_prod_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_terminology_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(64), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "locale", "version_no"),
        sa.CheckConstraint("version_no >= 1", name="ck_terminology_version_no"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_terminology_hash"),
    )
    op.create_table(
        "production_translation_memory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("target_text", sa.Text, nullable=False),
        sa.Column("approved_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "locale", "source_hash", "target_text"),
        sa.CheckConstraint("length(source_hash) = 64", name="ck_translation_memory_source_hash"),
    )
    op.create_table(
        "production_terminology_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_terminology_command_hash"),
    )
    op.create_index("ix_terminology_locale", "production_terminology_versions", ["org_id", "locale", "version_no"])
    op.create_index("ix_translation_memory_lookup", "production_translation_memory", ["org_id", "locale", "source_hash"])
    for table in ("production_terminology_versions", "production_translation_memory", "production_terminology_commands"):
        if op.get_bind().dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                )
        elif op.get_bind().dialect.name == "postgresql":
            op.execute(
                f"CREATE FUNCTION {table}_immutable() RETURNS trigger AS $$ "
                f"BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$ LANGUAGE plpgsql"
            )
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in ("production_terminology_versions", "production_translation_memory", "production_terminology_commands"):
            op.execute(f"DROP TRIGGER {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION {table}_immutable()")
    op.drop_index("ix_translation_memory_lookup", table_name="production_translation_memory")
    op.drop_index("ix_terminology_locale", table_name="production_terminology_versions")
    op.drop_table("production_terminology_commands")
    op.drop_table("production_translation_memory")
    op.drop_table("production_terminology_versions")
