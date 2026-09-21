"""SUP-002 escalation facts."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_sup_002"
down_revision = "20260921_sup_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("support_escalations", sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False), sa.Column("thread_id", sa.String(36), nullable=False), sa.Column("escalation_json", sa.Text, nullable=False), sa.Column("snapshot_hash", sa.String(64), nullable=False), sa.PrimaryKeyConstraint("org_id", "id"), sa.ForeignKeyConstraint(["org_id", "thread_id"], ["support_threads.org_id", "support_threads.id"]), sa.CheckConstraint("length(snapshot_hash)=64", name="ck_support_escalation_hash"))
    if op.get_bind().dialect.name == "sqlite":
        op.execute("CREATE TRIGGER support_escalations_no_update BEFORE UPDATE ON support_escalations BEGIN SELECT RAISE(ABORT,'support escalation facts are append-only'); END")
        op.execute("CREATE TRIGGER support_escalations_no_delete BEFORE DELETE ON support_escalations BEGIN SELECT RAISE(ABORT,'support escalation facts are append-only'); END")
        op.execute("""CREATE TRIGGER support_escalations_validate BEFORE INSERT ON support_escalations BEGIN
          SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM support_threads t WHERE t.org_id=NEW.org_id AND t.id=NEW.thread_id) THEN RAISE(ABORT,'support escalation tenant mismatch') END;
        END""")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION sup_002_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'support escalation facts are append-only'; END; $$ LANGUAGE plpgsql""")
        op.execute("CREATE TRIGGER support_escalations_immutable BEFORE UPDATE OR DELETE ON support_escalations FOR EACH ROW EXECUTE FUNCTION sup_002_immutable()")


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql": op.execute("DROP TRIGGER IF EXISTS support_escalations_immutable ON support_escalations")
    elif dialect == "sqlite":
        for suffix in ("no_update", "no_delete", "validate"): op.execute(f"DROP TRIGGER IF EXISTS support_escalations_{suffix}")
    op.drop_table("support_escalations")
    if dialect == "postgresql": op.execute("DROP FUNCTION IF EXISTS sup_002_immutable()")
