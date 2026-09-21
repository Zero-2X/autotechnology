"""MEDIA-003C immutable output specification profiles and lineage guards."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_003c"
down_revision = "20260920_media_003b"
branch_labels = None
depends_on = None


_APPEND_ONLY = (
    "media_output_spec_versions",
    "media_output_spec_items",
    "media_output_spec_commands",
)


def _profile_json_guard(postgres: bool) -> str:
    """Freeze profile validation in this migration, independent of future schemas."""
    fields = ('sequence', 'profile_key', 'aspect_ratio', 'width', 'height', 'frame_rate',
              'container_format', 'video_codec', 'pixel_format', 'audio_codec',
              'audio_sample_rate_hz', 'audio_channels', 'subtitle_track_ids')
    def value(field):
        raw = f"p.value->>'{field}'" if postgres else f"json_extract(p.value, '$.{field}')"
        if postgres and field in ('sequence', 'width', 'height', 'frame_rate', 'audio_sample_rate_hz', 'audio_channels', 'bitrate_kbps'):
            return f"({raw})::numeric"
        return raw
    def kind(field):
        return f"jsonb_typeof(p.value->'{field}')" if postgres else f"json_type(p.value, '$.{field}')"
    array = "jsonb_array_elements(NEW.profiles_json::jsonb)" if postgres else "json_each(NEW.profiles_json)"
    allowed = ','.join(f"'{field}'" for field in (*fields, 'bitrate_kbps'))
    invalid = [f"{kind(field)} IS NULL" for field in fields]
    for field in ('sequence', 'width', 'height', 'audio_sample_rate_hz', 'audio_channels'):
        invalid.append(f"{kind(field)} <> '{'number' if postgres else 'integer'}'")
        if postgres:
            invalid.append(f"{value(field)} <> trunc({value(field)})")
    invalid += [f"{kind('frame_rate')} <> 'number'" if postgres else f"{kind('frame_rate')} NOT IN ('integer','real')",
                f"{value('frame_rate')} NOT BETWEEN 1 AND 120",
                f"round({value('frame_rate')}, 3) <> {value('frame_rate')}",
                f"{value('sequence')} NOT BETWEEN 1 AND NEW.profile_count",
                f"{kind('subtitle_track_ids')} <> 'array'"]
    for field, choices in {
        'aspect_ratio': "'9:16','1:1','16:9'", 'container_format': "'mp4','mov','webm'",
        'video_codec': "'h264','hevc','av1','vp9'", 'pixel_format': "'yuv420p','yuv422p','yuv444p','rgba'",
        'audio_codec': "'aac','opus','pcm','none'",
    }.items():
        invalid.append(f"{value(field)} NOT IN ({choices})")
    w, h = value('width'), value('height')
    invalid += [f"{w} NOT BETWEEN 2 AND 7680", f"{h} NOT BETWEEN 2 AND 7680", f"{w} % 2 <> 0", f"{h} % 2 <> 0",
                f"NOT (({value('aspect_ratio')} = '9:16' AND {w} * 16 = {h} * 9) OR ({value('aspect_ratio')} = '1:1' AND {w} = {h}) OR ({value('aspect_ratio')} = '16:9' AND {w} * 9 = {h} * 16))",
                f"NOT (({value('audio_codec')} = 'none' AND {value('audio_sample_rate_hz')} = 0 AND {value('audio_channels')} = 0) OR ({value('audio_codec')} <> 'none' AND {value('audio_sample_rate_hz')} IN (44100,48000,96000) AND {value('audio_channels')} BETWEEN 1 AND 8))"]
    keys = "jsonb_object_keys(p.value) AS k(key)" if postgres else "json_each(p.value) k"
    invalid.append(f"EXISTS (SELECT 1 FROM {keys} WHERE k.key NOT IN ({allowed}))")
    invalid.append(f"{kind('profile_key')} <> '{'string' if postgres else 'text'}'")
    invalid.append(f"length({value('profile_key')}) NOT BETWEEN 1 AND 64")
    if postgres:
        invalid.append(f"{value('profile_key')} !~ '^[a-z][a-z0-9._-]{{0,63}}$'")
        tracks = "jsonb_array_elements_text(p.value->'subtitle_track_ids') AS t(value)"
        invalid_uuid = "t.value !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
        invalid.append(f"({kind('bitrate_kbps')} IS NOT NULL AND ({kind('bitrate_kbps')} <> 'number' OR {value('bitrate_kbps')} <> trunc({value('bitrate_kbps')}) OR {value('bitrate_kbps')} NOT BETWEEN 1 AND 1000000))")
    else:
        invalid.append(f"({value('profile_key')} GLOB '*[^a-z0-9._-]*' OR substr({value('profile_key')},1,1) NOT GLOB '[a-z]')")
        tracks = "json_each(json_extract(p.value, '$.subtitle_track_ids')) t"
        invalid_uuid = "t.type <> 'text' OR length(t.value) <> 36 OR substr(t.value,9,1) <> '-' OR substr(t.value,14,1) <> '-' OR substr(t.value,19,1) <> '-' OR substr(t.value,24,1) <> '-' OR length(replace(t.value,'-','')) <> 32 OR replace(t.value,'-','') GLOB '*[^0-9a-fA-F]*'"
        invalid.append(f"({kind('bitrate_kbps')} IS NOT NULL AND ({kind('bitrate_kbps')} <> 'integer' OR {value('bitrate_kbps')} NOT BETWEEN 1 AND 1000000))")
    invalid.append(f"EXISTS (SELECT 1 FROM {tracks} WHERE {invalid_uuid})")
    invalid.append(f"(SELECT COUNT(*) FROM {tracks}) <> (SELECT COUNT(DISTINCT t.value) FROM {tracks})")
    predicate = f"EXISTS (SELECT 1 FROM {array} p WHERE " + ' OR '.join(invalid) + ')'
    for field in ('sequence', 'aspect_ratio', 'profile_key'):
        predicate += f" OR (SELECT COUNT(DISTINCT {value(field)}) FROM {array} p) <> NEW.profile_count"
    return predicate


def _sqlite_guards() -> None:
    op.execute("CREATE TRIGGER media_output_spec_profiles_json_guard BEFORE INSERT ON media_output_spec_versions WHEN "
               + _profile_json_guard(False) + " BEGIN SELECT RAISE(ABORT, 'output spec profile JSON invalid'); END")
    op.execute(
        "CREATE TRIGGER media_output_specs_initial_pointer BEFORE INSERT ON media_output_specs "
        "WHEN NEW.current_version_id IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'output spec initial pointer must be null'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_specs_pointer_progress BEFORE UPDATE ON media_output_specs "
        "WHEN (OLD.current_version_id IS NOT NULL AND NEW.current_version_id IS NULL) "
        "OR (NEW.current_version_id IS NOT OLD.current_version_id AND NOT EXISTS ("
        "SELECT 1 FROM media_output_spec_versions v WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id "
        "AND v.spec_id = NEW.id AND v.version_no = COALESCE((SELECT version_no FROM media_output_spec_versions "
        "WHERE id = OLD.current_version_id AND org_id = OLD.org_id), 0) + 1 "
        "AND v.profile_count = (SELECT COUNT(*) FROM media_output_spec_items i "
        "WHERE i.org_id = NEW.org_id AND i.spec_version_id = v.id))) "
        "BEGIN SELECT RAISE(ABORT, 'output spec pointer progression invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_spec_versions_no_replace BEFORE INSERT ON media_output_spec_versions "
        "WHEN EXISTS (SELECT 1 FROM media_output_spec_versions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'output spec versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_spec_items_no_replace BEFORE INSERT ON media_output_spec_items "
        "WHEN EXISTS (SELECT 1 FROM media_output_spec_items WHERE org_id = NEW.org_id "
        "AND spec_version_id = NEW.spec_version_id AND sequence = NEW.sequence) "
        "BEGIN SELECT RAISE(ABORT, 'output spec items is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_spec_commands_no_replace BEFORE INSERT ON media_output_spec_commands "
        "WHEN EXISTS (SELECT 1 FROM media_output_spec_commands WHERE org_id = NEW.org_id "
        "AND namespace = NEW.namespace AND idempotency_key = NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'output spec commands is append-only'); END"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
    op.execute(
        "CREATE TRIGGER media_output_specs_natural_guard BEFORE INSERT ON media_output_specs "
        "WHEN EXISTS (SELECT 1 FROM media_output_specs prior WHERE prior.org_id = NEW.org_id "
        "AND prior.media_visual_asset_set_version_id = NEW.media_visual_asset_set_version_id) "
        "BEGIN SELECT RAISE(ABORT, 'output spec already exists'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_specs_identity_guard BEFORE UPDATE ON media_output_specs "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id "
        "OR NEW.media_visual_asset_set_version_id != OLD.media_visual_asset_set_version_id "
        "OR NEW.media_script_version_id != OLD.media_script_version_id "
        "OR COALESCE(NEW.media_storyboard_version_id, '') != COALESCE(OLD.media_storyboard_version_id, '') "
        "OR NEW.duration_seconds != OLD.duration_seconds "
        "OR NEW.region_profile_version_id != OLD.region_profile_version_id "
        "OR NEW.policy_snapshot_id != OLD.policy_snapshot_id "
        "BEGIN SELECT RAISE(ABORT, 'output spec identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_specs_current_version_guard BEFORE UPDATE ON media_output_specs "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_output_spec_versions v "
        "WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id AND v.spec_id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'output spec current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_spec_versions_validate BEFORE INSERT ON media_output_spec_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM media_output_specs s WHERE s.id = NEW.spec_id AND s.org_id = NEW.org_id "
        "AND s.media_visual_asset_set_version_id = NEW.media_visual_asset_set_version_id "
        "AND s.media_script_version_id = NEW.media_script_version_id "
        "AND COALESCE(s.media_storyboard_version_id, '') = COALESCE(NEW.media_storyboard_version_id, '') "
        "AND s.duration_seconds = NEW.duration_seconds AND s.region_profile_version_id = NEW.region_profile_version_id "
        "AND s.policy_snapshot_id = NEW.policy_snapshot_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions visual WHERE visual.id = NEW.media_visual_asset_set_version_id "
        "AND visual.org_id = NEW.org_id AND visual.media_script_version_id = NEW.media_script_version_id "
        "AND visual.duration_seconds = NEW.duration_seconds AND visual.region_profile_version_id = NEW.region_profile_version_id "
        "AND visual.policy_snapshot_id = NEW.policy_snapshot_id AND visual.status NOT IN ('withdrawn', 'superseded') "
        "AND visual.snapshot_hash = NEW.source_visual_snapshot_hash "
        "AND visual.source_script_snapshot_hash = NEW.source_script_snapshot_hash "
        "AND COALESCE(visual.media_storyboard_version_id, '') = COALESCE(NEW.media_storyboard_version_id, '') "
        "AND COALESCE(visual.source_storyboard_snapshot_hash, '') = COALESCE(NEW.source_storyboard_snapshot_hash, '')) "
        "OR json_valid(NEW.profiles_json) = 0 OR json_type(NEW.profiles_json) != 'array' "
        "OR json_array_length(NEW.profiles_json) < 1 OR json_array_length(NEW.profiles_json) > 3 "
        "OR json_array_length(NEW.profiles_json) != NEW.profile_count "
        "OR (NEW.require_all_ratios = 1 AND NEW.profile_count != 3) "
        "OR (NEW.version_no = 1 AND NEW.supersedes_version_id IS NOT NULL) "
        "OR (NEW.version_no > 1 AND (NEW.supersedes_version_id IS NULL OR NOT EXISTS ("
        "SELECT 1 FROM media_output_spec_versions prior WHERE prior.org_id = NEW.org_id AND prior.spec_id = NEW.spec_id "
        "AND prior.id = NEW.supersedes_version_id AND prior.version_no = NEW.version_no - 1))) "
        "OR NEW.template_version != 'media-output-spec-v1' OR NEW.profile_count < 1 OR NEW.profile_count > 3 "
        "OR length(NEW.source_visual_snapshot_hash) != 64 OR NEW.source_visual_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.source_script_snapshot_hash) != 64 OR NEW.source_script_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR (NEW.source_storyboard_snapshot_hash IS NOT NULL AND (length(NEW.source_storyboard_snapshot_hash) != 64 "
        "OR NEW.source_storyboard_snapshot_hash GLOB '*[^0-9A-Fa-f]*')) "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR lower(NEW.profiles_json) LIKE '%\"model\"%' OR lower(NEW.profiles_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.profiles_json) LIKE '%\"credential\"%' OR lower(NEW.profiles_json) LIKE '%\"token\"%' "
        "OR lower(NEW.profiles_json) LIKE '%\"secret\"%' OR lower(NEW.profiles_json) LIKE '%\"password\"%' "
        "OR lower(NEW.profiles_json) LIKE '%\"authorization\"%' OR lower(NEW.profiles_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.profiles_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'output spec version validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_spec_items_validate BEFORE INSERT ON media_output_spec_items "
        "WHEN NOT EXISTS (SELECT 1 FROM media_output_spec_versions WHERE id = NEW.spec_version_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions v, json_each(v.profiles_json) p "
        "WHERE v.id = NEW.spec_version_id AND v.org_id = NEW.org_id "
        "AND json_extract(p.value, '$.sequence') = NEW.sequence "
        "AND json_extract(p.value, '$.profile_key') = NEW.profile_key "
        "AND json_extract(p.value, '$.aspect_ratio') = NEW.aspect_ratio "
        "AND json_extract(p.value, '$.width') = NEW.width AND json_extract(p.value, '$.height') = NEW.height "
        "AND json_extract(p.value, '$.frame_rate') = NEW.frame_rate "
        "AND json_extract(p.value, '$.container_format') = NEW.container_format "
        "AND json_extract(p.value, '$.video_codec') = NEW.video_codec "
        "AND json_extract(p.value, '$.pixel_format') = NEW.pixel_format "
        "AND json_extract(p.value, '$.audio_codec') = NEW.audio_codec "
        "AND json_extract(p.value, '$.audio_sample_rate_hz') = NEW.audio_sample_rate_hz "
        "AND json_extract(p.value, '$.audio_channels') = NEW.audio_channels "
        "AND json_extract(p.value, '$.bitrate_kbps') IS NEW.bitrate_kbps "
        "AND json(json_extract(p.value, '$.subtitle_track_ids')) = json(NEW.subtitle_track_ids_json)) "
        "OR NEW.sequence < 1 OR NEW.aspect_ratio NOT IN ('9:16', '1:1', '16:9') "
        "OR NEW.width < 2 OR NEW.height < 2 OR NEW.width > 7680 OR NEW.height > 7680 "
        "OR NEW.width % 2 != 0 OR NEW.height % 2 != 0 OR NEW.frame_rate < 1 OR NEW.frame_rate > 120 "
        "OR NEW.container_format NOT IN ('mp4', 'mov', 'webm') OR NEW.video_codec NOT IN ('h264', 'hevc', 'av1', 'vp9') "
        "OR NEW.pixel_format NOT IN ('yuv420p', 'yuv422p', 'yuv444p', 'rgba') "
        "OR NEW.audio_codec NOT IN ('aac', 'opus', 'pcm', 'none') OR NEW.audio_sample_rate_hz NOT IN (0, 44100, 48000, 96000) "
        "OR NEW.audio_channels < 0 OR NEW.audio_channels > 8 OR json_valid(NEW.subtitle_track_ids_json) = 0 "
        "OR json_type(NEW.subtitle_track_ids_json) != 'array' "
        "OR (NEW.audio_codec = 'none' AND (NEW.audio_sample_rate_hz != 0 OR NEW.audio_channels != 0)) "
        "OR (NEW.audio_codec != 'none' AND (NEW.audio_sample_rate_hz = 0 OR NEW.audio_channels = 0)) "
        "OR lower(NEW.profile_key) LIKE '%model%' OR lower(NEW.profile_key) LIKE '%provider%' "
        "BEGIN SELECT RAISE(ABORT, 'output spec profile validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_output_spec_commands_validate BEFORE INSERT ON media_output_spec_commands "
        "WHEN NOT EXISTS (SELECT 1 FROM media_output_specs WHERE id = NEW.spec_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions WHERE id = NEW.result_version_id AND org_id = NEW.org_id AND spec_id = NEW.spec_id) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "OR lower(NEW.response_json) LIKE '%\"authorization\"%' OR lower(NEW.response_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'output spec command validation failed'); END"
    )


def _postgres_guards() -> None:
    op.execute("CREATE FUNCTION media_output_spec_profiles_json_guard() RETURNS trigger AS $$ BEGIN IF "
               + _profile_json_guard(True) + " THEN RAISE EXCEPTION 'output spec profile JSON invalid'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
    op.execute("CREATE TRIGGER media_output_spec_profiles_json_guard BEFORE INSERT ON media_output_spec_versions FOR EACH ROW EXECUTE FUNCTION media_output_spec_profiles_json_guard()")
    op.execute(
        "CREATE FUNCTION media_output_specs_pointer_guard() RETURNS trigger AS $$ BEGIN "
        "IF TG_OP = 'INSERT' THEN "
        "IF NEW.current_version_id IS NOT NULL THEN RAISE EXCEPTION 'output spec initial pointer must be null'; END IF; "
        "ELSIF NEW.current_version_id IS DISTINCT FROM OLD.current_version_id THEN "
        "IF NEW.current_version_id IS NULL OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions v "
        "WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id AND v.spec_id = NEW.id "
        "AND v.version_no = COALESCE((SELECT version_no FROM media_output_spec_versions "
        "WHERE id = OLD.current_version_id AND org_id = OLD.org_id), 0) + 1 "
        "AND v.profile_count = (SELECT COUNT(*) FROM media_output_spec_items i "
        "WHERE i.org_id = NEW.org_id AND i.spec_version_id = v.id)) "
        "THEN RAISE EXCEPTION 'output spec pointer progression invalid'; END IF; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_output_specs_pointer_guard BEFORE INSERT OR UPDATE ON media_output_specs FOR EACH ROW EXECUTE FUNCTION media_output_specs_pointer_guard()")
    op.execute(
        "CREATE FUNCTION media_output_spec_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION media_output_spec_append_only_guard()")
    op.execute(
        "CREATE FUNCTION media_output_specs_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.media_visual_asset_set_version_id <> OLD.media_visual_asset_set_version_id "
        "OR NEW.media_script_version_id <> OLD.media_script_version_id OR COALESCE(NEW.media_storyboard_version_id, '') <> COALESCE(OLD.media_storyboard_version_id, '') "
        "OR NEW.duration_seconds <> OLD.duration_seconds OR NEW.region_profile_version_id <> OLD.region_profile_version_id "
        "OR NEW.policy_snapshot_id <> OLD.policy_snapshot_id THEN RAISE EXCEPTION 'output spec identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_output_specs_identity_guard BEFORE UPDATE ON media_output_specs FOR EACH ROW EXECUTE FUNCTION media_output_specs_identity_guard()")
    op.execute(
        "CREATE FUNCTION media_output_spec_versions_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_output_specs s WHERE s.id = NEW.spec_id AND s.org_id = NEW.org_id "
        "AND s.media_visual_asset_set_version_id = NEW.media_visual_asset_set_version_id AND s.media_script_version_id = NEW.media_script_version_id "
        "AND s.duration_seconds = NEW.duration_seconds AND s.region_profile_version_id = NEW.region_profile_version_id AND s.policy_snapshot_id = NEW.policy_snapshot_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions visual WHERE visual.id = NEW.media_visual_asset_set_version_id AND visual.org_id = NEW.org_id "
        "AND visual.snapshot_hash = NEW.source_visual_snapshot_hash AND visual.status NOT IN ('withdrawn','superseded') "
        "AND visual.media_script_version_id = NEW.media_script_version_id AND visual.duration_seconds = NEW.duration_seconds "
        "AND visual.region_profile_version_id = NEW.region_profile_version_id AND visual.policy_snapshot_id = NEW.policy_snapshot_id "
        "AND visual.source_script_snapshot_hash = NEW.source_script_snapshot_hash "
        "AND visual.media_storyboard_version_id IS NOT DISTINCT FROM NEW.media_storyboard_version_id "
        "AND visual.source_storyboard_snapshot_hash IS NOT DISTINCT FROM NEW.source_storyboard_snapshot_hash) "
        "OR jsonb_array_length(NEW.profiles_json::jsonb) <> NEW.profile_count "
        "OR (NEW.require_all_ratios AND NEW.profile_count <> 3) "
        "OR (NEW.version_no = 1 AND NEW.supersedes_version_id IS NOT NULL) "
        "OR (NEW.version_no > 1 AND NOT EXISTS (SELECT 1 FROM media_output_spec_versions prior "
        "WHERE prior.org_id = NEW.org_id AND prior.spec_id = NEW.spec_id AND prior.id = NEW.supersedes_version_id AND prior.version_no = NEW.version_no - 1)) "
        "OR lower(NEW.profiles_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "OR jsonb_typeof(NEW.profiles_json::jsonb) <> 'array' OR NEW.source_visual_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR NEW.source_script_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$' "
        "THEN RAISE EXCEPTION 'output spec version validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_output_spec_versions_guard BEFORE INSERT ON media_output_spec_versions FOR EACH ROW EXECUTE FUNCTION media_output_spec_versions_guard()")
    op.execute(
        "CREATE FUNCTION media_output_spec_items_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_output_spec_versions WHERE id = NEW.spec_version_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions v, jsonb_array_elements(v.profiles_json::jsonb) p "
        "WHERE v.id = NEW.spec_version_id AND v.org_id = NEW.org_id "
        "AND (p->>'sequence')::integer = NEW.sequence AND p->>'profile_key' = NEW.profile_key "
        "AND p->>'aspect_ratio' = NEW.aspect_ratio AND (p->>'width')::integer = NEW.width "
        "AND (p->>'height')::integer = NEW.height AND (p->>'frame_rate')::double precision = NEW.frame_rate "
        "AND p->>'container_format' = NEW.container_format AND p->>'video_codec' = NEW.video_codec "
        "AND p->>'pixel_format' = NEW.pixel_format AND p->>'audio_codec' = NEW.audio_codec "
        "AND (p->>'audio_sample_rate_hz')::integer = NEW.audio_sample_rate_hz "
        "AND (p->>'audio_channels')::integer = NEW.audio_channels "
        "AND (p->>'bitrate_kbps')::integer IS NOT DISTINCT FROM NEW.bitrate_kbps "
        "AND p->'subtitle_track_ids' = NEW.subtitle_track_ids_json::jsonb) "
        "OR NEW.aspect_ratio NOT IN ('9:16','1:1','16:9') OR NEW.width < 2 OR NEW.height < 2 OR NEW.width > 7680 OR NEW.height > 7680 "
        "OR NEW.frame_rate < 1 OR NEW.frame_rate > 120 OR jsonb_typeof(NEW.subtitle_track_ids_json::jsonb) <> 'array' "
        "THEN RAISE EXCEPTION 'output spec profile validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_output_spec_items_guard BEFORE INSERT ON media_output_spec_items FOR EACH ROW EXECUTE FUNCTION media_output_spec_items_guard()")
    op.execute(
        "CREATE FUNCTION media_output_spec_commands_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_output_specs WHERE id = NEW.spec_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_output_spec_versions WHERE id = NEW.result_version_id AND org_id = NEW.org_id AND spec_id = NEW.spec_id) "
        "OR NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL "
        "OR lower(NEW.response_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "THEN RAISE EXCEPTION 'output spec command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_output_spec_commands_guard BEFORE INSERT ON media_output_spec_commands FOR EACH ROW EXECUTE FUNCTION media_output_spec_commands_guard()")


def upgrade() -> None:
    op.create_table(
        "media_output_specs",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("media_visual_asset_set_version_id", sa.String(36), nullable=False), sa.Column("media_script_version_id", sa.String(36), nullable=False),
        sa.Column("media_storyboard_version_id", sa.String(36), nullable=True), sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False), sa.Column("policy_snapshot_id", sa.String(36), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_output_specs_org_id"),
        sa.UniqueConstraint("org_id", "media_visual_asset_set_version_id", name="uq_media_output_specs_visual_source"),
        sa.ForeignKeyConstraint(["org_id", "media_visual_asset_set_version_id"], ["media_visual_asset_set_versions.org_id", "media_visual_asset_set_versions.id"], name="fk_media_output_specs_visual"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_output_specs_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_output_specs_storyboard"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_output_specs_duration"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'withdrawn')", name="ck_media_output_specs_status"),
    )
    op.create_table(
        "media_output_spec_versions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("spec_id", sa.String(36), nullable=False), sa.Column("media_visual_asset_set_version_id", sa.String(36), nullable=False),
        sa.Column("media_script_version_id", sa.String(36), nullable=False), sa.Column("media_storyboard_version_id", sa.String(36), nullable=True),
        sa.Column("version_no", sa.Integer, nullable=False), sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False), sa.Column("policy_snapshot_id", sa.String(36), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("profiles_json", sa.Text, nullable=False), sa.Column("profile_count", sa.Integer, nullable=False),
        sa.Column("require_all_ratios", sa.Boolean, nullable=False), sa.Column("revision_reason", sa.String(1000), nullable=True),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True), sa.Column("source_visual_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("source_script_snapshot_hash", sa.String(64), nullable=False), sa.Column("source_storyboard_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False), sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_output_spec_versions_org_id"),
        sa.UniqueConstraint("org_id", "spec_id", "version_no", name="uq_media_output_spec_versions_no"),
        sa.ForeignKeyConstraint(["org_id", "spec_id"], ["media_output_specs.org_id", "media_output_specs.id"], name="fk_media_output_spec_versions_spec"),
        sa.ForeignKeyConstraint(["org_id", "media_visual_asset_set_version_id"], ["media_visual_asset_set_versions.org_id", "media_visual_asset_set_versions.id"], name="fk_media_output_spec_versions_visual"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_output_spec_versions_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_output_spec_versions_storyboard"),
        sa.ForeignKeyConstraint(["org_id", "supersedes_version_id"], ["media_output_spec_versions.org_id", "media_output_spec_versions.id"], name="fk_media_output_spec_versions_supersedes"),
        sa.CheckConstraint("version_no >= 1", name="ck_media_output_spec_versions_no"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_output_spec_versions_duration"),
        sa.CheckConstraint("template_version = 'media-output-spec-v1'", name="ck_media_output_spec_versions_template"),
        sa.CheckConstraint("status IN ('draft', 'edited', 'in_review', 'approved', 'superseded', 'withdrawn')", name="ck_media_output_spec_versions_status"),
        sa.CheckConstraint("profile_count >= 1 AND profile_count <= 3", name="ck_media_output_spec_versions_count"),
        sa.CheckConstraint("length(source_visual_snapshot_hash) = 64", name="ck_media_output_spec_versions_visual_hash"),
        sa.CheckConstraint("length(source_script_snapshot_hash) = 64", name="ck_media_output_spec_versions_script_hash"),
        sa.CheckConstraint("source_storyboard_snapshot_hash IS NULL OR length(source_storyboard_snapshot_hash) = 64", name="ck_media_output_spec_versions_story_hash"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_media_output_spec_versions_hash"),
    )
    op.create_table(
        "media_output_spec_items",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("spec_version_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False), sa.Column("profile_key", sa.String(64), nullable=False),
        sa.Column("aspect_ratio", sa.String(5), nullable=False), sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False), sa.Column("frame_rate", sa.Float, nullable=False),
        sa.Column("container_format", sa.String(16), nullable=False), sa.Column("video_codec", sa.String(16), nullable=False),
        sa.Column("pixel_format", sa.String(16), nullable=False), sa.Column("audio_codec", sa.String(16), nullable=False),
        sa.Column("audio_sample_rate_hz", sa.Integer, nullable=False), sa.Column("audio_channels", sa.Integer, nullable=False),
        sa.Column("subtitle_track_ids_json", sa.Text, nullable=False), sa.Column("bitrate_kbps", sa.Integer, nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "spec_version_id", "sequence"),
        sa.UniqueConstraint("org_id", "spec_version_id", "aspect_ratio", name="uq_output_items_ratio"),
        sa.UniqueConstraint("org_id", "spec_version_id", "profile_key", name="uq_output_items_key"),
        sa.ForeignKeyConstraint(["org_id", "spec_version_id"], ["media_output_spec_versions.org_id", "media_output_spec_versions.id"], name="fk_media_output_spec_items_version"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_output_spec_items_sequence"),
        sa.CheckConstraint("aspect_ratio IN ('9:16', '1:1', '16:9')", name="ck_media_output_spec_items_ratio"),
        sa.CheckConstraint("width >= 2 AND height >= 2 AND width <= 7680 AND height <= 7680", name="ck_media_output_spec_items_dimensions"),
        sa.CheckConstraint("frame_rate >= 1 AND frame_rate <= 120", name="ck_media_output_spec_items_rate"),
        sa.CheckConstraint("width % 2 = 0 AND height % 2 = 0", name="ck_output_items_even_dimensions"),
        sa.CheckConstraint("(aspect_ratio = '9:16' AND width * 16 = height * 9) OR (aspect_ratio = '1:1' AND width = height) OR (aspect_ratio = '16:9' AND width * 9 = height * 16)", name="ck_output_items_exact_ratio"),
        sa.CheckConstraint("container_format IN ('mp4','mov','webm') AND video_codec IN ('h264','hevc','av1','vp9') AND pixel_format IN ('yuv420p','yuv422p','yuv444p','rgba')", name="ck_output_items_format"),
        sa.CheckConstraint("(audio_codec = 'none' AND audio_sample_rate_hz = 0 AND audio_channels = 0) OR (audio_codec IN ('aac','opus','pcm') AND audio_sample_rate_hz IN (44100,48000,96000) AND audio_channels BETWEEN 1 AND 8)", name="ck_output_items_audio"),
        sa.CheckConstraint("bitrate_kbps IS NULL OR bitrate_kbps BETWEEN 1 AND 1000000", name="ck_output_items_bitrate"),
    )
    op.create_table(
        "media_output_spec_commands",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("spec_id", sa.String(36), nullable=False), sa.Column("result_version_id", sa.String(36), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False), sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "spec_id"], ["media_output_specs.org_id", "media_output_specs.id"], name="fk_media_output_spec_commands_spec"),
        sa.ForeignKeyConstraint(["org_id", "result_version_id"], ["media_output_spec_versions.org_id", "media_output_spec_versions.id"], name="fk_media_output_spec_commands_version"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_output_spec_commands_hash"),
    )
    op.create_index("ix_media_output_specs_visual", "media_output_specs", ["org_id", "media_visual_asset_set_version_id"])
    op.create_index("ix_media_output_spec_versions_spec", "media_output_spec_versions", ["org_id", "spec_id", "version_no"])
    op.create_index("ix_media_output_spec_items_ratio", "media_output_spec_items", ["org_id", "aspect_ratio"])
    op.create_index("ix_media_output_spec_commands_spec", "media_output_spec_commands", ["org_id", "spec_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            "media_output_spec_profiles_json_guard",
            "media_output_specs_initial_pointer", "media_output_specs_pointer_progress",
            "media_output_spec_commands_validate", "media_output_spec_items_validate", "media_output_spec_versions_validate",
            "media_output_specs_current_version_guard", "media_output_specs_identity_guard", "media_output_specs_natural_guard",
            "media_output_spec_commands_no_delete", "media_output_spec_commands_no_update", "media_output_spec_items_no_delete",
            "media_output_spec_items_no_update", "media_output_spec_versions_no_delete", "media_output_spec_versions_no_update",
            "media_output_spec_versions_no_replace", "media_output_spec_items_no_replace", "media_output_spec_commands_no_replace",
        ]
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for table, trigger in (
            ("media_output_spec_versions", "media_output_spec_profiles_json_guard"),
            ("media_output_specs", "media_output_specs_pointer_guard"),
            ("media_output_specs", "media_output_specs_identity_guard"),
            ("media_output_spec_versions", "media_output_spec_versions_guard"),
            ("media_output_spec_items", "media_output_spec_items_guard"),
            ("media_output_spec_commands", "media_output_spec_commands_guard"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        for name in (
            "media_output_spec_profiles_json_guard",
            "media_output_specs_pointer_guard",
            "media_output_spec_commands_guard", "media_output_spec_items_guard", "media_output_spec_versions_guard",
            "media_output_specs_identity_guard", "media_output_spec_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_output_spec_commands_spec", "media_output_spec_commands"),
        ("ix_media_output_spec_items_ratio", "media_output_spec_items"),
        ("ix_media_output_spec_versions_spec", "media_output_spec_versions"),
        ("ix_media_output_specs_visual", "media_output_specs"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_output_spec_commands")
    op.drop_table("media_output_spec_items")
    op.drop_table("media_output_spec_versions")
    op.drop_table("media_output_specs")
