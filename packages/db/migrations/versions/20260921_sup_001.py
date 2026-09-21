"""SUP-001 support thread/message/draft facts."""
from alembic import op
import sqlalchemy as sa

revision = "20260921_sup_001"
down_revision = "20260921_feedback_exp_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("support_threads", sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False), sa.Column("thread_json", sa.Text, nullable=False), sa.Column("snapshot_hash", sa.String(64), nullable=False), sa.PrimaryKeyConstraint("org_id", "id"), sa.CheckConstraint("length(snapshot_hash)=64", name="ck_support_thread_hash"))
    op.create_table("support_messages", sa.Column("org_id", sa.String(36), nullable=False), sa.Column("id", sa.String(36), nullable=False), sa.Column("thread_id", sa.String(36), nullable=False), sa.Column("message_json", sa.Text, nullable=False), sa.Column("message_hash", sa.String(64), nullable=False), sa.PrimaryKeyConstraint("org_id", "id"), sa.ForeignKeyConstraint(["org_id", "thread_id"], ["support_threads.org_id", "support_threads.id"]), sa.CheckConstraint("length(message_hash)=64", name="ck_support_message_hash"))
    op.create_table("support_commands", sa.Column("org_id", sa.String(36), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("aggregate_id", sa.String(36), nullable=False), sa.PrimaryKeyConstraint("org_id", "idempotency_key"), sa.CheckConstraint("length(request_hash)=64", name="ck_support_command_hash"))
    if op.get_bind().dialect.name == "sqlite":
        for table in ("support_threads", "support_messages", "support_commands"):
            for action in ("UPDATE", "DELETE"): op.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'support facts are append-only'); END")
        op.execute("""CREATE TRIGGER support_messages_validate BEFORE INSERT ON support_messages BEGIN
          SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM support_threads t WHERE t.org_id=NEW.org_id AND t.id=NEW.thread_id) THEN RAISE(ABORT,'support thread tenant mismatch') END;
        END""")
    elif op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION sup_001_immutable() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'support facts are append-only'; END; $$ LANGUAGE plpgsql""")
        for table in ("support_threads", "support_messages", "support_commands"): op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION sup_001_immutable()")


def downgrade():
    dialect = op.get_bind().dialect.name
    for table in ("support_commands", "support_messages", "support_threads"):
        if dialect == "postgresql": op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
        elif dialect == "sqlite":
            for suffix in ("no_update", "no_delete", "validate"): op.execute(f"DROP TRIGGER IF EXISTS {table}_{suffix}")
        op.drop_table(table)
    if dialect == "postgresql": op.execute("DROP FUNCTION IF EXISTS sup_001_immutable()")
