"""MEDIA-002 storyboard roots, immutable shot projections and rights-bound refs."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_002"
down_revision = "20260920_media_001"
branch_labels = None
depends_on = None


_APPEND_ONLY = (
    "media_storyboard_versions",
    "media_storyboard_shots",
    "media_storyboard_asset_refs",
    "media_storyboard_commands",
)


def _sqlite_guards() -> None:
    # A version, shot, reference, or command is an append-only fact.  The
    # explicit insert guards make a replayed identity fail even on SQLite
    # configurations that do not enable all uniqueness checks in adapters.
    op.execute(
        "CREATE TRIGGER media_storyboard_versions_no_replace BEFORE INSERT ON media_storyboard_versions "
        "WHEN EXISTS (SELECT 1 FROM media_storyboard_versions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_shots_no_replace BEFORE INSERT ON media_storyboard_shots "
        "WHEN EXISTS (SELECT 1 FROM media_storyboard_shots WHERE org_id = NEW.org_id "
        "AND storyboard_version_id = NEW.storyboard_version_id AND sequence = NEW.sequence) "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard shots is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_asset_refs_no_replace BEFORE INSERT ON media_storyboard_asset_refs "
        "WHEN EXISTS (SELECT 1 FROM media_storyboard_asset_refs WHERE org_id = NEW.org_id "
        "AND storyboard_version_id = NEW.storyboard_version_id AND shot_sequence = NEW.shot_sequence "
        "AND role = NEW.role AND asset_version_id = NEW.asset_version_id) "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard asset refs is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_commands_no_replace BEFORE INSERT ON media_storyboard_commands "
        "WHEN EXISTS (SELECT 1 FROM media_storyboard_commands WHERE org_id = NEW.org_id "
        "AND namespace = NEW.namespace AND idempotency_key = NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard commands is append-only'); END"
    )
    for table in _APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )
    op.execute(
        "CREATE TRIGGER media_storyboards_identity_guard BEFORE UPDATE ON media_storyboards "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id "
        "OR NEW.media_script_version_id != OLD.media_script_version_id "
        "OR NEW.duration_seconds != OLD.duration_seconds "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboards_current_version_guard BEFORE INSERT ON media_storyboards "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM media_storyboard_versions WHERE id = NEW.current_version_id "
        "AND org_id = NEW.org_id AND storyboard_id = NEW.id "
        "AND media_script_version_id = NEW.media_script_version_id AND duration_seconds = NEW.duration_seconds) "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboards_current_version_guard_update BEFORE UPDATE ON media_storyboards "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM media_storyboard_versions WHERE id = NEW.current_version_id "
        "AND org_id = NEW.org_id AND storyboard_id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_versions_validate BEFORE INSERT ON media_storyboard_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM media_storyboards WHERE id = NEW.storyboard_id AND org_id = NEW.org_id "
        "AND media_script_version_id = NEW.media_script_version_id AND duration_seconds = NEW.duration_seconds) "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions WHERE id = NEW.media_script_version_id "
        "AND org_id = NEW.org_id AND duration_seconds = NEW.duration_seconds "
        "AND status NOT IN ('withdrawn', 'superseded') AND snapshot_hash = NEW.source_script_snapshot_hash) "
        "OR (NEW.version_no = 1 AND NEW.supersedes_version_id IS NOT NULL) "
        "OR (NEW.version_no > 1 AND (NEW.supersedes_version_id IS NULL OR NOT EXISTS ("
        "SELECT 1 FROM media_storyboard_versions predecessor WHERE predecessor.org_id = NEW.org_id "
        "AND predecessor.storyboard_id = NEW.storyboard_id AND predecessor.id = NEW.supersedes_version_id "
        "AND predecessor.version_no = NEW.version_no - 1))) "
        "OR json_valid(NEW.shots_json) = 0 OR json_type(NEW.shots_json) != 'array' "
        "OR json_array_length(NEW.shots_json) < 1 "
        "OR json_valid(NEW.rights_snapshot_ids_json) = 0 OR json_type(NEW.rights_snapshot_ids_json) != 'array' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"model\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"credential\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"token\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"secret\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"password\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"authorization\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.shots_json || NEW.rights_snapshot_ids_json) LIKE '%\"raw_output\"%' "
        "OR length(NEW.source_script_snapshot_hash) != 64 OR NEW.source_script_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard version validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_shots_validate BEFORE INSERT ON media_storyboard_shots "
        "WHEN NOT EXISTS (SELECT 1 FROM media_storyboard_versions WHERE id = NEW.storyboard_version_id AND org_id = NEW.org_id) "
        "OR NEW.sequence < 1 OR NEW.script_segment_sequence NOT IN (1, 2, 3) "
        "OR NEW.end_ms <= NEW.start_ms OR NEW.end_ms - NEW.start_ms < 500 "
        "OR NOT EXISTS (SELECT 1 FROM media_storyboard_versions v "
        "JOIN media_script_versions script ON script.id = v.media_script_version_id AND script.org_id = v.org_id "
        "JOIN json_each(script.segments_json) segment "
        "WHERE v.id = NEW.storyboard_version_id AND v.org_id = NEW.org_id "
        "AND CAST(json_extract(segment.value, '$.sequence') AS INTEGER) = NEW.script_segment_sequence "
        "AND NEW.start_ms >= CAST(json_extract(segment.value, '$.start_ms') AS INTEGER) "
        "AND NEW.end_ms <= CAST(json_extract(segment.value, '$.end_ms') AS INTEGER)) "
        "OR json_valid(NEW.asset_refs_json) = 0 OR json_type(NEW.asset_refs_json) != 'array' "
        "OR lower(NEW.asset_refs_json) LIKE '%\"model\"%' "
        "OR lower(NEW.asset_refs_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.asset_refs_json) LIKE '%\"token\"%' "
        "OR lower(NEW.asset_refs_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard shot validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_asset_refs_validate BEFORE INSERT ON media_storyboard_asset_refs "
        "WHEN NOT EXISTS (SELECT 1 FROM media_storyboard_shots WHERE org_id = NEW.org_id "
        "AND storyboard_version_id = NEW.storyboard_version_id AND sequence = NEW.shot_sequence) "
        "OR NEW.role NOT IN ('visual', 'music', 'font', 'voiceover') "
        "OR (NEW.role = 'visual' AND NEW.media_type NOT IN ('image', 'video', 'thumbnail')) "
        "OR (NEW.role IN ('music', 'voiceover') AND NEW.media_type != 'audio') "
        "OR (NEW.role = 'font' AND NEW.media_type != 'document') "
        "OR json_valid(NEW.rights_record_version_ids_json) = 0 OR json_type(NEW.rights_record_version_ids_json) != 'array' "
        "OR json_valid(NEW.rights_snapshots_json) = 0 OR json_type(NEW.rights_snapshots_json) != 'array' "
        "OR json_array_length(NEW.rights_record_version_ids_json) < 1 "
        "OR json_array_length(NEW.rights_snapshots_json) < 1 "
        "OR EXISTS (SELECT 1 FROM json_each(NEW.rights_record_version_ids_json) AS ref "
        "WHERE NOT EXISTS (SELECT 1 FROM rights_record_versions r WHERE r.org_id = NEW.org_id "
        "AND r.id = ref.value AND r.status = 'verified' AND r.permitted_use IN ('derivative', 'commercial') "
        "AND (r.valid_from IS NULL OR r.valid_from <= (SELECT created_at FROM media_storyboard_versions WHERE id = NEW.storyboard_version_id)) "
        "AND (r.valid_to IS NULL OR (SELECT created_at FROM media_storyboard_versions WHERE id = NEW.storyboard_version_id) < r.valid_to))) "
        "OR (NEW.storage_object_ref IS NOT NULL AND NEW.storage_object_ref NOT LIKE 'private://%') "
        "OR length(NEW.asset_snapshot_hash) != 64 OR NEW.asset_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard asset reference validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_commands_validate BEFORE INSERT ON media_storyboard_commands "
        "WHEN NOT EXISTS (SELECT 1 FROM media_storyboards WHERE id = NEW.storyboard_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_storyboard_versions WHERE id = NEW.result_version_id AND org_id = NEW.org_id "
        "AND storyboard_id = NEW.storyboard_id) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "OR lower(NEW.response_json) LIKE '%\"authorization\"%' OR lower(NEW.response_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media storyboard command validation failed'); END"
    )


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_storyboard_append_only_guard() RETURNS trigger AS $$ "
        "BEGIN IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN "
        "RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION media_storyboard_append_only_guard()"
        )
    op.execute(
        "CREATE FUNCTION media_storyboards_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.media_script_version_id <> OLD.media_script_version_id "
        "OR NEW.duration_seconds <> OLD.duration_seconds THEN RAISE EXCEPTION 'media storyboard identity is immutable'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_storyboards_identity_guard BEFORE UPDATE ON media_storyboards "
        "FOR EACH ROW EXECUTE FUNCTION media_storyboards_identity_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_storyboard_versions_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_storyboards s WHERE s.id = NEW.storyboard_id AND s.org_id = NEW.org_id "
        "AND s.media_script_version_id = NEW.media_script_version_id AND s.duration_seconds = NEW.duration_seconds) "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions v WHERE v.id = NEW.media_script_version_id AND v.org_id = NEW.org_id "
        "AND v.duration_seconds = NEW.duration_seconds AND v.status NOT IN ('withdrawn','superseded') "
        "AND v.snapshot_hash = NEW.source_script_snapshot_hash) THEN RAISE EXCEPTION 'media storyboard version validation failed'; END IF; "
        "IF jsonb_typeof(NEW.shots_json::jsonb) <> 'array' OR jsonb_typeof(NEW.rights_snapshot_ids_json::jsonb) <> 'array' "
        "OR NEW.source_script_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$' THEN "
        "RAISE EXCEPTION 'media storyboard version projection invalid'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_versions_guard BEFORE INSERT ON media_storyboard_versions "
        "FOR EACH ROW EXECUTE FUNCTION media_storyboard_versions_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_storyboard_asset_refs_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_storyboard_shots s WHERE s.org_id = NEW.org_id "
        "AND s.storyboard_version_id = NEW.storyboard_version_id AND s.sequence = NEW.shot_sequence) "
        "OR jsonb_array_length(NEW.rights_record_version_ids_json::jsonb) < 1 "
        "OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(NEW.rights_record_version_ids_json::jsonb) ref "
        "WHERE NOT EXISTS (SELECT 1 FROM rights_record_versions r WHERE r.org_id = NEW.org_id AND r.id = ref "
        "AND r.status = 'verified')) THEN RAISE EXCEPTION 'media storyboard rights reference invalid'; END IF; "
        "IF NEW.asset_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' THEN RAISE EXCEPTION 'media storyboard asset hash invalid'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_asset_refs_guard BEFORE INSERT ON media_storyboard_asset_refs "
        "FOR EACH ROW EXECUTE FUNCTION media_storyboard_asset_refs_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_storyboard_commands_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL "
        "OR lower(NEW.response_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "THEN RAISE EXCEPTION 'media storyboard command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_storyboard_commands_guard BEFORE INSERT ON media_storyboard_commands "
        "FOR EACH ROW EXECUTE FUNCTION media_storyboard_commands_guard()"
    )


def upgrade() -> None:
    op.create_table(
        "media_storyboards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("media_script_version_id", sa.String(36), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_storyboards_org_id"),
        sa.UniqueConstraint("org_id", "media_script_version_id", name="uq_media_storyboards_script"),
        sa.ForeignKeyConstraint(
            ["org_id", "media_script_version_id"],
            ["media_script_versions.org_id", "media_script_versions.id"],
            name="fk_media_storyboards_script",
        ),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_storyboards_duration"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'withdrawn')", name="ck_media_storyboards_status"),
    )
    op.create_table(
        "media_storyboard_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("storyboard_id", sa.String(36), nullable=False),
        sa.Column("media_script_version_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("locale", sa.String(64), nullable=False),
        sa.Column("market", sa.String(64), nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False),
        sa.Column("policy_snapshot_id", sa.String(36), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("shots_json", sa.Text, nullable=False),
        sa.Column("asset_reference_count", sa.Integer, nullable=False),
        sa.Column("rights_snapshot_ids_json", sa.Text, nullable=False),
        sa.Column("revision_reason", sa.String(1000), nullable=True),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("source_script_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_storyboard_versions_org_id"),
        sa.UniqueConstraint("org_id", "storyboard_id", "version_no", name="uq_media_storyboard_versions_no"),
        sa.ForeignKeyConstraint(
            ["org_id", "storyboard_id"],
            ["media_storyboards.org_id", "media_storyboards.id"],
            name="fk_media_storyboard_versions_storyboard",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "media_script_version_id"],
            ["media_script_versions.org_id", "media_script_versions.id"],
            name="fk_media_storyboard_versions_script",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "supersedes_version_id"],
            ["media_storyboard_versions.org_id", "media_storyboard_versions.id"],
            name="fk_media_storyboard_versions_supersedes",
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_media_storyboard_versions_no"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_storyboard_versions_duration"),
        sa.CheckConstraint("template_version = 'media-storyboard-v1'", name="ck_media_storyboard_versions_template"),
        sa.CheckConstraint(
            "status IN ('draft', 'edited', 'in_review', 'approved', 'superseded', 'withdrawn')",
            name="ck_media_storyboard_versions_status",
        ),
        sa.CheckConstraint("asset_reference_count >= 0", name="ck_media_storyboard_versions_asset_count"),
        sa.CheckConstraint("length(source_script_snapshot_hash) = 64", name="ck_media_storyboard_versions_source_hash"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_media_storyboard_versions_hash"),
    )
    op.create_table(
        "media_storyboard_shots",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("storyboard_version_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("script_segment_sequence", sa.Integer, nullable=False),
        sa.Column("start_ms", sa.Integer, nullable=False),
        sa.Column("end_ms", sa.Integer, nullable=False),
        sa.Column("purpose", sa.String(512), nullable=False),
        sa.Column("transition", sa.String(16), nullable=False),
        sa.Column("asset_refs_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "storyboard_version_id", "sequence"),
        sa.ForeignKeyConstraint(
            ["org_id", "storyboard_version_id"],
            ["media_storyboard_versions.org_id", "media_storyboard_versions.id"],
            name="fk_media_storyboard_shots_version",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_media_storyboard_shots_sequence"),
        sa.CheckConstraint("script_segment_sequence IN (1, 2, 3)", name="ck_media_storyboard_shots_segment"),
        sa.CheckConstraint("end_ms > start_ms AND end_ms - start_ms >= 500", name="ck_media_storyboard_shots_timing"),
        sa.CheckConstraint("transition IN ('cut', 'fade', 'dissolve', 'none')", name="ck_media_storyboard_shots_transition"),
    )
    op.create_table(
        "media_storyboard_asset_refs",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("storyboard_version_id", sa.String(36), nullable=False),
        sa.Column("shot_sequence", sa.Integer, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("format", sa.String(64), nullable=False),
        sa.Column("storage_object_ref", sa.String(512), nullable=True),
        sa.Column("asset_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("rights_record_version_ids_json", sa.Text, nullable=False),
        sa.Column("rights_snapshots_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "storyboard_version_id", "shot_sequence", "role", "asset_version_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "storyboard_version_id", "shot_sequence"],
            ["media_storyboard_shots.org_id", "media_storyboard_shots.storyboard_version_id", "media_storyboard_shots.sequence"],
            name="fk_media_storyboard_asset_refs_shot",
        ),
        sa.CheckConstraint("role IN ('visual', 'music', 'font', 'voiceover')", name="ck_media_storyboard_asset_refs_role"),
        sa.CheckConstraint(
            "media_type IN ('image', 'audio', 'video', 'subtitle', 'document', 'thumbnail')",
            name="ck_media_storyboard_asset_refs_media",
        ),
        sa.CheckConstraint("length(asset_snapshot_hash) = 64", name="ck_media_storyboard_asset_refs_hash"),
    )
    op.create_table(
        "media_storyboard_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("storyboard_id", sa.String(36), nullable=False),
        sa.Column("result_version_id", sa.String(36), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(
            ["org_id", "storyboard_id"],
            ["media_storyboards.org_id", "media_storyboards.id"],
            name="fk_media_storyboard_commands_storyboard",
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "result_version_id"],
            ["media_storyboard_versions.org_id", "media_storyboard_versions.id"],
            name="fk_media_storyboard_commands_version",
        ),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_storyboard_commands_hash"),
    )
    op.create_index("ix_media_storyboards_script", "media_storyboards", ["org_id", "media_script_version_id"])
    op.create_index("ix_media_storyboard_versions_storyboard", "media_storyboard_versions", ["org_id", "storyboard_id", "version_no"])
    op.create_index("ix_media_storyboard_shots_version", "media_storyboard_shots", ["org_id", "storyboard_version_id", "sequence"])
    op.create_index("ix_media_storyboard_asset_refs_asset", "media_storyboard_asset_refs", ["org_id", "asset_version_id"])
    op.create_index("ix_media_storyboard_commands_storyboard", "media_storyboard_commands", ["org_id", "storyboard_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            "media_storyboard_commands_validate", "media_storyboard_asset_refs_validate",
            "media_storyboard_shots_validate", "media_storyboard_versions_validate",
            "media_storyboards_current_version_guard_update", "media_storyboards_current_version_guard",
            "media_storyboards_identity_guard", "media_storyboard_commands_no_delete",
            "media_storyboard_commands_no_update", "media_storyboard_asset_refs_no_delete",
            "media_storyboard_asset_refs_no_update", "media_storyboard_shots_no_delete",
            "media_storyboard_shots_no_update", "media_storyboard_versions_no_delete",
            "media_storyboard_versions_no_update", "media_storyboard_versions_no_replace",
            "media_storyboard_shots_no_replace", "media_storyboard_asset_refs_no_replace",
            "media_storyboard_commands_no_replace",
        ]
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for name in (
            "media_storyboard_commands_guard", "media_storyboard_asset_refs_guard",
            "media_storyboard_versions_guard", "media_storyboards_identity_guard",
            "media_storyboard_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_storyboard_commands_storyboard", "media_storyboard_commands"),
        ("ix_media_storyboard_asset_refs_asset", "media_storyboard_asset_refs"),
        ("ix_media_storyboard_shots_version", "media_storyboard_shots"),
        ("ix_media_storyboard_versions_storyboard", "media_storyboard_versions"),
        ("ix_media_storyboards_script", "media_storyboards"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_storyboard_commands")
    op.drop_table("media_storyboard_asset_refs")
    op.drop_table("media_storyboard_shots")
    op.drop_table("media_storyboard_versions")
    op.drop_table("media_storyboards")
