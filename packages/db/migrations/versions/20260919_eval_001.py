"""EVAL-001 adds immutable prompt, golden-set, threshold, and run evidence."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_found_eval_001"
down_revision = "20260919_found_model_001"
branch_labels = None
depends_on = None


IMMUTABLE_TABLES = (
    "evaluation_prompt_versions",
    "evaluation_golden_set_versions",
    "evaluation_threshold_versions",
    "eval_runs",
    "evaluation_commands",
)


def upgrade() -> None:
    op.create_table(
        "evaluation_prompt_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("prompt_key", sa.String(128), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "prompt_key", "version_no"),
        sa.CheckConstraint("version_no >= 1", name="ck_evaluation_prompt_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_evaluation_prompt_hash"),
    )
    op.create_table(
        "evaluation_golden_set_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("dataset_key", sa.String(128), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "dataset_key", "version_no"),
        sa.CheckConstraint("version_no >= 1", name="ck_evaluation_golden_set_version"),
        sa.CheckConstraint("length(dataset_hash) = 64", name="ck_evaluation_dataset_hash"),
    )
    op.create_table(
        "evaluation_threshold_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("threshold_key", sa.String(128), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "threshold_key", "version_no"),
        sa.CheckConstraint("version_no >= 1", name="ck_evaluation_threshold_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_evaluation_threshold_hash"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("prompt_version_id", sa.String(36), nullable=False),
        sa.Column("dataset_version_id", sa.String(36), nullable=False),
        sa.Column("threshold_version_id", sa.String(36), nullable=False),
        sa.Column("model_config_id", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gate_status", sa.String(16), nullable=False),
        sa.Column("total_cost_cents", sa.Integer, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "request_hash"),
        sa.ForeignKeyConstraint(
            ["org_id", "prompt_version_id"],
            ["evaluation_prompt_versions.org_id", "evaluation_prompt_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "dataset_version_id"],
            ["evaluation_golden_set_versions.org_id", "evaluation_golden_set_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "threshold_version_id"],
            ["evaluation_threshold_versions.org_id", "evaluation_threshold_versions.id"],
        ),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_eval_run_request_hash"),
        sa.CheckConstraint("status IN ('completed', 'failed')", name="ck_eval_run_status"),
        sa.CheckConstraint("gate_status IN ('passed', 'failed')", name="ck_eval_run_gate_status"),
        sa.CheckConstraint("total_cost_cents >= 0", name="ck_eval_run_cost"),
    )
    op.create_table(
        "evaluation_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_type", sa.String(32), nullable=False),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_evaluation_command_hash"),
    )
    op.create_index(
        "ix_evaluation_prompt_versions_lookup",
        "evaluation_prompt_versions",
        ["org_id", "prompt_key", "version_no"],
    )
    op.create_index(
        "ix_evaluation_golden_sets_lookup",
        "evaluation_golden_set_versions",
        ["org_id", "dataset_key", "version_no"],
    )
    op.create_index(
        "ix_eval_runs_lookup",
        "eval_runs",
        ["org_id", "dataset_version_id", "created_at"],
    )
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in IMMUTABLE_TABLES:
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                )
    elif dialect == "postgresql":
        op.execute(
            "CREATE FUNCTION evaluation_immutable_rows() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'evaluation rows are append-only'; END; $$ LANGUAGE plpgsql"
        )
        for table in IMMUTABLE_TABLES:
            op.execute(
                f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION evaluation_immutable_rows()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in IMMUTABLE_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        op.execute("DROP FUNCTION IF EXISTS evaluation_immutable_rows()")
    op.drop_index("ix_eval_runs_lookup", table_name="eval_runs")
    op.drop_index("ix_evaluation_golden_sets_lookup", table_name="evaluation_golden_set_versions")
    op.drop_index("ix_evaluation_prompt_versions_lookup", table_name="evaluation_prompt_versions")
    op.drop_table("evaluation_commands")
    op.drop_table("eval_runs")
    op.drop_table("evaluation_threshold_versions")
    op.drop_table("evaluation_golden_set_versions")
    op.drop_table("evaluation_prompt_versions")
