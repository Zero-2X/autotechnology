"""MEDIA-003A subtitle roots, immutable language tracks and cue projections."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_003a"
down_revision = "20260920_media_002"
branch_labels = None
depends_on = None


_APPEND_ONLY = (
    "media_subtitle_versions",
    "media_subtitle_tracks",
    "media_subtitle_cues",
    "media_subtitle_commands",
)


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_subtitle_versions_no_replace BEFORE INSERT ON media_subtitle_versions "
        "WHEN EXISTS (SELECT 1 FROM media_subtitle_versions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_tracks_no_replace BEFORE INSERT ON media_subtitle_tracks "
        "WHEN EXISTS (SELECT 1 FROM media_subtitle_tracks WHERE org_id = NEW.org_id "
        "AND subtitle_version_id = NEW.subtitle_version_id AND locale = NEW.locale) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle tracks is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_cues_no_replace BEFORE INSERT ON media_subtitle_cues "
        "WHEN EXISTS (SELECT 1 FROM media_subtitle_cues WHERE org_id = NEW.org_id "
        "AND subtitle_version_id = NEW.subtitle_version_id AND locale = NEW.locale AND sequence = NEW.sequence) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle cues is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_commands_no_replace BEFORE INSERT ON media_subtitle_commands "
        "WHEN EXISTS (SELECT 1 FROM media_subtitle_commands WHERE org_id = NEW.org_id "
        "AND namespace = NEW.namespace AND idempotency_key = NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle commands is append-only'); END"
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
        "CREATE TRIGGER media_subtitles_natural_guard BEFORE INSERT ON media_subtitles "
        "WHEN EXISTS (SELECT 1 FROM media_subtitles prior WHERE prior.org_id = NEW.org_id "
        "AND prior.media_script_version_id = NEW.media_script_version_id "
        "AND ((prior.media_storyboard_version_id IS NULL AND NEW.media_storyboard_version_id IS NULL) "
        "OR prior.media_storyboard_version_id = NEW.media_storyboard_version_id)) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle root already exists'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitles_identity_guard BEFORE UPDATE ON media_subtitles "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.media_script_version_id != OLD.media_script_version_id "
        "OR COALESCE(NEW.media_storyboard_version_id, '') != COALESCE(OLD.media_storyboard_version_id, '') "
        "OR NEW.duration_seconds != OLD.duration_seconds "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitles_current_version_guard BEFORE INSERT ON media_subtitles "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_subtitle_versions v "
        "WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id AND v.subtitle_id = NEW.id "
        "AND v.media_script_version_id = NEW.media_script_version_id AND v.duration_seconds = NEW.duration_seconds) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitles_current_version_guard_update BEFORE UPDATE ON media_subtitles "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_subtitle_versions v "
        "WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id AND v.subtitle_id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_versions_validate BEFORE INSERT ON media_subtitle_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM media_subtitles s WHERE s.id = NEW.subtitle_id AND s.org_id = NEW.org_id "
        "AND s.media_script_version_id = NEW.media_script_version_id "
        "AND COALESCE(s.media_storyboard_version_id, '') = COALESCE(NEW.media_storyboard_version_id, '') "
        "AND s.duration_seconds = NEW.duration_seconds) "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions script WHERE script.id = NEW.media_script_version_id "
        "AND script.org_id = NEW.org_id AND script.duration_seconds = NEW.duration_seconds "
        "AND script.status NOT IN ('withdrawn', 'superseded') AND script.snapshot_hash = NEW.source_script_snapshot_hash) "
        "OR json_valid(NEW.tracks_json) = 0 OR json_type(NEW.tracks_json) != 'array' OR json_array_length(NEW.tracks_json) < 1 "
        "OR json_valid(NEW.accessibility_json) = 0 OR json_type(NEW.accessibility_json) != 'object' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"model\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"credential\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"token\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"secret\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"password\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"authorization\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.tracks_json || NEW.accessibility_json) LIKE '%\"raw_output\"%' "
        "OR (NEW.version_no = 1 AND NEW.supersedes_version_id IS NOT NULL) "
        "OR (NEW.version_no > 1 AND (NEW.supersedes_version_id IS NULL OR NOT EXISTS ("
        "SELECT 1 FROM media_subtitle_versions prior WHERE prior.org_id = NEW.org_id "
        "AND prior.subtitle_id = NEW.subtitle_id AND prior.id = NEW.supersedes_version_id "
        "AND prior.version_no = NEW.version_no - 1))) "
        "OR length(NEW.source_script_snapshot_hash) != 64 OR NEW.source_script_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR (NEW.source_storyboard_snapshot_hash IS NOT NULL AND (length(NEW.source_storyboard_snapshot_hash) != 64 "
        "OR NEW.source_storyboard_snapshot_hash GLOB '*[^0-9A-Fa-f]*')) "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle version validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_tracks_validate BEFORE INSERT ON media_subtitle_tracks "
        "WHEN NOT EXISTS (SELECT 1 FROM media_subtitle_versions WHERE id = NEW.subtitle_version_id AND org_id = NEW.org_id) "
        "OR NEW.kind NOT IN ('caption', 'subtitle') OR NEW.direction NOT IN ('ltr', 'rtl') OR NEW.text_version < 1 "
        "OR NEW.cue_count < 1 OR json_valid(NEW.cues_json) = 0 OR json_type(NEW.cues_json) != 'array' "
        "OR json_array_length(NEW.cues_json) < 1 OR json_valid(NEW.accessibility_json) = 0 "
        "OR json_type(NEW.accessibility_json) != 'object' OR length(NEW.source_text_hash) != 64 "
        "OR NEW.source_text_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR lower(NEW.cues_json || NEW.accessibility_json) LIKE '%\"model\"%' "
        "OR lower(NEW.cues_json || NEW.accessibility_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.cues_json || NEW.accessibility_json) LIKE '%\"token\"%' "
        "OR lower(NEW.cues_json || NEW.accessibility_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle track validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_cues_validate BEFORE INSERT ON media_subtitle_cues "
        "WHEN NOT EXISTS (SELECT 1 FROM media_subtitle_tracks WHERE org_id = NEW.org_id "
        "AND subtitle_version_id = NEW.subtitle_version_id AND locale = NEW.locale) "
        "OR NEW.sequence < 1 OR NEW.source_segment_sequence NOT IN (1, 2, 3) "
        "OR NEW.end_ms <= NEW.start_ms OR NEW.end_ms - NEW.start_ms < 250 "
        "OR NOT EXISTS (SELECT 1 FROM media_subtitle_versions v JOIN media_script_versions script "
        "ON script.id = v.media_script_version_id AND script.org_id = v.org_id JOIN json_each(script.segments_json) segment "
        "WHERE v.id = NEW.subtitle_version_id AND v.org_id = NEW.org_id "
        "AND CAST(json_extract(segment.value, '$.sequence') AS INTEGER) = NEW.source_segment_sequence "
        "AND NEW.start_ms >= CAST(json_extract(segment.value, '$.start_ms') AS INTEGER) "
        "AND NEW.end_ms <= CAST(json_extract(segment.value, '$.end_ms') AS INTEGER)) "
        "OR (NEW.speaker_label IS NOT NULL AND length(NEW.speaker_label) > 120) "
        "OR (NEW.sound_description IS NOT NULL AND length(NEW.sound_description) > 240) "
        "OR NEW.line < 0 OR NEW.line > 100 OR NEW.position < 0 OR NEW.position > 100 "
        "OR NEW.align NOT IN ('start', 'center', 'end') "
        "OR lower(NEW.text || COALESCE(NEW.speaker_label, '') || COALESCE(NEW.sound_description, '')) LIKE '%\"model\"%' "
        "OR lower(NEW.text || COALESCE(NEW.speaker_label, '') || COALESCE(NEW.sound_description, '')) LIKE '%\"provider\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle cue validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_commands_validate BEFORE INSERT ON media_subtitle_commands "
        "WHEN NOT EXISTS (SELECT 1 FROM media_subtitles WHERE id = NEW.subtitle_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_subtitle_versions WHERE id = NEW.result_version_id AND org_id = NEW.org_id AND subtitle_id = NEW.subtitle_id) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "OR lower(NEW.response_json) LIKE '%\"authorization\"%' OR lower(NEW.response_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media subtitle command validation failed'); END"
    )


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_subtitle_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION media_subtitle_append_only_guard()"
        )
    op.execute(
        "CREATE FUNCTION media_subtitles_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.media_script_version_id <> OLD.media_script_version_id "
        "OR COALESCE(NEW.media_storyboard_version_id, '') <> COALESCE(OLD.media_storyboard_version_id, '') "
        "OR NEW.duration_seconds <> OLD.duration_seconds THEN RAISE EXCEPTION 'media subtitle identity is immutable'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_subtitles_identity_guard BEFORE UPDATE ON media_subtitles "
        "FOR EACH ROW EXECUTE FUNCTION media_subtitles_identity_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_subtitle_versions_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_subtitles s WHERE s.id = NEW.subtitle_id AND s.org_id = NEW.org_id "
        "AND s.media_script_version_id = NEW.media_script_version_id AND s.duration_seconds = NEW.duration_seconds "
        "AND COALESCE(s.media_storyboard_version_id, '') = COALESCE(NEW.media_storyboard_version_id, '')) "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions script WHERE script.id = NEW.media_script_version_id "
        "AND script.org_id = NEW.org_id AND script.duration_seconds = NEW.duration_seconds "
        "AND script.status NOT IN ('withdrawn','superseded') AND script.snapshot_hash = NEW.source_script_snapshot_hash) "
        "OR jsonb_typeof(NEW.tracks_json::jsonb) <> 'array' OR jsonb_typeof(NEW.accessibility_json::jsonb) <> 'object' "
        "OR NEW.source_script_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$' "
        "THEN RAISE EXCEPTION 'media subtitle version validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_versions_guard BEFORE INSERT ON media_subtitle_versions "
        "FOR EACH ROW EXECUTE FUNCTION media_subtitle_versions_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_subtitle_cues_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_subtitle_tracks WHERE org_id = NEW.org_id AND subtitle_version_id = NEW.subtitle_version_id AND locale = NEW.locale) "
        "OR NEW.end_ms <= NEW.start_ms OR NEW.end_ms - NEW.start_ms < 250 "
        "OR NEW.align NOT IN ('start','center','end') THEN RAISE EXCEPTION 'media subtitle cue validation failed'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_cues_guard BEFORE INSERT ON media_subtitle_cues "
        "FOR EACH ROW EXECUTE FUNCTION media_subtitle_cues_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_subtitle_commands_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_subtitles WHERE id = NEW.subtitle_id AND org_id = NEW.org_id) "
        "OR NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL "
        "OR lower(NEW.response_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "THEN RAISE EXCEPTION 'media subtitle command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_subtitle_commands_guard BEFORE INSERT ON media_subtitle_commands "
        "FOR EACH ROW EXECUTE FUNCTION media_subtitle_commands_guard()"
    )


def upgrade() -> None:
    op.create_table(
        "media_subtitles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("media_script_version_id", sa.String(36), nullable=False),
        sa.Column("media_storyboard_version_id", sa.String(36), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_subtitles_org_id"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_subtitles_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_subtitles_storyboard"),
        sa.UniqueConstraint("org_id", "media_script_version_id", "media_storyboard_version_id", name="uq_media_subtitles_source"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_subtitles_duration"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'withdrawn')", name="ck_media_subtitles_status"),
    )
    op.create_table(
        "media_subtitle_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("subtitle_id", sa.String(36), nullable=False),
        sa.Column("media_script_version_id", sa.String(36), nullable=False),
        sa.Column("media_storyboard_version_id", sa.String(36), nullable=True),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("policy_snapshot_id", sa.String(36), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("tracks_json", sa.Text, nullable=False),
        sa.Column("track_count", sa.Integer, nullable=False),
        sa.Column("accessibility_json", sa.Text, nullable=False),
        sa.Column("revision_reason", sa.String(1000), nullable=True),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("source_script_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("source_storyboard_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_subtitle_versions_org_id"),
        sa.UniqueConstraint("org_id", "subtitle_id", "version_no", name="uq_media_subtitle_versions_no"),
        sa.ForeignKeyConstraint(["org_id", "subtitle_id"], ["media_subtitles.org_id", "media_subtitles.id"], name="fk_media_subtitle_versions_subtitle"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_subtitle_versions_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_subtitle_versions_storyboard"),
        sa.ForeignKeyConstraint(["org_id", "supersedes_version_id"], ["media_subtitle_versions.org_id", "media_subtitle_versions.id"], name="fk_media_subtitle_versions_supersedes"),
        sa.CheckConstraint("version_no >= 1", name="ck_media_subtitle_versions_no"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_subtitle_versions_duration"),
        sa.CheckConstraint("template_version = 'media-subtitle-v1'", name="ck_media_subtitle_versions_template"),
        sa.CheckConstraint("status IN ('draft', 'edited', 'in_review', 'approved', 'superseded', 'withdrawn')", name="ck_media_subtitle_versions_status"),
        sa.CheckConstraint("track_count >= 1", name="ck_media_subtitle_versions_track_count"),
        sa.CheckConstraint("length(source_script_snapshot_hash) = 64", name="ck_media_subtitle_versions_source_hash"),
        sa.CheckConstraint("source_storyboard_snapshot_hash IS NULL OR length(source_storyboard_snapshot_hash) = 64", name="ck_media_subtitle_versions_story_hash"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_media_subtitle_versions_hash"),
    )
    op.create_table(
        "media_subtitle_tracks",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("subtitle_version_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("language_name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False),
        sa.Column("text_version", sa.Integer, nullable=False),
        sa.Column("source_text_hash", sa.String(64), nullable=False),
        sa.Column("cues_json", sa.Text, nullable=False),
        sa.Column("cue_count", sa.Integer, nullable=False),
        sa.Column("accessibility_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "subtitle_version_id", "locale"),
        sa.ForeignKeyConstraint(["org_id", "subtitle_version_id"], ["media_subtitle_versions.org_id", "media_subtitle_versions.id"], name="fk_media_subtitle_tracks_version"),
        sa.CheckConstraint("kind IN ('caption', 'subtitle')", name="ck_media_subtitle_tracks_kind"),
        sa.CheckConstraint("direction IN ('ltr', 'rtl')", name="ck_media_subtitle_tracks_direction"),
        sa.CheckConstraint("text_version >= 1", name="ck_media_subtitle_tracks_text_version"),
        sa.CheckConstraint("cue_count >= 1", name="ck_media_subtitle_tracks_cue_count"),
        sa.CheckConstraint("length(source_text_hash) = 64", name="ck_media_subtitle_tracks_hash"),
    )
    op.create_table(
        "media_subtitle_cues",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("subtitle_version_id", sa.String(36), nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("source_segment_sequence", sa.Integer, nullable=False),
        sa.Column("start_ms", sa.Integer, nullable=False),
        sa.Column("end_ms", sa.Integer, nullable=False),
        sa.Column("text", sa.String(500), nullable=False),
        sa.Column("speaker_label", sa.String(120), nullable=True),
        sa.Column("sound_description", sa.String(240), nullable=True),
        sa.Column("is_forced", sa.Boolean, nullable=False),
        sa.Column("line", sa.Integer, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("align", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "subtitle_version_id", "locale", "sequence"),
        sa.ForeignKeyConstraint(["org_id", "subtitle_version_id", "locale"], ["media_subtitle_tracks.org_id", "media_subtitle_tracks.subtitle_version_id", "media_subtitle_tracks.locale"], name="fk_media_subtitle_cues_track"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_subtitle_cues_sequence"),
        sa.CheckConstraint("source_segment_sequence IN (1, 2, 3)", name="ck_media_subtitle_cues_segment"),
        sa.CheckConstraint("end_ms > start_ms AND end_ms - start_ms >= 250", name="ck_media_subtitle_cues_timing"),
        sa.CheckConstraint("line >= 0 AND line <= 100 AND position >= 0 AND position <= 100", name="ck_media_subtitle_cues_position"),
        sa.CheckConstraint("align IN ('start', 'center', 'end')", name="ck_media_subtitle_cues_align"),
    )
    op.create_table(
        "media_subtitle_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("subtitle_id", sa.String(36), nullable=False),
        sa.Column("result_version_id", sa.String(36), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "subtitle_id"], ["media_subtitles.org_id", "media_subtitles.id"], name="fk_media_subtitle_commands_subtitle"),
        sa.ForeignKeyConstraint(["org_id", "result_version_id"], ["media_subtitle_versions.org_id", "media_subtitle_versions.id"], name="fk_media_subtitle_commands_version"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_subtitle_commands_hash"),
    )
    op.create_index("ix_media_subtitles_script", "media_subtitles", ["org_id", "media_script_version_id"])
    op.create_index("ix_media_subtitle_versions_subtitle", "media_subtitle_versions", ["org_id", "subtitle_id", "version_no"])
    op.create_index("ix_media_subtitle_tracks_locale", "media_subtitle_tracks", ["org_id", "locale", "subtitle_version_id"])
    op.create_index("ix_media_subtitle_cues_version", "media_subtitle_cues", ["org_id", "subtitle_version_id", "locale", "sequence"])
    op.create_index("ix_media_subtitle_commands_subtitle", "media_subtitle_commands", ["org_id", "subtitle_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            "media_subtitle_commands_validate", "media_subtitle_cues_validate", "media_subtitle_tracks_validate",
            "media_subtitle_versions_validate", "media_subtitles_current_version_guard_update",
            "media_subtitles_current_version_guard", "media_subtitles_identity_guard", "media_subtitles_natural_guard",
            "media_subtitle_commands_no_delete", "media_subtitle_commands_no_update", "media_subtitle_cues_no_delete",
            "media_subtitle_cues_no_update", "media_subtitle_tracks_no_delete", "media_subtitle_tracks_no_update",
            "media_subtitle_versions_no_delete", "media_subtitle_versions_no_update", "media_subtitle_versions_no_replace",
            "media_subtitle_tracks_no_replace", "media_subtitle_cues_no_replace", "media_subtitle_commands_no_replace",
        ]
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for name in (
            "media_subtitle_commands_guard", "media_subtitle_cues_guard", "media_subtitle_versions_guard",
            "media_subtitles_identity_guard", "media_subtitle_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_subtitle_commands_subtitle", "media_subtitle_commands"),
        ("ix_media_subtitle_cues_version", "media_subtitle_cues"),
        ("ix_media_subtitle_tracks_locale", "media_subtitle_tracks"),
        ("ix_media_subtitle_versions_subtitle", "media_subtitle_versions"),
        ("ix_media_subtitles_script", "media_subtitles"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_subtitle_commands")
    op.drop_table("media_subtitle_cues")
    op.drop_table("media_subtitle_tracks")
    op.drop_table("media_subtitle_versions")
    op.drop_table("media_subtitles")
