"""FEEDBACK-CORE-003 immutable FeedbackItem versions and commands."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_feedback_core_003"
down_revision = "20260921_analytics_004"
branch_labels = None
depends_on = None

TABLES = ("feedback_items", "feedback_item_commands")


def upgrade():
    op.create_table(
        TABLES[0], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False), sa.Column("item_json", sa.Text, nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False), sa.PrimaryKeyConstraint("org_id", "id", "version_no"),
        sa.CheckConstraint("version_no >= 1", name="ck_feedback_item_version"), sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_feedback_item_hash"),
    )
    op.create_table(
        TABLES[1], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False), sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "item_id", "version_no"], [f"{TABLES[0]}.org_id", f"{TABLES[0]}.id", f"{TABLES[0]}.version_no"]),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_feedback_command_hash"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"""CREATE TRIGGER {TABLES[0]}_validate BEFORE INSERT ON {TABLES[0]} BEGIN
          SELECT CASE WHEN json_valid(NEW.item_json) = 0 OR json_extract(NEW.item_json, '$.org_id') IS NOT NEW.org_id
            OR json_extract(NEW.item_json, '$.id') IS NOT NEW.id OR json_extract(NEW.item_json, '$.status') IS NULL
            OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' THEN RAISE(ABORT, 'invalid FeedbackItem binding') END;
          SELECT CASE WHEN json_type(NEW.item_json, '$.observation_ids') IS NOT 'array' OR json_array_length(NEW.item_json, '$.observation_ids') < 1
            THEN RAISE(ABORT, 'FeedbackItem observations required') END;
          SELECT CASE WHEN EXISTS (SELECT 1 FROM json_each(NEW.item_json, '$.observation_ids') i
            WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.org_id = NEW.org_id AND o.id = i.value))
            THEN RAISE(ABORT, 'FeedbackItem observation tenant mismatch') END;
        END""")
        op.execute(f"""CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]}
          WHEN NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR NOT EXISTS (SELECT 1 FROM {TABLES[0]} i WHERE i.org_id=NEW.org_id AND i.id=NEW.item_id AND i.version_no=NEW.version_no)
          BEGIN SELECT RAISE(ABORT, 'invalid FeedbackItem command'); END""")
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'FeedbackItem facts are append-only'); END")
    elif dialect == "postgresql":
        op.execute("""CREATE FUNCTION feedback_core_003_item_guard() RETURNS trigger AS $$
        DECLARE body jsonb;
        BEGIN body := NEW.item_json::jsonb;
          IF body->>'org_id' IS DISTINCT FROM NEW.org_id OR body->>'id' IS DISTINCT FROM NEW.id OR body->>'status' IS NULL OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$'
          THEN RAISE EXCEPTION 'invalid FeedbackItem binding'; END IF;
          IF jsonb_array_length(body->'observation_ids') < 1 OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(body->'observation_ids') AS i(value)
            WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.org_id=NEW.org_id AND o.id=i.value))
          THEN RAISE EXCEPTION 'FeedbackItem observation tenant mismatch'; END IF; RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[0]}_validate BEFORE INSERT ON {TABLES[0]} FOR EACH ROW EXECUTE FUNCTION feedback_core_003_item_guard()")
        op.execute("""CREATE FUNCTION feedback_core_003_command_guard() RETURNS trigger AS $$ BEGIN
          IF NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR NOT EXISTS (SELECT 1 FROM feedback_items i WHERE i.org_id=NEW.org_id AND i.id=NEW.item_id AND i.version_no=NEW.version_no)
          THEN RAISE EXCEPTION 'invalid FeedbackItem command'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]} FOR EACH ROW EXECUTE FUNCTION feedback_core_003_command_guard()")
        op.execute("""CREATE FUNCTION feedback_core_003_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'FeedbackItem facts are append-only'; END; $$ LANGUAGE plpgsql""")
        for table in TABLES:
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION feedback_core_003_immutable()")


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
        for function in ("feedback_core_003_item_guard", "feedback_core_003_command_guard", "feedback_core_003_immutable"):
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
