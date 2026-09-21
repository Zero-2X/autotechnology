"""ANALYTICS-002 append-only, metric-bound observations."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_analytics_002"
down_revision = "20260920_analytics_001"
branch_labels = None
depends_on = None


_EVENT_TYPES_SQL = (
    "'analytics.content.observed','analytics.asset.observed','analytics.publication.observed',"
    "'analytics.interaction.observed','analytics.geo.observed','analytics.support.observed',"
    "'analytics.qa.observed','analytics.cost.observed','analytics.risk.observed'"
)


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER observations_validate BEFORE INSERT ON observations "
        "WHEN NEW.source NOT IN ('site','fake','manual','platform','geo','support','qa') "
        "OR NEW.subject_type NOT IN ('publication','content','variant','asset','topic','page','geo_run') "
        "OR NEW.metric_type NOT IN ('number','boolean','string','enum','json') "
        "OR NEW.data_quality NOT IN ('raw','validated','estimated') "
        "OR NEW.observation_version < 1 OR json_valid(NEW.metric_value_json) = 0 "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        f"OR NEW.source_event_type NOT IN ({_EVENT_TYPES_SQL}) "
        "OR NEW.observation_version != (SELECT COALESCE(MAX(o.observation_version), 0) + 1 FROM observations o "
        "WHERE o.org_id = NEW.org_id AND o.dedupe_key = NEW.dedupe_key) "
        "OR (NEW.source IN ('site','platform','geo','support','qa') AND NEW.source_snapshot_ref IS NULL) "
        "OR (NEW.source = 'platform' AND (NEW.account_evidence_hash IS NULL OR length(NEW.account_evidence_hash) != 64 "
        "OR NEW.account_evidence_hash GLOB '*[^0-9A-Fa-f]*')) "
        "OR (NEW.source != 'platform' AND NEW.account_evidence_hash IS NOT NULL) "
        "OR lower(NEW.metric_value_json) LIKE '%\"token\"%' OR lower(NEW.metric_value_json) LIKE '%\"secret\"%' "
        "OR lower(NEW.metric_value_json) LIKE '%\"password\"%' OR lower(NEW.metric_value_json) LIKE '%\"cookie\"%' "
        "OR lower(NEW.metric_value_json) LIKE '%\"authorization\"%' OR lower(NEW.metric_value_json) LIKE '%\"raw_content\"%' "
        "OR NOT EXISTS (SELECT 1 FROM metric_definitions d WHERE d.id = NEW.metric_definition_id "
        "AND (d.org_id IS NULL OR d.org_id = NEW.org_id) AND d.version_no = NEW.metric_definition_version_no "
        "AND d.key = NEW.metric_name AND d.metric_type = NEW.metric_type "
        "AND EXISTS (SELECT 1 FROM metric_definition_state_events s WHERE s.definition_id = d.id "
        "AND s.to_status = 'active' AND s.sequence = (SELECT MAX(latest.sequence) FROM metric_definition_state_events latest "
        "WHERE latest.definition_id = d.id))) "
        "OR (NEW.observation_version > 1 AND NOT EXISTS (SELECT 1 FROM observations first_observation "
        "WHERE first_observation.org_id = NEW.org_id AND first_observation.dedupe_key = NEW.dedupe_key "
        "AND first_observation.observation_version = 1 AND first_observation.source = NEW.source "
        "AND first_observation.subject_type = NEW.subject_type AND first_observation.subject_id = NEW.subject_id "
        "AND first_observation.metric_definition_id = NEW.metric_definition_id "
        "AND first_observation.metric_name = NEW.metric_name AND first_observation.metric_type = NEW.metric_type)) "
        "BEGIN SELECT RAISE(ABORT, 'observation validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER analytics_observation_commands_validate BEFORE INSERT ON analytics_observation_commands "
        "WHEN length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.response_hash) != 64 OR NEW.response_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NOT EXISTS (SELECT 1 FROM observations o WHERE o.id = NEW.observation_id AND o.org_id = NEW.org_id) "
        "BEGIN SELECT RAISE(ABORT, 'observation command validation failed'); END"
    )
    for table in ("observations", "analytics_observation_commands"):
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
        "CREATE FUNCTION analytics_002_observation_guard() RETURNS trigger AS $$ BEGIN PERFORM NEW.metric_value_json::jsonb; "
        "IF NEW.source NOT IN ('site','fake','manual','platform','geo','support','qa') "
        "OR NEW.subject_type NOT IN ('publication','content','variant','asset','topic','page','geo_run') "
        "OR NEW.metric_type NOT IN ('number','boolean','string','enum','json') "
        "OR NEW.data_quality NOT IN ('raw','validated','estimated') "
        "OR NEW.observation_version < 1 OR length(NEW.snapshot_hash) <> 64 OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]+$' "
        f"OR NEW.source_event_type NOT IN ({_EVENT_TYPES_SQL}) "
        "OR NEW.observation_version <> (SELECT COALESCE(MAX(o.observation_version), 0) + 1 FROM observations o "
        "WHERE o.org_id = NEW.org_id AND o.dedupe_key = NEW.dedupe_key) "
        "OR (NEW.source IN ('site','platform','geo','support','qa') AND NEW.source_snapshot_ref IS NULL) "
        "OR (NEW.source = 'platform' AND (NEW.account_evidence_hash IS NULL OR length(NEW.account_evidence_hash) <> 64 "
        "OR NEW.account_evidence_hash !~ '^[0-9A-Fa-f]+$')) "
        "OR (NEW.source <> 'platform' AND NEW.account_evidence_hash IS NOT NULL) "
        "OR lower(NEW.metric_value_json) LIKE '%\"token\"%' OR lower(NEW.metric_value_json) LIKE '%\"secret\"%' "
        "OR lower(NEW.metric_value_json) LIKE '%\"password\"%' OR lower(NEW.metric_value_json) LIKE '%\"cookie\"%' "
        "OR lower(NEW.metric_value_json) LIKE '%\"authorization\"%' OR lower(NEW.metric_value_json) LIKE '%\"raw_content\"%' "
        "OR NOT EXISTS (SELECT 1 FROM metric_definitions d WHERE d.id = NEW.metric_definition_id "
        "AND (d.org_id IS NULL OR d.org_id = NEW.org_id) AND d.version_no = NEW.metric_definition_version_no "
        "AND d.key = NEW.metric_name AND d.metric_type = NEW.metric_type "
        "AND EXISTS (SELECT 1 FROM metric_definition_state_events s WHERE s.definition_id = d.id "
        "AND s.to_status = 'active' AND s.sequence = (SELECT MAX(latest.sequence) FROM metric_definition_state_events latest "
        "WHERE latest.definition_id = d.id))) "
        "OR (NEW.observation_version > 1 AND NOT EXISTS (SELECT 1 FROM observations first_observation "
        "WHERE first_observation.org_id = NEW.org_id AND first_observation.dedupe_key = NEW.dedupe_key "
        "AND first_observation.observation_version = 1 AND first_observation.source = NEW.source "
        "AND first_observation.subject_type = NEW.subject_type AND first_observation.subject_id = NEW.subject_id "
        "AND first_observation.metric_definition_id = NEW.metric_definition_id "
        "AND first_observation.metric_name = NEW.metric_name AND first_observation.metric_type = NEW.metric_type)) THEN "
        "RAISE EXCEPTION 'observation validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER observations_validate BEFORE INSERT ON observations "
        "FOR EACH ROW EXECUTE FUNCTION analytics_002_observation_guard()"
    )
    op.execute(
        "CREATE FUNCTION analytics_002_command_guard() RETURNS trigger AS $$ BEGIN "
        "IF length(NEW.request_hash) <> 64 OR NEW.request_hash !~ '^[0-9A-Fa-f]+$' "
        "OR length(NEW.response_hash) <> 64 OR NEW.response_hash !~ '^[0-9A-Fa-f]+$' "
        "OR NOT EXISTS (SELECT 1 FROM observations o WHERE o.id = NEW.observation_id AND o.org_id = NEW.org_id) THEN "
        "RAISE EXCEPTION 'observation command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER analytics_observation_commands_validate BEFORE INSERT ON analytics_observation_commands "
        "FOR EACH ROW EXECUTE FUNCTION analytics_002_command_guard()"
    )
    op.execute(
        "CREATE FUNCTION analytics_002_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "RAISE EXCEPTION 'analytics observation facts are append-only'; END; $$ LANGUAGE plpgsql"
    )
    for table in ("observations", "analytics_observation_commands"):
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION analytics_002_append_only_guard()"
        )


def upgrade() -> None:
    op.create_table(
        "observations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("metric_definition_id", sa.String(36), nullable=False),
        sa.Column("metric_definition_version_no", sa.Integer, nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("metric_type", sa.String(16), nullable=False),
        sa.Column("metric_value_json", sa.Text, nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("locale", sa.String(64), nullable=True),
        sa.Column("region", sa.String(32), nullable=True),
        sa.Column("data_quality", sa.String(16), nullable=False),
        sa.Column("dedupe_key", sa.String(512), nullable=False),
        sa.Column("source_snapshot_ref", sa.String(2048), nullable=True),
        sa.Column("observation_version", sa.Integer, nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("source_event_type", sa.String(64), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("account_evidence_hash", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["metric_definition_id"], ["metric_definitions.id"], name="fk_observations_metric_definition"),
        sa.UniqueConstraint("org_id", "dedupe_key", "observation_version", name="uq_observations_dedupe_version"),
        sa.UniqueConstraint("org_id", "source_event_id", name="uq_observations_source_event"),
        sa.CheckConstraint("observation_version >= 1", name="ck_observations_version"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_observations_snapshot_hash"),
    )
    op.create_table(
        "analytics_observation_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("response_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["observation_id"], ["observations.id"], name="fk_analytics_observation_command_observation"),
        sa.CheckConstraint("length(request_hash) = 64 AND length(response_hash) = 64", name="ck_analytics_observation_command_hashes"),
    )
    op.create_index(
        "ix_observations_subject_metric",
        "observations",
        ["org_id", "subject_type", "subject_id", "metric_definition_id", "observed_at"],
    )
    op.create_index(
        "ix_observations_dedupe",
        "observations",
        ["org_id", "dedupe_key", "observation_version"],
    )
    op.create_index(
        "ix_analytics_observation_commands_observation",
        "analytics_observation_commands",
        ["org_id", "observation_id", "created_at"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _sqlite_guards()
    elif dialect == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    tables = ("observations", "analytics_observation_commands")
    if dialect == "sqlite":
        for table in tables:
            for suffix in ("validate", "no_update", "no_delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
    elif dialect == "postgresql":
        for table in tables:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        op.execute("DROP TRIGGER IF EXISTS observations_validate ON observations")
        op.execute("DROP TRIGGER IF EXISTS analytics_observation_commands_validate ON analytics_observation_commands")
        for name in ("analytics_002_observation_guard", "analytics_002_command_guard", "analytics_002_append_only_guard"):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    op.drop_index("ix_analytics_observation_commands_observation", table_name="analytics_observation_commands")
    op.drop_index("ix_observations_dedupe", table_name="observations")
    op.drop_index("ix_observations_subject_metric", table_name="observations")
    op.drop_table("analytics_observation_commands")
    op.drop_table("observations")
