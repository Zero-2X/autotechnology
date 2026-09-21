"""MEDIA-004A input-locked render jobs and private artifact facts."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_004a"
down_revision = "20260920_media_003c"
branch_labels = None
depends_on = None


_APPEND_ONLY = (
    "media_render_job_inputs",
    "media_render_artifacts",
    "media_render_commands",
)


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_render_jobs_validate BEFORE INSERT ON media_render_jobs "
        "WHEN json_valid(NEW.output_profile_json) = 0 OR json_type(NEW.output_profile_json) != 'object' "
        "OR json_extract(NEW.output_profile_json, '$.profile_key') != NEW.output_profile_key "
        "OR json_valid(NEW.input_snapshot_hashes_json) = 0 OR json_type(NEW.input_snapshot_hashes_json) != 'object' "
        "OR length(NEW.input_hash) != 64 OR NEW.input_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NEW.asset_version_no IS NOT NULL AND NEW.asset_version_no < 1 "
        "OR lower(NEW.output_profile_json) LIKE '%\"model\"%' OR lower(NEW.output_profile_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.output_profile_json) LIKE '%\"credential\"%' OR lower(NEW.output_profile_json) LIKE '%\"token\"%' "
        "OR lower(NEW.output_profile_json) LIKE '%\"secret\"%' OR lower(NEW.output_profile_json) LIKE '%\"password\"%' "
        "OR lower(NEW.output_profile_json) LIKE '%\"authorization\"%' OR lower(NEW.output_profile_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.output_profile_json) LIKE '%\"raw_output\"%' "
        "OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"model\"%' OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"credential\"%' OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"token\"%' "
        "OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"secret\"%' OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"password\"%' "
        "OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"authorization\"%' OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.input_snapshot_hashes_json) LIKE '%\"raw_output\"%' "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions s WHERE s.org_id = NEW.org_id "
        "AND s.id = NEW.media_script_version_id AND s.snapshot_hash = json_extract(NEW.input_snapshot_hashes_json, '$.script')) "
        "OR (NEW.media_storyboard_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_storyboard_versions b WHERE b.org_id = NEW.org_id "
        "AND b.id = NEW.media_storyboard_version_id AND b.snapshot_hash = json_extract(NEW.input_snapshot_hashes_json, '$.storyboard'))) "
        "OR (NEW.media_subtitle_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_subtitle_versions u WHERE u.org_id = NEW.org_id "
        "AND u.id = NEW.media_subtitle_version_id AND u.snapshot_hash = json_extract(NEW.input_snapshot_hashes_json, '$.subtitle'))) "
        "OR NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions v WHERE v.org_id = NEW.org_id "
        "AND v.id = NEW.media_visual_asset_set_version_id AND v.snapshot_hash = json_extract(NEW.input_snapshot_hashes_json, '$.visual_asset_set')) "
        "OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions o WHERE o.org_id = NEW.org_id "
        "AND o.id = NEW.media_output_spec_version_id AND o.snapshot_hash = json_extract(NEW.input_snapshot_hashes_json, '$.output_spec')) "
        "BEGIN SELECT RAISE(ABORT, 'render job input lock validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_jobs_identity_guard BEFORE UPDATE ON media_render_jobs "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.asset_version_id != OLD.asset_version_id "
        "OR COALESCE(NEW.asset_version_no, 0) != COALESCE(OLD.asset_version_no, 0) "
        "OR NEW.media_script_version_id != OLD.media_script_version_id "
        "OR COALESCE(NEW.media_storyboard_version_id, '') != COALESCE(OLD.media_storyboard_version_id, '') "
        "OR COALESCE(NEW.media_subtitle_version_id, '') != COALESCE(OLD.media_subtitle_version_id, '') "
        "OR NEW.media_visual_asset_set_version_id != OLD.media_visual_asset_set_version_id "
        "OR NEW.media_output_spec_version_id != OLD.media_output_spec_version_id "
        "OR NEW.output_profile_key != OLD.output_profile_key OR NEW.output_profile_json != OLD.output_profile_json "
        "OR NEW.input_hash != OLD.input_hash OR NEW.input_snapshot_hashes_json != OLD.input_snapshot_hashes_json "
        "OR NEW.region_profile_version_id != OLD.region_profile_version_id OR NEW.policy_snapshot_id != OLD.policy_snapshot_id "
        "BEGIN SELECT RAISE(ABORT, 'render job inputs are immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_jobs_status_guard BEFORE UPDATE ON media_render_jobs "
        "WHEN NOT ((OLD.status = 'planned' AND NEW.status IN ('running', 'failed', 'unknown', 'retry_scheduled')) "
        "OR (OLD.status = 'running' AND NEW.status IN ('succeeded', 'failed', 'unknown', 'retry_scheduled')) "
        "OR (OLD.status = 'failed' AND NEW.status IN ('retry_scheduled', 'running', 'dead_letter')) "
        "OR (OLD.status = 'retry_scheduled' AND NEW.status IN ('running', 'failed', 'dead_letter')) "
        "OR (OLD.status = 'unknown' AND NEW.status IN ('failed', 'dead_letter', 'succeeded')) "
        "OR (OLD.status = NEW.status)) "
        "BEGIN SELECT RAISE(ABORT, 'render job status transition invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_job_inputs_validate BEFORE INSERT ON media_render_job_inputs "
        "WHEN NEW.input_kind NOT IN ('script', 'storyboard', 'subtitle', 'visual_asset_set', 'output_spec', 'asset_version') "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR (NEW.input_kind = 'script' AND NOT EXISTS (SELECT 1 FROM media_script_versions v WHERE v.org_id = NEW.org_id AND v.id = NEW.input_version_id AND v.snapshot_hash = NEW.snapshot_hash)) "
        "OR (NEW.input_kind = 'storyboard' AND NOT EXISTS (SELECT 1 FROM media_storyboard_versions v WHERE v.org_id = NEW.org_id AND v.id = NEW.input_version_id AND v.snapshot_hash = NEW.snapshot_hash)) "
        "OR (NEW.input_kind = 'subtitle' AND NOT EXISTS (SELECT 1 FROM media_subtitle_versions v WHERE v.org_id = NEW.org_id AND v.id = NEW.input_version_id AND v.snapshot_hash = NEW.snapshot_hash)) "
        "OR (NEW.input_kind = 'visual_asset_set' AND NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions v WHERE v.org_id = NEW.org_id AND v.id = NEW.input_version_id AND v.snapshot_hash = NEW.snapshot_hash)) "
        "OR (NEW.input_kind = 'output_spec' AND NOT EXISTS (SELECT 1 FROM media_output_spec_versions v WHERE v.org_id = NEW.org_id AND v.id = NEW.input_version_id AND v.snapshot_hash = NEW.snapshot_hash)) "
        "BEGIN SELECT RAISE(ABORT, 'render job input fact invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_artifacts_validate BEFORE INSERT ON media_render_artifacts "
        "WHEN NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR NEW.storage_object_ref NOT LIKE 'private://%' OR length(NEW.content_hash) != 64 OR NEW.content_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NEW.size_bytes < 0 OR length(NEW.input_hash) != 64 OR NEW.input_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id AND j.input_hash = NEW.input_hash) "
        "OR NEW.stage NOT GLOB '[a-z]*' OR NEW.output_profile_key NOT GLOB '[a-z]*' "
        "BEGIN SELECT RAISE(ABORT, 'render artifact validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_commands_validate BEFORE INSERT ON media_render_commands "
        "WHEN length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.response_json) = 0 OR NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "BEGIN SELECT RAISE(ABORT, 'render command validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_render_artifacts_no_replace BEFORE INSERT ON media_render_artifacts "
        "WHEN EXISTS (SELECT 1 FROM media_render_artifacts prior WHERE prior.org_id = NEW.org_id AND prior.render_job_id = NEW.render_job_id "
        "AND prior.stage = NEW.stage AND COALESCE(prior.shot_sequence, 0) = COALESCE(NEW.shot_sequence, 0) "
        "AND prior.output_profile_key = NEW.output_profile_key) "
        "BEGIN SELECT RAISE(ABORT, 'render artifact natural key already exists'); END"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_render_jobs_validate() RETURNS trigger AS $$ BEGIN "
        "IF jsonb_typeof(NEW.output_profile_json::jsonb) <> 'object' OR NEW.output_profile_key <> NEW.output_profile_json::jsonb->>'profile_key' "
        "OR jsonb_typeof(NEW.input_snapshot_hashes_json::jsonb) <> 'object' OR NEW.input_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR lower(NEW.output_profile_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "OR lower(NEW.input_snapshot_hashes_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions s WHERE s.org_id = NEW.org_id AND s.id = NEW.media_script_version_id AND s.snapshot_hash = NEW.input_snapshot_hashes_json::jsonb->>'script') "
        "OR (NEW.media_storyboard_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_storyboard_versions b WHERE b.org_id = NEW.org_id AND b.id = NEW.media_storyboard_version_id AND b.snapshot_hash = NEW.input_snapshot_hashes_json::jsonb->>'storyboard')) "
        "OR (NEW.media_subtitle_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_subtitle_versions u WHERE u.org_id = NEW.org_id AND u.id = NEW.media_subtitle_version_id AND u.snapshot_hash = NEW.input_snapshot_hashes_json::jsonb->>'subtitle')) "
        "OR NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions v WHERE v.org_id = NEW.org_id AND v.id = NEW.media_visual_asset_set_version_id AND v.snapshot_hash = NEW.input_snapshot_hashes_json::jsonb->>'visual_asset_set') "
        "OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions o WHERE o.org_id = NEW.org_id AND o.id = NEW.media_output_spec_version_id AND o.snapshot_hash = NEW.input_snapshot_hashes_json::jsonb->>'output_spec') "
        "THEN RAISE EXCEPTION 'render job input lock validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_jobs_validate BEFORE INSERT ON media_render_jobs FOR EACH ROW EXECUTE FUNCTION media_render_jobs_validate()")
    op.execute(
        "CREATE FUNCTION media_render_jobs_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.asset_version_id <> OLD.asset_version_id "
        "OR COALESCE(NEW.asset_version_no, 0) <> COALESCE(OLD.asset_version_no, 0) "
        "OR NEW.media_script_version_id <> OLD.media_script_version_id OR NEW.media_visual_asset_set_version_id <> OLD.media_visual_asset_set_version_id "
        "OR NEW.media_output_spec_version_id <> OLD.media_output_spec_version_id OR NEW.output_profile_key <> OLD.output_profile_key "
        "OR NEW.output_profile_json <> OLD.output_profile_json OR NEW.input_hash <> OLD.input_hash OR NEW.input_snapshot_hashes_json <> OLD.input_snapshot_hashes_json "
        "OR NEW.region_profile_version_id <> OLD.region_profile_version_id OR NEW.policy_snapshot_id <> OLD.policy_snapshot_id "
        "THEN RAISE EXCEPTION 'render job inputs are immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_jobs_identity_guard BEFORE UPDATE ON media_render_jobs FOR EACH ROW EXECUTE FUNCTION media_render_jobs_identity_guard()")
    op.execute(
        "CREATE FUNCTION media_render_job_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION media_render_job_append_only_guard()")
    op.execute(
        "CREATE FUNCTION media_render_artifacts_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.storage_object_ref !~ '^private://' OR NEW.content_hash !~ '^[0-9A-Fa-f]{64}$' OR NEW.input_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id AND j.input_hash = NEW.input_hash) "
        "THEN RAISE EXCEPTION 'render artifact validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_artifacts_guard BEFORE INSERT ON media_render_artifacts FOR EACH ROW EXECUTE FUNCTION media_render_artifacts_guard()")
    op.execute(
        "CREATE FUNCTION media_render_commands_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL "
        "OR NOT EXISTS (SELECT 1 FROM media_render_jobs j WHERE j.org_id = NEW.org_id AND j.id = NEW.render_job_id) "
        "THEN RAISE EXCEPTION 'render command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_render_commands_guard BEFORE INSERT ON media_render_commands FOR EACH ROW EXECUTE FUNCTION media_render_commands_guard()")


def upgrade() -> None:
    op.create_table(
        "media_render_jobs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False), sa.Column("asset_version_no", sa.Integer, nullable=True),
        sa.Column("media_script_version_id", sa.String(36), nullable=False), sa.Column("media_storyboard_version_id", sa.String(36), nullable=True),
        sa.Column("media_subtitle_version_id", sa.String(36), nullable=True), sa.Column("media_visual_asset_set_version_id", sa.String(36), nullable=False),
        sa.Column("media_output_spec_version_id", sa.String(36), nullable=False), sa.Column("output_profile_key", sa.String(64), nullable=False),
        sa.Column("output_profile_json", sa.Text, nullable=False), sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False), sa.Column("policy_snapshot_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False), sa.Column("input_snapshot_hashes_json", sa.Text, nullable=False),
        sa.Column("artifact_count", sa.Integer, nullable=False), sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True), sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False), sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_render_jobs_org_id"),
        sa.UniqueConstraint("org_id", "input_hash", name="uq_media_render_jobs_input_hash"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_render_jobs_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_render_jobs_storyboard"),
        sa.ForeignKeyConstraint(["org_id", "media_subtitle_version_id"], ["media_subtitle_versions.org_id", "media_subtitle_versions.id"], name="fk_media_render_jobs_subtitle"),
        sa.ForeignKeyConstraint(["org_id", "media_visual_asset_set_version_id"], ["media_visual_asset_set_versions.org_id", "media_visual_asset_set_versions.id"], name="fk_media_render_jobs_visual"),
        sa.ForeignKeyConstraint(["org_id", "media_output_spec_version_id"], ["media_output_spec_versions.org_id", "media_output_spec_versions.id"], name="fk_media_render_jobs_output"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_render_jobs_duration"),
        sa.CheckConstraint("status IN ('planned', 'running', 'succeeded', 'failed', 'retry_scheduled', 'unknown', 'dead_letter')", name="ck_media_render_jobs_status"),
        sa.CheckConstraint("attempt_count >= 0 AND artifact_count >= 0", name="ck_media_render_jobs_counts"),
        sa.CheckConstraint("length(input_hash) = 64", name="ck_media_render_jobs_hash"),
    )
    op.create_table(
        "media_render_job_inputs",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False), sa.Column("input_kind", sa.String(32), nullable=False),
        sa.Column("input_version_id", sa.String(36), nullable=False), sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("expected_version_no", sa.Integer, nullable=True), sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "render_job_id", "sequence"),
        sa.UniqueConstraint("org_id", "render_job_id", "input_kind", name="uq_media_render_job_inputs_kind"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_job_inputs_job"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_render_job_inputs_sequence"),
        sa.CheckConstraint("expected_version_no IS NULL OR expected_version_no >= 1", name="ck_media_render_job_inputs_version_no"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_media_render_job_inputs_hash"),
    )
    op.create_table(
        "media_render_artifacts",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("render_job_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False), sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("shot_sequence", sa.Integer, nullable=True), sa.Column("output_profile_key", sa.String(64), nullable=False),
        sa.Column("storage_object_ref", sa.String(512), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False), sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "render_job_id", "sequence"),
        sa.UniqueConstraint("org_id", "render_job_id", "stage", "shot_sequence", "output_profile_key", name="uq_media_render_artifacts_natural"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_artifacts_job"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_render_artifacts_sequence"),
        sa.CheckConstraint("shot_sequence IS NULL OR shot_sequence >= 1", name="ck_media_render_artifacts_shot"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_media_render_artifacts_size"),
        sa.CheckConstraint("length(content_hash) = 64 AND length(input_hash) = 64", name="ck_media_render_artifacts_hash"),
        sa.CheckConstraint("storage_object_ref LIKE 'private://%'", name="ck_media_render_artifacts_private_ref"),
    )
    op.create_table(
        "media_render_commands",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("render_job_id", sa.String(36), nullable=False), sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False), sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "render_job_id"], ["media_render_jobs.org_id", "media_render_jobs.id"], name="fk_media_render_commands_job"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_render_commands_hash"),
    )
    op.create_index("ix_media_render_jobs_script", "media_render_jobs", ["org_id", "media_script_version_id"])
    op.create_index("ix_media_render_jobs_status", "media_render_jobs", ["org_id", "status", "created_at"])
    op.create_index("ix_media_render_job_inputs_job", "media_render_job_inputs", ["org_id", "render_job_id", "sequence"])
    op.create_index("ix_media_render_artifacts_job", "media_render_artifacts", ["org_id", "render_job_id", "sequence"])
    op.create_index("ix_media_render_commands_job", "media_render_commands", ["org_id", "render_job_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for name in (
            "media_render_commands_validate", "media_render_artifacts_validate", "media_render_job_inputs_validate",
            "media_render_jobs_status_guard", "media_render_jobs_identity_guard", "media_render_jobs_validate",
            "media_render_artifacts_no_replace",
            "media_render_commands_no_delete", "media_render_commands_no_update", "media_render_artifacts_no_delete",
            "media_render_artifacts_no_update", "media_render_job_inputs_no_delete", "media_render_job_inputs_no_update",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for table, trigger in (
            ("media_render_jobs", "media_render_jobs_validate"), ("media_render_jobs", "media_render_jobs_identity_guard"),
            ("media_render_artifacts", "media_render_artifacts_guard"), ("media_render_commands", "media_render_commands_guard"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for name in ("media_render_jobs_validate", "media_render_jobs_identity_guard", "media_render_job_append_only_guard", "media_render_artifacts_guard", "media_render_commands_guard"):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_render_commands_job", "media_render_commands"), ("ix_media_render_artifacts_job", "media_render_artifacts"),
        ("ix_media_render_job_inputs_job", "media_render_job_inputs"), ("ix_media_render_jobs_status", "media_render_jobs"),
        ("ix_media_render_jobs_script", "media_render_jobs"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_render_commands")
    op.drop_table("media_render_artifacts")
    op.drop_table("media_render_job_inputs")
    op.drop_table("media_render_jobs")
