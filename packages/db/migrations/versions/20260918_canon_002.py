"""CANON-002 immutable version history and deterministic diff snapshots."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_canon_002"
down_revision = "20260918_found_canon_001"
branch_labels = None
depends_on = None


def _sqlite_append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def _postgres_append_only(table: str) -> None:
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
        "canonical_content_version_diffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_content_id", sa.String(36), nullable=False),
        sa.Column("from_version_id", sa.String(36), nullable=False),
        sa.Column("to_version_id", sa.String(36), nullable=False),
        sa.Column("diff_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "canonical_content_id", "from_version_id", "to_version_id", name="uq_canonical_diffs_pair"),
        sa.ForeignKeyConstraint(["org_id", "canonical_content_id"], ["canonical_contents.org_id", "canonical_contents.id"], name="fk_canonical_diffs_root"),
        sa.ForeignKeyConstraint(["org_id", "from_version_id"], ["canonical_content_versions.org_id", "canonical_content_versions.id"], name="fk_canonical_diffs_from"),
        sa.ForeignKeyConstraint(["org_id", "to_version_id"], ["canonical_content_versions.org_id", "canonical_content_versions.id"], name="fk_canonical_diffs_to"),
        sa.CheckConstraint("length(diff_hash) = 64", name="ck_canonical_diffs_hash"),
    )
    op.create_index("ix_canonical_diffs_root", "canonical_content_version_diffs", ["org_id", "canonical_content_id", "created_at"])
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _sqlite_append_only("canonical_content_version_diffs")
    elif dialect == "postgresql":
        _postgres_append_only("canonical_content_version_diffs")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS canonical_content_version_diffs_no_update")
        op.execute("DROP TRIGGER IF EXISTS canonical_content_version_diffs_no_delete")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS canonical_content_version_diffs_no_mutation ON canonical_content_version_diffs")
        op.execute("DROP FUNCTION IF EXISTS canonical_content_version_diffs_immutable()")
    op.drop_index("ix_canonical_diffs_root", table_name="canonical_content_version_diffs")
    op.drop_table("canonical_content_version_diffs")
