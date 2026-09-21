"""Add append-only render failures, retry schedules and shot targets."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_004b"
down_revision = "20260920_media_004a"
branch_labels = None
depends_on = None


_FACT_TABLES = (
    "media_render_failures",
    "media_render_retry_commands",
    "media_render_rerender_targets",
)


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_render_jobs_retry_fields_validate BEFORE INSERT ON media_render_jobs "
        "WHEN NEW.max_attempts < 1 OR NEW.failure_count < 0 "
        "OR (NEW.pending_storage_object_ref IS NOT NULL AND NEW.pending_storage_object_ref NOT LIKE 'private://%') "
        "OR (NEW.pending_shot_sequence IS NOT NULL AND NEW.pending_shot_sequence < 1) "
        "BEGIN SELECT RAISE(ABORT, 'render retry fields validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_jobs_retry_fields_update_validate BEFORE UPDATE ON media_render_jobs "
        "WHEN NEW.max_attempts < 1 OR NEW.failure_count < 0 "
        "OR (NEW.pending_storage_object_ref IS NOT NULL AND NEW.pending_storage_object_ref NOT LIKE 'private://%') "
        "OR (NEW.pending_shot_sequence IS NOT NULL AND NEW.pending_shot_sequence < 1) "
        "BEGIN SELECT RAISE(ABORT, 'render retry fields validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_failures_validate BEFORE INSERT ON media_render_failures "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.attempt_count < 1 OR NEW.error_class NOT IN ('deterministic', 'transient', 'unknown') "
        "OR length(NEW.error_code) < 1 OR length(NEW.error_code) > 128 "
        "OR (NEW.error_class = 'transient' AND NEW.retryable <> 1) "
        "OR (NEW.error_class <> 'transient' AND NEW.retryable <> 0) "
        "OR lower(COALESCE(NEW.message_redacted, '')) LIKE '%model%' "
        "OR lower(COALESCE(NEW.message_redacted, '')) LIKE '%provider%' "
        "OR lower(COALESCE(NEW.message_redacted, '')) LIKE '%credential%' "
        "OR lower(COALESCE(NEW.message_redacted, '')) LIKE '%token%' "
        "OR lower(COALESCE(NEW.message_redacted, '')) LIKE '%secret%' "
        "BEGIN SELECT RAISE(ABORT, 'render failure validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_retry_schedules_validate BEFORE INSERT ON media_render_retry_schedules "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_render_failures f WHERE f.org_id = NEW.org_id AND f.id = NEW.failure_id AND f.render_job_id = NEW.render_job_id) "
        "OR NEW.attempt_count < 1 OR NEW.delay_ms < 0 "
        "OR NEW.status NOT IN ('scheduled', 'claimed', 'completed', 'cancelled') "
        "BEGIN SELECT RAISE(ABORT, 'render retry schedule validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_retry_commands_validate BEFORE INSERT ON media_render_retry_commands "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "BEGIN SELECT RAISE(ABORT, 'render retry command validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_rerender_targets_validate BEFORE INSERT ON media_render_rerender_targets "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.shot_sequence < 1 OR length(NEW.input_hash) != 64 OR NEW.input_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NEW.status NOT IN ('requested', 'confirmed', 'conflict') "
        "OR NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id AND j.input_hash = NEW.input_hash) "
        "BEGIN SELECT RAISE(ABORT, 'render shot target validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_retry_schedules_identity_guard BEFORE UPDATE ON media_render_retry_schedules "
        "WHEN NEW.org_id <> OLD.org_id OR NEW.render_job_id <> OLD.render_job_id OR NEW.attempt_count <> OLD.attempt_count "
        "OR NEW.failure_id <> OLD.failure_id OR NEW.id <> OLD.id OR NEW.delay_ms <> OLD.delay_ms "
        "BEGIN SELECT RAISE(ABORT, 'render retry schedule identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_retry_schedules_status_guard BEFORE UPDATE ON media_render_retry_schedules "
        "WHEN NOT ((OLD.status = 'scheduled' AND NEW.status IN ('claimed', 'cancelled')) "
        "OR (OLD.status = 'claimed' AND NEW.status IN ('completed', 'cancelled')) OR OLD.status = NEW.status) "
        "BEGIN SELECT RAISE(ABORT, 'render retry schedule transition invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_retry_schedules_no_delete BEFORE DELETE ON media_render_retry_schedules "
        "BEGIN SELECT RAISE(ABORT, 'render retry schedules are append-only facts'); END"
    )
    for table in _FACT_TABLES:
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_render_004b_job_fields_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.max_attempts < 1 OR NEW.failure_count < 0 "
        "OR (NEW.pending_storage_object_ref IS NOT NULL AND NEW.pending_storage_object_ref !~ '^private://') "
        "OR (NEW.pending_shot_sequence IS NOT NULL AND NEW.pending_shot_sequence < 1) "
        "THEN RAISE EXCEPTION 'render retry fields validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_jobs_retry_fields_validate BEFORE INSERT OR UPDATE ON media_render_jobs FOR EACH ROW EXECUTE FUNCTION media_render_004b_job_fields_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_failure_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.attempt_count < 1 OR NEW.error_class NOT IN ('deterministic', 'transient', 'unknown') "
        "OR (NEW.error_class = 'transient' AND NEW.retryable IS NOT TRUE) "
        "OR (NEW.error_class <> 'transient' AND NEW.retryable IS NOT FALSE) "
        "THEN RAISE EXCEPTION 'render failure validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_failures_validate BEFORE INSERT ON media_render_failures FOR EACH ROW EXECUTE FUNCTION media_render_004b_failure_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_schedule_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_render_failures f WHERE f.org_id = NEW.org_id AND f.id = NEW.failure_id AND f.render_job_id = NEW.render_job_id) "
        "OR NEW.attempt_count < 1 OR NEW.delay_ms < 0 THEN RAISE EXCEPTION 'render retry schedule validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_retry_schedules_validate BEFORE INSERT OR UPDATE ON media_render_retry_schedules FOR EACH ROW EXECUTE FUNCTION media_render_004b_schedule_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_command_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.request_hash !~ '^[A-Fa-f0-9]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL "
        "THEN RAISE EXCEPTION 'render retry command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_retry_commands_validate BEFORE INSERT ON media_render_retry_commands FOR EACH ROW EXECUTE FUNCTION media_render_004b_command_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_shot_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id AND j.input_hash = NEW.input_hash) "
        "OR NEW.shot_sequence < 1 OR NEW.input_hash !~ '^[A-Fa-f0-9]{64}$' THEN RAISE EXCEPTION 'render shot target validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_rerender_targets_validate BEFORE INSERT ON media_render_rerender_targets FOR EACH ROW EXECUTE FUNCTION media_render_004b_shot_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_schedule_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.render_job_id <> OLD.render_job_id "
        "OR NEW.attempt_count <> OLD.attempt_count OR NEW.failure_id <> OLD.failure_id OR NEW.delay_ms <> OLD.delay_ms "
        "THEN RAISE EXCEPTION 'render retry schedule identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_retry_schedules_identity_guard BEFORE UPDATE ON media_render_retry_schedules FOR EACH ROW EXECUTE FUNCTION media_render_004b_schedule_identity_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_schedule_status_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT ((OLD.status = 'scheduled' AND NEW.status IN ('claimed', 'cancelled')) "
        "OR (OLD.status = 'claimed' AND NEW.status IN ('completed', 'cancelled')) OR OLD.status = NEW.status) "
        "THEN RAISE EXCEPTION 'render retry schedule transition invalid'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_retry_schedules_status_guard BEFORE UPDATE ON media_render_retry_schedules FOR EACH ROW EXECUTE FUNCTION media_render_004b_schedule_status_guard()")
    op.execute(
        "CREATE FUNCTION media_render_004b_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _FACT_TABLES:
        op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION media_render_004b_append_only_guard()")
    op.execute("CREATE TRIGGER media_render_retry_schedules_no_delete BEFORE DELETE ON media_render_retry_schedules FOR EACH ROW EXECUTE FUNCTION media_render_004b_append_only_guard()")


def upgrade() -> None:
    # These projections make the retry fields in render-job.schema.json
    # durable without rewriting MEDIA-004A's input identity columns.
    op.add_column("media_render_jobs", sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"))
    op.add_column("media_render_jobs", sa.Column("next_retry_at", sa.String(40), nullable=True))
    op.add_column("media_render_jobs", sa.Column("last_failure_id", sa.String(36), nullable=True))
    op.add_column("media_render_jobs", sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"))
    op.add_column("media_render_jobs", sa.Column("dead_letter_reason", sa.String(256), nullable=True))
    op.add_column("media_render_jobs", sa.Column("pending_storage_object_ref", sa.String(512), nullable=True))
    op.add_column("media_render_jobs", sa.Column("pending_object_key", sa.String(512), nullable=True))
    op.add_column("media_render_jobs", sa.Column("pending_stage", sa.String(64), nullable=True))
    op.add_column("media_render_jobs", sa.Column("pending_shot_sequence", sa.Integer, nullable=True))
    op.add_column("media_render_jobs", sa.Column("pending_content_type", sa.String(128), nullable=True))
    op.create_table(
        "media_render_failures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("error_class", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=False),
        sa.Column("message_redacted", sa.String(512), nullable=True),
        sa.Column("retryable", sa.Boolean, nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("occurred_at", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("next_retry_at", sa.String(40), nullable=True),
        sa.UniqueConstraint("org_id", "render_job_id", "attempt_count", "error_code", name="uq_media_render_failures_natural"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_failures_job"),
        sa.CheckConstraint("attempt_count >= 1", name="ck_media_render_failures_attempt"),
        sa.CheckConstraint("error_class IN ('deterministic', 'transient', 'unknown')", name="ck_media_render_failures_class"),
    )
    op.create_table(
        "media_render_retry_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("failure_id", sa.String(36), nullable=False),
        sa.Column("available_at", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delay_ms", sa.Integer, nullable=False),
        sa.Column("policy_max_attempts", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("claimed_at", sa.String(40), nullable=True),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.UniqueConstraint("org_id", "render_job_id", "attempt_count", name="uq_media_render_retry_schedules_attempt"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_retry_schedules_job"),
        sa.ForeignKeyConstraint(["failure_id"], ["media_render_failures.id"], name="fk_media_render_retry_schedules_failure"),
        sa.CheckConstraint("attempt_count >= 1 AND delay_ms >= 0 AND policy_max_attempts >= 1", name="ck_media_render_retry_schedules_bounds"),
        sa.CheckConstraint("status IN ('scheduled', 'claimed', 'completed', 'cancelled')", name="ck_media_render_retry_schedules_status"),
    )
    op.create_table(
        "media_render_retry_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("command", sa.String(32), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_retry_commands_job"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_render_retry_commands_hash"),
    )
    op.create_table(
        "media_render_rerender_targets",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("shot_sequence", sa.Integer, nullable=False),
        sa.Column("output_profile_key", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("artifact_sequence", sa.Integer, nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "render_job_id", "sequence"),
        sa.UniqueConstraint("org_id", "render_job_id", "stage", "shot_sequence", "output_profile_key", name="uq_media_render_rerender_targets_natural"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_rerender_targets_job"),
        sa.CheckConstraint("sequence >= 1 AND shot_sequence >= 1", name="ck_media_render_rerender_targets_sequence"),
        sa.CheckConstraint("status IN ('requested', 'confirmed', 'conflict')", name="ck_media_render_rerender_targets_status"),
        sa.CheckConstraint("length(input_hash) = 64 AND length(request_hash) = 64", name="ck_media_render_rerender_targets_hash"),
    )
    op.create_index("ix_media_render_failures_job", "media_render_failures", ["org_id", "render_job_id", "attempt_count"])
    op.create_index("ix_media_render_retry_schedules_due", "media_render_retry_schedules", ["org_id", "status", "available_at"])
    op.create_index("ix_media_render_retry_commands_job", "media_render_retry_commands", ["org_id", "render_job_id", "created_at"])
    op.create_index("ix_media_render_rerender_targets_job", "media_render_rerender_targets", ["org_id", "render_job_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for name in (
            "media_render_jobs_retry_fields_validate", "media_render_jobs_retry_fields_update_validate",
            "media_render_retry_schedules_validate", "media_render_retry_schedules_identity_guard", "media_render_retry_schedules_status_guard", "media_render_retry_schedules_no_delete",
            "media_render_failures_validate", "media_render_retry_commands_validate", "media_render_rerender_targets_validate",
            "media_render_failures_no_update", "media_render_failures_no_delete", "media_render_retry_commands_no_update",
            "media_render_retry_commands_no_delete", "media_render_rerender_targets_no_update", "media_render_rerender_targets_no_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _FACT_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for table, trigger in (
            ("media_render_jobs", "media_render_jobs_retry_fields_validate"),
            ("media_render_failures", "media_render_failures_validate"),
            ("media_render_retry_schedules", "media_render_retry_schedules_validate"),
            ("media_render_retry_schedules", "media_render_retry_schedules_identity_guard"),
            ("media_render_retry_schedules", "media_render_retry_schedules_status_guard"),
            ("media_render_retry_schedules", "media_render_retry_schedules_no_delete"),
            ("media_render_retry_commands", "media_render_retry_commands_validate"),
            ("media_render_rerender_targets", "media_render_rerender_targets_validate"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for name in (
            "media_render_004b_job_fields_guard", "media_render_004b_failure_guard", "media_render_004b_schedule_guard", "media_render_004b_command_guard",
            "media_render_004b_shot_guard", "media_render_004b_schedule_identity_guard", "media_render_004b_schedule_status_guard", "media_render_004b_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_render_rerender_targets_job", "media_render_rerender_targets"),
        ("ix_media_render_retry_commands_job", "media_render_retry_commands"),
        ("ix_media_render_retry_schedules_due", "media_render_retry_schedules"),
        ("ix_media_render_failures_job", "media_render_failures"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_render_rerender_targets")
    op.drop_table("media_render_retry_commands")
    op.drop_table("media_render_retry_schedules")
    op.drop_table("media_render_failures")
    for column in (
        "pending_content_type", "pending_shot_sequence", "pending_stage", "pending_object_key",
        "pending_storage_object_ref", "dead_letter_reason", "failure_count", "last_failure_id",
        "next_retry_at", "max_attempts",
    ):
        op.drop_column("media_render_jobs", column)
