"""MODEL-003 adds versioned budget policy and model cost ledger boundaries."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_model_003"
down_revision = "20260919_found_eval_001"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "model_budget_policies",
    "model_budget_usage",
    "model_budget_commands",
)


def upgrade() -> None:
    op.create_table(
        "model_budget_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(256), nullable=False),
        sa.Column("policy_key", sa.String(200), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "policy_key", "version_no"),
        sa.CheckConstraint("version_no >= 1", name="ck_model_budget_policy_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_model_budget_policy_hash"),
    )
    op.create_table(
        "model_budget_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(256), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(200), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("call_id", sa.String(200), nullable=False),
        sa.Column("requested_cents", sa.Integer, nullable=False),
        sa.Column("cost_cents", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "call_id"),
        sa.ForeignKeyConstraint(["org_id", "policy_id"], ["model_budget_policies.org_id", "model_budget_policies.id"]),
        sa.CheckConstraint("requested_cents >= 0", name="ck_model_budget_usage_requested"),
        sa.CheckConstraint("cost_cents >= 0", name="ck_model_budget_usage_cost"),
    )
    op.create_table(
        "model_budget_reservations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(256), nullable=False),
        sa.Column("policy_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(200), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("requested_cents", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("settled_at", sa.String(40), nullable=True),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "policy_id"], ["model_budget_policies.org_id", "model_budget_policies.id"]),
        sa.CheckConstraint("requested_cents >= 0", name="ck_model_budget_reservation_requested"),
        sa.CheckConstraint("status IN ('reserved', 'settled', 'released')", name="ck_model_budget_reservation_status"),
    )
    op.create_table(
        "model_budget_commands",
        sa.Column("org_id", sa.String(256), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(256), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_model_budget_command_hash"),
    )
    op.create_index("ix_model_budget_usage_org_task", "model_budget_usage", ["org_id", "task_id", "occurred_at"])
    op.create_index("ix_model_budget_usage_org_model", "model_budget_usage", ["org_id", "model", "occurred_at"])
    op.create_index("ix_model_budget_reservations_active", "model_budget_reservations", ["org_id", "status", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        for table in IMMUTABLE_TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                )
    elif op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION model_budget_immutable_rows() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'model budget rows are append-only'; END; $$ LANGUAGE plpgsql"
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION model_budget_immutable_rows()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        op.execute("DROP FUNCTION IF EXISTS model_budget_immutable_rows()")
    op.drop_index("ix_model_budget_reservations_active", table_name="model_budget_reservations")
    op.drop_index("ix_model_budget_usage_org_model", table_name="model_budget_usage")
    op.drop_index("ix_model_budget_usage_org_task", table_name="model_budget_usage")
    op.drop_table("model_budget_commands")
    op.drop_table("model_budget_reservations")
    op.drop_table("model_budget_usage")
    op.drop_table("model_budget_policies")
