"""FEEDBACK-EXP-001 experiment and sample facts."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_feedback_exp_001"
down_revision = "20260921_feedback_core_005"
branch_labels = None
depends_on = None
TABLES = ("feedback_experiments", "feedback_experiment_samples", "feedback_experiment_commands")


def upgrade():
    op.create_table(TABLES[0], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False), sa.Column("version_no", sa.Integer, nullable=False), sa.Column("experiment_json", sa.Text, nullable=False), sa.Column("snapshot_hash", sa.String(64), nullable=False), sa.PrimaryKeyConstraint("org_id", "id", "version_no"), sa.CheckConstraint("version_no >= 1", name="ck_feedback_exp_version"), sa.CheckConstraint("length(snapshot_hash)=64", name="ck_feedback_exp_hash"))
    op.create_table(TABLES[1], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False), sa.Column("experiment_id", sa.String(36), nullable=False), sa.Column("sample_json", sa.Text, nullable=False), sa.Column("sample_hash", sa.String(64), nullable=False), sa.PrimaryKeyConstraint("org_id", "id"), sa.ForeignKeyConstraint(["org_id", "experiment_id"], [f"{TABLES[0]}.org_id", f"{TABLES[0]}.id"]), sa.CheckConstraint("length(sample_hash)=64", name="ck_feedback_exp_sample_hash"))
    op.create_table(TABLES[2], sa.Column("org_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("aggregate_id", sa.String(36), nullable=False), sa.Column("aggregate_version", sa.Integer, nullable=False), sa.PrimaryKeyConstraint("org_id", "idempotency_key"), sa.CheckConstraint("length(request_hash)=64", name="ck_feedback_exp_command_hash"))
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'experiment facts are append-only'); END")
        op.execute(f"""CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]} BEGIN
          SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM {TABLES[0]} e WHERE e.org_id=NEW.org_id AND e.id=NEW.experiment_id) THEN RAISE(ABORT,'experiment tenant mismatch') END;
        END""")
        op.execute(f"""CREATE TRIGGER {TABLES[2]}_validate BEFORE INSERT ON {TABLES[2]} WHEN NEW.request_hash GLOB '*[^0-9A-Fa-f]*' BEGIN SELECT RAISE(ABORT,'invalid experiment command'); END""")
    elif dialect == "postgresql":
        op.execute("""CREATE FUNCTION feedback_exp_001_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'experiment facts are append-only'; END; $$ LANGUAGE plpgsql""")
        for table in TABLES: op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION feedback_exp_001_immutable()")
        op.execute("""CREATE FUNCTION feedback_exp_001_sample_guard() RETURNS trigger AS $$ BEGIN IF NOT EXISTS (SELECT 1 FROM feedback_experiments e WHERE e.org_id=NEW.org_id AND e.id=NEW.experiment_id) THEN RAISE EXCEPTION 'experiment tenant mismatch'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql""")
        op.execute(f"CREATE TRIGGER {TABLES[1]}_validate BEFORE INSERT ON {TABLES[1]} FOR EACH ROW EXECUTE FUNCTION feedback_exp_001_sample_guard()")


def downgrade():
    dialect = op.get_bind().dialect.name
    for table in reversed(TABLES):
        if dialect == "postgresql": op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}"); op.execute(f"DROP TRIGGER IF EXISTS {table}_validate ON {table}")
        elif dialect == "sqlite":
            for suffix in ("no_update", "no_delete", "validate"): op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
        op.drop_table(table)
    if dialect == "postgresql":
        for function in ("feedback_exp_001_immutable", "feedback_exp_001_sample_guard"): op.execute(f"DROP FUNCTION IF EXISTS {function}()")
