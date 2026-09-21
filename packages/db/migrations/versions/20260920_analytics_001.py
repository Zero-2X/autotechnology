"""ANALYTICS-001 metric definitions and append-only lifecycle facts."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_analytics_001"
down_revision = "20260920_media_006"
branch_labels = None
depends_on = None


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER metric_definitions_validate BEFORE INSERT ON metric_definitions "
        "WHEN (NEW.org_id IS NULL AND NEW.scope_key != 'global') "
        "OR (NEW.org_id IS NOT NULL AND NEW.scope_key != NEW.org_id) "
        "OR NEW.version_no < 1 OR NEW.initial_status != 'draft' "
        "OR NEW.metric_type NOT IN ('number','boolean','string','enum','json') "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.dimensions_json) = 0 OR json_type(NEW.dimensions_json) != 'array' "
        "OR json_valid(NEW.quality_rules_json) = 0 OR json_type(NEW.quality_rules_json) != 'object' "
        "BEGIN SELECT RAISE(ABORT, 'metric definition validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER metric_definition_state_events_validate BEFORE INSERT ON metric_definition_state_events "
        "WHEN NOT EXISTS (SELECT 1 FROM metric_definitions d WHERE d.id = NEW.definition_id AND d.scope_key = NEW.scope_key) "
        "OR NEW.sequence < 1 OR NEW.to_status NOT IN ('draft','active','retired') "
        "OR NEW.sequence != (SELECT COALESCE(MAX(s.sequence), 0) + 1 FROM metric_definition_state_events s WHERE s.definition_id = NEW.definition_id) "
        "OR (NEW.sequence = 1 AND (NEW.from_status IS NOT NULL OR NEW.to_status != 'draft')) "
        "OR (NEW.sequence > 1 AND NOT ((NEW.from_status = 'draft' AND NEW.to_status = 'active') "
        "OR (NEW.from_status = 'active' AND NEW.to_status = 'retired'))) "
        "OR (NEW.sequence > 1 AND NEW.from_status IS NOT (SELECT s.to_status FROM metric_definition_state_events s "
        "WHERE s.definition_id = NEW.definition_id ORDER BY s.sequence DESC LIMIT 1)) "
        "OR (NEW.to_status = 'active' AND NEW.effective_at IS NULL) "
        "OR (NEW.to_status = 'retired' AND (NEW.retired_at IS NULL OR NEW.replacement_definition_id IS NULL)) "
        "OR (NEW.to_status = 'retired' AND NOT EXISTS (SELECT 1 FROM metric_definitions current_def "
        "JOIN metric_definitions replacement ON replacement.id = NEW.replacement_definition_id "
        "WHERE current_def.id = NEW.definition_id AND replacement.scope_key = current_def.scope_key "
        "AND replacement.key = current_def.key AND replacement.version_no > current_def.version_no "
        "AND EXISTS (SELECT 1 FROM metric_definition_state_events rs WHERE rs.definition_id = replacement.id "
        "AND rs.to_status = 'active' AND rs.sequence = (SELECT MAX(latest.sequence) FROM metric_definition_state_events latest "
        "WHERE latest.definition_id = replacement.id)))) "
        "BEGIN SELECT RAISE(ABORT, 'metric definition state validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER analytics_metric_definition_commands_validate BEFORE INSERT ON analytics_metric_definition_commands "
        "WHEN NEW.actor_org_id IS NULL OR length(NEW.request_hash) != 64 "
        "OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR json_valid(NEW.response_json) = 0 "
        "OR (NEW.definition_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM metric_definitions d "
        "WHERE d.id = NEW.definition_id AND d.scope_key = NEW.scope_key)) "
        "OR lower(NEW.response_json) LIKE '%\"token\"%' OR lower(NEW.response_json) LIKE '%\"secret\"%' "
        "BEGIN SELECT RAISE(ABORT, 'metric definition command validation failed'); END"
    )
    for table in ("metric_definitions", "metric_definition_state_events", "analytics_metric_definition_commands"):
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION analytics_001_definition_guard() RETURNS trigger AS $$ BEGIN "
        "IF (NEW.org_id IS NULL AND NEW.scope_key <> 'global') "
        "OR (NEW.org_id IS NOT NULL AND NEW.scope_key <> NEW.org_id) "
        "OR NEW.version_no < 1 OR NEW.initial_status <> 'draft' "
        "OR NEW.metric_type NOT IN ('number','boolean','string','enum','json') "
        "OR length(NEW.snapshot_hash) <> 64 OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]+$' THEN "
        "RAISE EXCEPTION 'metric definition validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER metric_definitions_validate BEFORE INSERT ON metric_definitions "
        "FOR EACH ROW EXECUTE FUNCTION analytics_001_definition_guard()"
    )
    op.execute(
        "CREATE FUNCTION analytics_001_state_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM metric_definitions d WHERE d.id = NEW.definition_id AND d.scope_key = NEW.scope_key) "
        "OR NEW.sequence < 1 OR NEW.to_status NOT IN ('draft','active','retired') "
        "OR NEW.sequence <> (SELECT COALESCE(MAX(s.sequence), 0) + 1 FROM metric_definition_state_events s WHERE s.definition_id = NEW.definition_id) "
        "OR (NEW.sequence = 1 AND (NEW.from_status IS NOT NULL OR NEW.to_status <> 'draft')) "
        "OR (NEW.sequence > 1 AND NOT ((NEW.from_status = 'draft' AND NEW.to_status = 'active') "
        "OR (NEW.from_status = 'active' AND NEW.to_status = 'retired'))) "
        "OR (NEW.sequence > 1 AND NEW.from_status IS DISTINCT FROM (SELECT s.to_status FROM metric_definition_state_events s "
        "WHERE s.definition_id = NEW.definition_id ORDER BY s.sequence DESC LIMIT 1)) "
        "OR (NEW.to_status = 'active' AND NEW.effective_at IS NULL) "
        "OR (NEW.to_status = 'retired' AND (NEW.retired_at IS NULL OR NEW.replacement_definition_id IS NULL)) "
        "OR (NEW.to_status = 'retired' AND NOT EXISTS (SELECT 1 FROM metric_definitions current_def "
        "JOIN metric_definitions replacement ON replacement.id = NEW.replacement_definition_id "
        "WHERE current_def.id = NEW.definition_id AND replacement.scope_key = current_def.scope_key "
        "AND replacement.key = current_def.key AND replacement.version_no > current_def.version_no "
        "AND EXISTS (SELECT 1 FROM metric_definition_state_events rs WHERE rs.definition_id = replacement.id "
        "AND rs.to_status = 'active' AND rs.sequence = (SELECT MAX(latest.sequence) FROM metric_definition_state_events latest "
        "WHERE latest.definition_id = replacement.id)))) THEN "
        "RAISE EXCEPTION 'metric definition state validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER metric_definition_state_events_validate BEFORE INSERT ON metric_definition_state_events "
        "FOR EACH ROW EXECUTE FUNCTION analytics_001_state_guard()"
    )
    op.execute(
        "CREATE FUNCTION analytics_001_command_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.actor_org_id IS NULL OR length(NEW.request_hash) <> 64 OR NEW.request_hash !~ '^[0-9A-Fa-f]+$' "
        "OR (NEW.definition_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM metric_definitions d "
        "WHERE d.id = NEW.definition_id AND d.scope_key = NEW.scope_key)) "
        "OR lower(NEW.response_json) LIKE '%\"token\"%' OR lower(NEW.response_json) LIKE '%\"secret\"%' THEN "
        "RAISE EXCEPTION 'metric definition command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER analytics_metric_definition_commands_validate BEFORE INSERT ON analytics_metric_definition_commands "
        "FOR EACH ROW EXECUTE FUNCTION analytics_001_command_guard()"
    )
    op.execute(
        "CREATE FUNCTION analytics_001_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'analytics metric facts are append-only'; END; $$ LANGUAGE plpgsql"
    )
    for table in ("metric_definitions", "metric_definition_state_events", "analytics_metric_definition_commands"):
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION analytics_001_append_only_guard()"
        )


def upgrade() -> None:
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=True),
        sa.Column("scope_key", sa.String(36), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("metric_type", sa.String(16), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("formula", sa.Text, nullable=False),
        sa.Column("dimensions_json", sa.Text, nullable=False),
        sa.Column("window", sa.String(128), nullable=False),
        sa.Column("data_source", sa.String(256), nullable=False),
        sa.Column("dedupe_rule", sa.String(512), nullable=False),
        sa.Column("quality_rules_json", sa.Text, nullable=False),
        sa.Column("owner_actor_id", sa.String(36), nullable=True),
        sa.Column("initial_status", sa.String(16), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", "key", "version_no", name="uq_metric_definitions_scope_key_version"),
        sa.CheckConstraint("version_no >= 1", name="ck_metric_definitions_version"),
        sa.CheckConstraint("initial_status = 'draft'", name="ck_metric_definitions_initial_status"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_metric_definitions_snapshot_hash"),
        sa.CheckConstraint(
            "(org_id IS NULL AND scope_key = 'global') OR (org_id IS NOT NULL AND scope_key = org_id)",
            name="ck_metric_definitions_scope",
        ),
    )
    op.create_table(
        "metric_definition_state_events",
        sa.Column("definition_id", sa.String(36), nullable=False),
        sa.Column("scope_key", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("effective_at", sa.String(40), nullable=True),
        sa.Column("retired_at", sa.String(40), nullable=True),
        sa.Column("replacement_definition_id", sa.String(36), nullable=True),
        sa.Column("actor_org_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("definition_id", "sequence"),
        sa.ForeignKeyConstraint(["definition_id"], ["metric_definitions.id"], name="fk_metric_definition_state_definition"),
        sa.ForeignKeyConstraint(["replacement_definition_id"], ["metric_definitions.id"], name="fk_metric_definition_state_replacement"),
        sa.CheckConstraint("sequence >= 1", name="ck_metric_definition_state_sequence"),
        sa.CheckConstraint("to_status IN ('draft','active','retired')", name="ck_metric_definition_state_status"),
    )
    op.create_table(
        "analytics_metric_definition_commands",
        sa.Column("actor_org_id", sa.String(36), nullable=False),
        sa.Column("scope_key", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("definition_id", sa.String(36), nullable=True),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("actor_org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["definition_id"], ["metric_definitions.id"], name="fk_analytics_metric_command_definition"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_analytics_metric_command_hash"),
    )
    op.create_index(
        "ix_metric_definitions_scope_key",
        "metric_definitions",
        ["scope_key", "key", "version_no"],
    )
    op.create_index(
        "ix_metric_definition_state_current",
        "metric_definition_state_events",
        ["definition_id", "sequence"],
    )
    op.create_index(
        "ix_analytics_metric_commands_definition",
        "analytics_metric_definition_commands",
        ["scope_key", "definition_id", "created_at"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _sqlite_guards()
    elif dialect == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    tables = ("metric_definitions", "metric_definition_state_events", "analytics_metric_definition_commands")
    if dialect == "sqlite":
        for table in tables:
            for suffix in ("validate", "no_update", "no_delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
    elif dialect == "postgresql":
        for table in tables:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for table, trigger in (
            ("metric_definitions", "metric_definitions_validate"),
            ("metric_definition_state_events", "metric_definition_state_events_validate"),
            ("analytics_metric_definition_commands", "analytics_metric_definition_commands_validate"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for name in (
            "analytics_001_definition_guard",
            "analytics_001_state_guard",
            "analytics_001_command_guard",
            "analytics_001_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    op.drop_index("ix_analytics_metric_commands_definition", table_name="analytics_metric_definition_commands")
    op.drop_index("ix_metric_definition_state_current", table_name="metric_definition_state_events")
    op.drop_index("ix_metric_definitions_scope_key", table_name="metric_definitions")
    op.drop_table("analytics_metric_definition_commands")
    op.drop_table("metric_definition_state_events")
    op.drop_table("metric_definitions")
