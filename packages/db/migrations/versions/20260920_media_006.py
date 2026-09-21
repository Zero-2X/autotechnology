"""MEDIA-006 immutable AssetVersion lineage edges and decisions."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_006"
down_revision = "20260920_media_005b"
branch_labels = None
depends_on = None


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_asset_lineage_edges_validate BEFORE INSERT ON media_asset_lineage_edges "
        "WHEN NEW.source_org_id != NEW.org_id OR NEW.lineage_type NOT IN ('variant', 'claim', 'rights') "
        "OR NEW.sequence < 1 OR NEW.source_version_no IS NOT NULL AND NEW.source_version_no < 1 "
        "OR length(NEW.source_snapshot_hash) != 64 OR NEW.source_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NEW.relation NOT IN ('derived_from', 'fact_support', 'rights_snapshot') "
        "BEGIN SELECT RAISE(ABORT, 'asset lineage edge validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_asset_lineage_checks_validate BEFORE INSERT ON media_asset_lineage_checks "
        "WHEN NEW.source_org_id != NEW.org_id OR NEW.status NOT IN ('valid', 'blocked', 'withdrawn', 'needs_review') "
        "OR length(NEW.decision_hash) != 64 OR NEW.decision_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.reasons_json) = 0 "
        "BEGIN SELECT RAISE(ABORT, 'asset lineage decision validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_asset_lineage_commands_validate BEFORE INSERT ON media_asset_lineage_commands "
        "WHEN NEW.source_org_id != NEW.org_id OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.response_json) = 0 OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'asset lineage command validation failed'); END"
    )
    for table in ("media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"):
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_asset_lineage_006_edge_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.source_org_id <> NEW.org_id OR NEW.lineage_type NOT IN ('variant','claim','rights') "
        "OR NEW.sequence < 1 OR (NEW.source_version_no IS NOT NULL AND NEW.source_version_no < 1) "
        "OR length(NEW.source_snapshot_hash) <> 64 OR NEW.source_snapshot_hash !~ '^[0-9A-Fa-f]+$' "
        "OR NEW.relation NOT IN ('derived_from','fact_support','rights_snapshot') THEN RAISE EXCEPTION 'asset lineage edge validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_asset_lineage_edges_validate BEFORE INSERT ON media_asset_lineage_edges FOR EACH ROW EXECUTE FUNCTION media_asset_lineage_006_edge_guard()")
    op.execute(
        "CREATE FUNCTION media_asset_lineage_006_check_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.source_org_id <> NEW.org_id OR NEW.status NOT IN ('valid','blocked','withdrawn','needs_review') "
        "OR length(NEW.decision_hash) <> 64 OR NEW.decision_hash !~ '^[0-9A-Fa-f]+$' THEN RAISE EXCEPTION 'asset lineage decision validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_asset_lineage_checks_validate BEFORE INSERT ON media_asset_lineage_checks FOR EACH ROW EXECUTE FUNCTION media_asset_lineage_006_check_guard()")
    op.execute(
        "CREATE FUNCTION media_asset_lineage_006_command_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.source_org_id <> NEW.org_id OR length(NEW.request_hash) <> 64 OR NEW.request_hash !~ '^[0-9A-Fa-f]+$' "
        "OR lower(NEW.response_json) LIKE '%\"token\"%' OR lower(NEW.response_json) LIKE '%\"secret\"%' THEN RAISE EXCEPTION 'asset lineage command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_asset_lineage_commands_validate BEFORE INSERT ON media_asset_lineage_commands FOR EACH ROW EXECUTE FUNCTION media_asset_lineage_006_command_guard()")
    op.execute(
        "CREATE FUNCTION media_asset_lineage_006_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'asset lineage facts are append-only'; END; $$ LANGUAGE plpgsql"
    )
    for table in ("media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"):
        op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION media_asset_lineage_006_append_only_guard()")


def upgrade() -> None:
    op.create_table(
        "media_asset_lineage_edges",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_org_id", sa.String(36), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("lineage_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("source_version_no", sa.Integer, nullable=True),
        sa.Column("source_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "asset_version_id", "sequence"),
        sa.UniqueConstraint("org_id", "asset_version_id", "lineage_type", "source_id", name="uq_media_asset_lineage_edge_source"),
        sa.CheckConstraint("org_id = source_org_id", name="ck_media_asset_lineage_edge_tenant"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_asset_lineage_edge_sequence"),
        sa.CheckConstraint("length(source_snapshot_hash) = 64", name="ck_media_asset_lineage_edge_hash"),
    )
    op.create_table(
        "media_asset_lineage_checks",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_org_id", sa.String(36), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reasons_json", sa.Text, nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "asset_version_id", "sequence"),
        sa.CheckConstraint("org_id = source_org_id", name="ck_media_asset_lineage_check_tenant"),
        sa.CheckConstraint("status IN ('valid', 'blocked', 'withdrawn', 'needs_review')", name="ck_media_asset_lineage_check_status"),
        sa.CheckConstraint("length(decision_hash) = 64", name="ck_media_asset_lineage_check_hash"),
    )
    op.create_table(
        "media_asset_lineage_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column("command", sa.String(64), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.CheckConstraint("org_id = source_org_id", name="ck_media_asset_lineage_command_tenant"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_asset_lineage_command_hash"),
    )
    op.create_index("ix_media_asset_lineage_edges_asset", "media_asset_lineage_edges", ["org_id", "asset_version_id", "sequence"])
    op.create_index("ix_media_asset_lineage_checks_asset", "media_asset_lineage_checks", ["org_id", "asset_version_id", "created_at"])
    op.create_index("ix_media_asset_lineage_commands_asset", "media_asset_lineage_commands", ["org_id", "asset_version_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"):
            for suffix in ("validate", "no_update", "no_delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
    elif dialect == "postgresql":
        for table in ("media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for table, trigger in (("media_asset_lineage_edges", "media_asset_lineage_edges_validate"), ("media_asset_lineage_checks", "media_asset_lineage_checks_validate"), ("media_asset_lineage_commands", "media_asset_lineage_commands_validate")):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for name in ("media_asset_lineage_006_edge_guard", "media_asset_lineage_006_check_guard", "media_asset_lineage_006_command_guard", "media_asset_lineage_006_append_only_guard"):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (("ix_media_asset_lineage_commands_asset", "media_asset_lineage_commands"), ("ix_media_asset_lineage_checks_asset", "media_asset_lineage_checks"), ("ix_media_asset_lineage_edges_asset", "media_asset_lineage_edges")):
        op.drop_index(index, table_name=table)
    op.drop_table("media_asset_lineage_commands")
    op.drop_table("media_asset_lineage_checks")
    op.drop_table("media_asset_lineage_edges")
