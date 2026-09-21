"""ANALYTICS-004 immutable GEO quality snapshots and command references."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_analytics_004"
down_revision = "20260920_analytics_003"
branch_labels = None
depends_on = None

TABLES = ("analytics_geo_quality_snapshots", "analytics_geo_quality_commands")


def upgrade():
    op.create_table(
        TABLES[0],
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("snapshot_json", sa.Text, nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "id"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_geo_quality_snapshot_hash"),
    )
    op.create_table(
        TABLES[1],
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "snapshot_id"], [f"{TABLES[0]}.org_id", f"{TABLES[0]}.id"]),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_geo_quality_command_hash"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"""CREATE TRIGGER {TABLES[0]}_validate BEFORE INSERT ON {TABLES[0]}
        BEGIN
          SELECT CASE WHEN json_valid(NEW.snapshot_json) = 0 THEN RAISE(ABORT, 'invalid GEO quality JSON') END;
          SELECT CASE WHEN json_extract(NEW.snapshot_json, '$.org_id') IS NOT NEW.org_id
            OR json_extract(NEW.snapshot_json, '$.id') IS NOT NEW.id
            OR json_extract(NEW.snapshot_json, '$.snapshot_hash') IS NOT NEW.snapshot_hash
            OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*'
            OR json_type(NEW.snapshot_json, '$.input_observation_ids') IS NOT 'array'
            OR json_array_length(NEW.snapshot_json, '$.input_observation_ids') < 1
            THEN RAISE(ABORT, 'invalid GEO quality binding') END;
          SELECT CASE WHEN EXISTS (
            SELECT 1 FROM json_each(NEW.snapshot_json, '$.input_observation_ids') i
            WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.org_id = NEW.org_id AND o.id = i.value)
          ) THEN RAISE(ABORT, 'GEO quality input tenant mismatch') END;
        END""")
        op.execute(f"""CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]}
        WHEN NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR NOT EXISTS (
          SELECT 1 FROM {TABLES[0]} s WHERE s.org_id = NEW.org_id AND s.id = NEW.snapshot_id)
        BEGIN SELECT RAISE(ABORT, 'invalid GEO quality command'); END""")
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'GEO quality facts are append-only'); END")
    elif dialect == "postgresql":
        op.execute("""CREATE FUNCTION analytics_004_snapshot_guard() RETURNS trigger AS $$
        DECLARE body jsonb;
        BEGIN
          body := NEW.snapshot_json::jsonb;
          IF body->>'org_id' IS DISTINCT FROM NEW.org_id OR body->>'id' IS DISTINCT FROM NEW.id
            OR body->>'snapshot_hash' IS DISTINCT FROM NEW.snapshot_hash
            OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$'
            OR jsonb_typeof(body->'input_observation_ids') IS DISTINCT FROM 'array'
          THEN RAISE EXCEPTION 'invalid GEO quality binding'; END IF;
          IF jsonb_array_length(body->'input_observation_ids') < 1 OR EXISTS (
            SELECT 1 FROM jsonb_array_elements_text(body->'input_observation_ids') AS i(value)
            WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.org_id = NEW.org_id AND o.id = i.value)
          ) THEN RAISE EXCEPTION 'GEO quality input tenant mismatch'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[0]}_validate BEFORE INSERT ON {TABLES[0]} FOR EACH ROW EXECUTE FUNCTION analytics_004_snapshot_guard()")
        op.execute("""CREATE FUNCTION analytics_004_command_guard() RETURNS trigger AS $$ BEGIN
          IF NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR NOT EXISTS (
            SELECT 1 FROM analytics_geo_quality_snapshots s WHERE s.org_id = NEW.org_id AND s.id = NEW.snapshot_id)
          THEN RAISE EXCEPTION 'invalid GEO quality command'; END IF; RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]} FOR EACH ROW EXECUTE FUNCTION analytics_004_command_guard()")
        op.execute("""CREATE FUNCTION analytics_004_immutable() RETURNS trigger AS $$ BEGIN
          RAISE EXCEPTION 'GEO quality facts are append-only'; END; $$ LANGUAGE plpgsql""")
        for table in TABLES:
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION analytics_004_immutable()")


def downgrade():
    dialect = op.get_bind().dialect.name
    for table in reversed(TABLES):
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_validate ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
        elif dialect == "sqlite":
            for suffix in ("validate", "no_update", "no_delete"):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
        op.drop_table(table)
    if dialect == "postgresql":
        for function in ("analytics_004_snapshot_guard", "analytics_004_command_guard", "analytics_004_immutable"):
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
