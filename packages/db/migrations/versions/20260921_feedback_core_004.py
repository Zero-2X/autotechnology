"""FEEDBACK-CORE-004 immutable recommendation projections."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_feedback_core_004"
down_revision = "20260921_feedback_core_003"
branch_labels = None
depends_on = None

TABLES = ("feedback_recommendations", "feedback_recommendation_commands")


def upgrade():
    op.create_table(TABLES[0], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False),
                    sa.Column("recommendation_json", sa.Text, nullable=False), sa.Column("snapshot_hash", sa.String(64), nullable=False),
                    sa.PrimaryKeyConstraint("org_id", "id"), sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_feedback_rec_hash"))
    op.create_table(TABLES[1], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False),
                    sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("recommendation_id", sa.String(36), nullable=False),
                    sa.PrimaryKeyConstraint("org_id", "idempotency_key"), sa.ForeignKeyConstraint(["org_id", "recommendation_id"], [f"{TABLES[0]}.org_id", f"{TABLES[0]}.id"]),
                    sa.CheckConstraint("length(request_hash) = 64", name="ck_feedback_rec_command_hash"))
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(f"""CREATE TRIGGER {TABLES[0]}_validate BEFORE INSERT ON {TABLES[0]} BEGIN
          SELECT CASE WHEN json_valid(NEW.recommendation_json)=0 OR json_extract(NEW.recommendation_json,'$.org_id') IS NOT NEW.org_id
            OR json_extract(NEW.recommendation_json,'$.id') IS NOT NEW.id OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*'
            THEN RAISE(ABORT,'invalid Feedback recommendation') END;
          SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM feedback_items f WHERE f.org_id=NEW.org_id AND f.id=json_extract(NEW.recommendation_json,'$.feedback_item_id'))
            THEN RAISE(ABORT,'Feedback recommendation item tenant mismatch') END;
        END""")
        op.execute(f"""CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]}
          WHEN NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR NOT EXISTS (SELECT 1 FROM {TABLES[0]} r WHERE r.org_id=NEW.org_id AND r.id=NEW.recommendation_id)
          BEGIN SELECT RAISE(ABORT,'invalid Feedback recommendation command'); END""")
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Feedback recommendation facts are append-only'); END")
    elif dialect == "postgresql":
        op.execute("""CREATE FUNCTION feedback_core_004_guard() RETURNS trigger AS $$ DECLARE body jsonb; BEGIN body:=NEW.recommendation_json::jsonb;
          IF body->>'org_id' IS DISTINCT FROM NEW.org_id OR body->>'id' IS DISTINCT FROM NEW.id OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$'
          THEN RAISE EXCEPTION 'invalid Feedback recommendation'; END IF;
          IF NOT EXISTS (SELECT 1 FROM feedback_items f WHERE f.org_id=NEW.org_id AND f.id=body->>'feedback_item_id')
          THEN RAISE EXCEPTION 'Feedback recommendation item tenant mismatch'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[0]}_validate BEFORE INSERT ON {TABLES[0]} FOR EACH ROW EXECUTE FUNCTION feedback_core_004_guard()")
        op.execute("""CREATE FUNCTION feedback_core_004_command_guard() RETURNS trigger AS $$ BEGIN
          IF NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR NOT EXISTS (SELECT 1 FROM feedback_recommendations r WHERE r.org_id=NEW.org_id AND r.id=NEW.recommendation_id)
          THEN RAISE EXCEPTION 'invalid Feedback recommendation command'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]} FOR EACH ROW EXECUTE FUNCTION feedback_core_004_command_guard()")
        op.execute("""CREATE FUNCTION feedback_core_004_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Feedback recommendation facts are append-only'; END; $$ LANGUAGE plpgsql""")
        for table in TABLES:
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION feedback_core_004_immutable()")


def downgrade():
    dialect = op.get_bind().dialect.name
    for table in reversed(TABLES):
        if dialect == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_validate ON {table}"); op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
        elif dialect == "sqlite":
            for suffix in ("validate", "no_update", "no_delete"): op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
        op.drop_table(table)
    if dialect == "postgresql":
        for function in ("feedback_core_004_guard", "feedback_core_004_command_guard", "feedback_core_004_immutable"):
            op.execute(f"DROP FUNCTION IF EXISTS {function}()")
