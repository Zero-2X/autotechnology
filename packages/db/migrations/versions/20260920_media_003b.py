"""MEDIA-003B visual AssetVersion reference sets and immutable items."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_003b"
down_revision = "20260920_media_003a"
branch_labels = None
depends_on = None


_APPEND_ONLY = (
    "media_visual_asset_set_versions",
    "media_visual_asset_items",
    "media_visual_asset_commands",
)


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_visual_asset_set_versions_no_replace BEFORE INSERT ON media_visual_asset_set_versions "
        "WHEN EXISTS (SELECT 1 FROM media_visual_asset_set_versions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'visual asset set versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_items_no_replace BEFORE INSERT ON media_visual_asset_items "
        "WHEN EXISTS (SELECT 1 FROM media_visual_asset_items WHERE org_id = NEW.org_id "
        "AND set_version_id = NEW.set_version_id AND sequence = NEW.sequence) "
        "BEGIN SELECT RAISE(ABORT, 'visual asset items is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_commands_no_replace BEFORE INSERT ON media_visual_asset_commands "
        "WHEN EXISTS (SELECT 1 FROM media_visual_asset_commands WHERE org_id = NEW.org_id "
        "AND namespace = NEW.namespace AND idempotency_key = NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'visual asset commands is append-only'); END"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
    op.execute(
        "CREATE TRIGGER media_visual_asset_sets_natural_guard BEFORE INSERT ON media_visual_asset_sets "
        "WHEN EXISTS (SELECT 1 FROM media_visual_asset_sets prior WHERE prior.org_id = NEW.org_id "
        "AND prior.media_script_version_id = NEW.media_script_version_id "
        "AND ((prior.media_storyboard_version_id IS NULL AND NEW.media_storyboard_version_id IS NULL) "
        "OR prior.media_storyboard_version_id = NEW.media_storyboard_version_id)) "
        "BEGIN SELECT RAISE(ABORT, 'visual asset set already exists'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_sets_identity_guard BEFORE UPDATE ON media_visual_asset_sets "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.media_script_version_id != OLD.media_script_version_id "
        "OR COALESCE(NEW.media_storyboard_version_id, '') != COALESCE(OLD.media_storyboard_version_id, '') "
        "OR NEW.duration_seconds != OLD.duration_seconds "
        "BEGIN SELECT RAISE(ABORT, 'visual asset set identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_sets_current_version_guard BEFORE INSERT ON media_visual_asset_sets "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions v "
        "WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id AND v.set_id = NEW.id "
        "AND v.media_script_version_id = NEW.media_script_version_id AND v.duration_seconds = NEW.duration_seconds) "
        "BEGIN SELECT RAISE(ABORT, 'visual asset current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_sets_current_version_guard_update BEFORE UPDATE ON media_visual_asset_sets "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions v "
        "WHERE v.id = NEW.current_version_id AND v.org_id = NEW.org_id AND v.set_id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'visual asset current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_set_versions_validate BEFORE INSERT ON media_visual_asset_set_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM media_visual_asset_sets s WHERE s.id = NEW.set_id AND s.org_id = NEW.org_id "
        "AND s.media_script_version_id = NEW.media_script_version_id "
        "AND COALESCE(s.media_storyboard_version_id, '') = COALESCE(NEW.media_storyboard_version_id, '') "
        "AND s.duration_seconds = NEW.duration_seconds) "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions script WHERE script.id = NEW.media_script_version_id "
        "AND script.org_id = NEW.org_id AND script.duration_seconds = NEW.duration_seconds "
        "AND script.status NOT IN ('withdrawn', 'superseded') AND script.snapshot_hash = NEW.source_script_snapshot_hash) "
        "OR json_valid(NEW.items_json) = 0 OR json_type(NEW.items_json) != 'array' OR json_array_length(NEW.items_json) < 1 "
        "OR json_valid(NEW.rights_snapshot_ids_json) = 0 OR json_type(NEW.rights_snapshot_ids_json) != 'array' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"model\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"credential\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"token\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"secret\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"password\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"authorization\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.items_json || NEW.rights_snapshot_ids_json) LIKE '%\"raw_output\"%' "
        "OR (NEW.version_no = 1 AND NEW.supersedes_version_id IS NOT NULL) "
        "OR (NEW.version_no > 1 AND (NEW.supersedes_version_id IS NULL OR NOT EXISTS ("
        "SELECT 1 FROM media_visual_asset_set_versions prior WHERE prior.org_id = NEW.org_id "
        "AND prior.set_id = NEW.set_id AND prior.id = NEW.supersedes_version_id AND prior.version_no = NEW.version_no - 1))) "
        "OR length(NEW.source_script_snapshot_hash) != 64 OR NEW.source_script_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR (NEW.source_storyboard_snapshot_hash IS NOT NULL AND (length(NEW.source_storyboard_snapshot_hash) != 64 "
        "OR NEW.source_storyboard_snapshot_hash GLOB '*[^0-9A-Fa-f]*')) "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'visual asset set version validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_items_validate BEFORE INSERT ON media_visual_asset_items "
        "WHEN NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions WHERE id = NEW.set_version_id AND org_id = NEW.org_id) "
        "OR NEW.role NOT IN ('cover', 'thumbnail', 'keyframe') "
        "OR (NEW.role = 'cover' AND NEW.media_type NOT IN ('image', 'video', 'thumbnail')) "
        "OR (NEW.role = 'thumbnail' AND NEW.media_type NOT IN ('image', 'thumbnail')) "
        "OR (NEW.role = 'keyframe' AND NEW.media_type NOT IN ('image', 'video', 'thumbnail')) "
        "OR (NEW.role IN ('cover', 'thumbnail') AND NEW.timestamp_ms IS NOT NULL) "
        "OR (NEW.role = 'keyframe' AND (NEW.timestamp_ms IS NULL OR NEW.timestamp_ms < 0)) "
        "OR json_valid(NEW.rights_record_version_ids_json) = 0 OR json_type(NEW.rights_record_version_ids_json) != 'array' "
        "OR json_array_length(NEW.rights_record_version_ids_json) < 1 "
        "OR json_valid(NEW.rights_snapshots_json) = 0 OR json_type(NEW.rights_snapshots_json) != 'array' "
        "OR json_array_length(NEW.rights_snapshots_json) < 1 "
        "OR EXISTS (SELECT 1 FROM json_each(NEW.rights_record_version_ids_json) ref WHERE NOT EXISTS ("
        "SELECT 1 FROM rights_record_versions r WHERE r.org_id = NEW.org_id AND r.id = ref.value "
        "AND r.status = 'verified' AND r.permitted_use IN ('derivative', 'commercial'))) "
        "OR (NEW.storage_object_ref IS NOT NULL AND NEW.storage_object_ref NOT LIKE 'private://%') "
        "OR length(NEW.asset_snapshot_hash) != 64 OR NEW.asset_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'visual asset item validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_visual_asset_commands_validate BEFORE INSERT ON media_visual_asset_commands "
        "WHEN NOT EXISTS (SELECT 1 FROM media_visual_asset_sets WHERE id = NEW.set_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions WHERE id = NEW.result_version_id AND org_id = NEW.org_id AND set_id = NEW.set_id) "
        "OR length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "OR lower(NEW.response_json) LIKE '%\"authorization\"%' OR lower(NEW.response_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'visual asset command validation failed'); END"
    )


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_visual_asset_append_only_guard() RETURNS trigger AS $$ BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION media_visual_asset_append_only_guard()")
    op.execute(
        "CREATE FUNCTION media_visual_asset_sets_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.media_script_version_id <> OLD.media_script_version_id "
        "OR COALESCE(NEW.media_storyboard_version_id, '') <> COALESCE(OLD.media_storyboard_version_id, '') "
        "OR NEW.duration_seconds <> OLD.duration_seconds THEN RAISE EXCEPTION 'visual asset set identity is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_visual_asset_sets_identity_guard BEFORE UPDATE ON media_visual_asset_sets FOR EACH ROW EXECUTE FUNCTION media_visual_asset_sets_identity_guard()")
    op.execute(
        "CREATE FUNCTION media_visual_asset_set_versions_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_visual_asset_sets s WHERE s.id = NEW.set_id AND s.org_id = NEW.org_id "
        "AND s.media_script_version_id = NEW.media_script_version_id AND s.duration_seconds = NEW.duration_seconds "
        "AND COALESCE(s.media_storyboard_version_id, '') = COALESCE(NEW.media_storyboard_version_id, '')) "
        "OR NOT EXISTS (SELECT 1 FROM media_script_versions script WHERE script.id = NEW.media_script_version_id AND script.org_id = NEW.org_id "
        "AND script.duration_seconds = NEW.duration_seconds AND script.status NOT IN ('withdrawn','superseded') AND script.snapshot_hash = NEW.source_script_snapshot_hash) "
        "OR jsonb_typeof(NEW.items_json::jsonb) <> 'array' OR NEW.source_script_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' "
        "OR NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$' THEN RAISE EXCEPTION 'visual asset set version validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_visual_asset_set_versions_guard BEFORE INSERT ON media_visual_asset_set_versions FOR EACH ROW EXECUTE FUNCTION media_visual_asset_set_versions_guard()")
    op.execute(
        "CREATE FUNCTION media_visual_asset_items_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_visual_asset_set_versions WHERE id = NEW.set_version_id AND org_id = NEW.org_id) "
        "OR jsonb_array_length(NEW.rights_record_version_ids_json::jsonb) < 1 OR NEW.asset_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' "
        "THEN RAISE EXCEPTION 'visual asset item validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_visual_asset_items_guard BEFORE INSERT ON media_visual_asset_items FOR EACH ROW EXECUTE FUNCTION media_visual_asset_items_guard()")
    op.execute(
        "CREATE FUNCTION media_visual_asset_commands_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_visual_asset_sets WHERE id = NEW.set_id AND org_id = NEW.org_id) "
        "OR NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL "
        "OR lower(NEW.response_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' "
        "THEN RAISE EXCEPTION 'visual asset command validation failed'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute("CREATE TRIGGER media_visual_asset_commands_guard BEFORE INSERT ON media_visual_asset_commands FOR EACH ROW EXECUTE FUNCTION media_visual_asset_commands_guard()")


def upgrade() -> None:
    op.create_table(
        "media_visual_asset_sets",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("media_script_version_id", sa.String(36), nullable=False), sa.Column("media_storyboard_version_id", sa.String(36), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=False), sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False), sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_visual_asset_sets_org_id"),
        sa.UniqueConstraint("org_id", "media_script_version_id", "media_storyboard_version_id", name="uq_media_visual_asset_sets_source"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_visual_asset_sets_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_visual_asset_sets_storyboard"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_visual_asset_sets_duration"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'withdrawn')", name="ck_media_visual_asset_sets_status"),
    )
    op.create_table(
        "media_visual_asset_set_versions",
        sa.Column("id", sa.String(36), primary_key=True), sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("set_id", sa.String(36), nullable=False), sa.Column("media_script_version_id", sa.String(36), nullable=False),
        sa.Column("media_storyboard_version_id", sa.String(36), nullable=True), sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False), sa.Column("region_profile_version_id", sa.String(36), nullable=False),
        sa.Column("policy_snapshot_id", sa.String(36), nullable=False), sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("items_json", sa.Text, nullable=False),
        sa.Column("item_count", sa.Integer, nullable=False), sa.Column("rights_snapshot_ids_json", sa.Text, nullable=False),
        sa.Column("revision_reason", sa.String(1000), nullable=True), sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("source_script_snapshot_hash", sa.String(64), nullable=False), sa.Column("source_storyboard_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False), sa.Column("created_by", sa.String(36), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_visual_asset_set_versions_org_id"),
        sa.UniqueConstraint("org_id", "set_id", "version_no", name="uq_media_visual_asset_set_versions_no"),
        sa.ForeignKeyConstraint(["org_id", "set_id"], ["media_visual_asset_sets.org_id", "media_visual_asset_sets.id"], name="fk_media_visual_asset_set_versions_set"),
        sa.ForeignKeyConstraint(["org_id", "media_script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_visual_asset_set_versions_script"),
        sa.ForeignKeyConstraint(["org_id", "media_storyboard_version_id"], ["media_storyboard_versions.org_id", "media_storyboard_versions.id"], name="fk_media_visual_asset_set_versions_storyboard"),
        sa.ForeignKeyConstraint(["org_id", "supersedes_version_id"], ["media_visual_asset_set_versions.org_id", "media_visual_asset_set_versions.id"], name="fk_media_visual_asset_set_versions_supersedes"),
        sa.CheckConstraint("version_no >= 1", name="ck_media_visual_asset_set_versions_no"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_visual_asset_set_versions_duration"),
        sa.CheckConstraint("template_version = 'media-visual-asset-set-v1'", name="ck_media_visual_asset_set_versions_template"),
        sa.CheckConstraint("status IN ('draft', 'edited', 'in_review', 'approved', 'superseded', 'withdrawn')", name="ck_media_visual_asset_set_versions_status"),
        sa.CheckConstraint("item_count >= 1", name="ck_media_visual_asset_set_versions_item_count"),
        sa.CheckConstraint("length(source_script_snapshot_hash) = 64", name="ck_media_visual_asset_set_versions_source_hash"),
        sa.CheckConstraint("source_storyboard_snapshot_hash IS NULL OR length(source_storyboard_snapshot_hash) = 64", name="ck_media_visual_asset_set_versions_story_hash"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_media_visual_asset_set_versions_hash"),
    )
    op.create_table(
        "media_visual_asset_items",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("set_version_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False), sa.Column("role", sa.String(16), nullable=False),
        sa.Column("asset_version_id", sa.String(36), nullable=False), sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("format", sa.String(64), nullable=False), sa.Column("storage_object_ref", sa.String(512), nullable=True),
        sa.Column("asset_snapshot_hash", sa.String(64), nullable=False), sa.Column("timestamp_ms", sa.Integer, nullable=True),
        sa.Column("alt_text", sa.String(500), nullable=False), sa.Column("rights_record_version_ids_json", sa.Text, nullable=False),
        sa.Column("rights_snapshots_json", sa.Text, nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "set_version_id", "sequence"),
        sa.ForeignKeyConstraint(["org_id", "set_version_id"], ["media_visual_asset_set_versions.org_id", "media_visual_asset_set_versions.id"], name="fk_media_visual_asset_items_version"),
        sa.CheckConstraint("sequence >= 1", name="ck_media_visual_asset_items_sequence"),
        sa.CheckConstraint("role IN ('cover', 'thumbnail', 'keyframe')", name="ck_media_visual_asset_items_role"),
        sa.CheckConstraint("media_type IN ('image', 'video', 'thumbnail')", name="ck_media_visual_asset_items_media"),
        sa.CheckConstraint("length(asset_snapshot_hash) = 64", name="ck_media_visual_asset_items_hash"),
    )
    op.create_table(
        "media_visual_asset_commands",
        sa.Column("org_id", sa.String(36), nullable=False), sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("set_id", sa.String(36), nullable=False), sa.Column("result_version_id", sa.String(36), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False), sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "set_id"], ["media_visual_asset_sets.org_id", "media_visual_asset_sets.id"], name="fk_media_visual_asset_commands_set"),
        sa.ForeignKeyConstraint(["org_id", "result_version_id"], ["media_visual_asset_set_versions.org_id", "media_visual_asset_set_versions.id"], name="fk_media_visual_asset_commands_version"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_visual_asset_commands_hash"),
    )
    op.create_index("ix_media_visual_asset_sets_script", "media_visual_asset_sets", ["org_id", "media_script_version_id"])
    op.create_index("ix_media_visual_asset_set_versions_set", "media_visual_asset_set_versions", ["org_id", "set_id", "version_no"])
    op.create_index("ix_media_visual_asset_items_asset", "media_visual_asset_items", ["org_id", "asset_version_id"])
    op.create_index("ix_media_visual_asset_commands_set", "media_visual_asset_commands", ["org_id", "set_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            "media_visual_asset_commands_validate", "media_visual_asset_items_validate", "media_visual_asset_set_versions_validate",
            "media_visual_asset_sets_current_version_guard_update", "media_visual_asset_sets_current_version_guard",
            "media_visual_asset_sets_identity_guard", "media_visual_asset_sets_natural_guard",
            "media_visual_asset_commands_no_delete", "media_visual_asset_commands_no_update", "media_visual_asset_items_no_delete",
            "media_visual_asset_items_no_update", "media_visual_asset_set_versions_no_delete", "media_visual_asset_set_versions_no_update",
            "media_visual_asset_set_versions_no_replace", "media_visual_asset_items_no_replace", "media_visual_asset_commands_no_replace",
        ]
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _APPEND_ONLY:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for name in (
            "media_visual_asset_commands_guard", "media_visual_asset_items_guard", "media_visual_asset_set_versions_guard",
            "media_visual_asset_sets_identity_guard", "media_visual_asset_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_visual_asset_commands_set", "media_visual_asset_commands"),
        ("ix_media_visual_asset_items_asset", "media_visual_asset_items"),
        ("ix_media_visual_asset_set_versions_set", "media_visual_asset_set_versions"),
        ("ix_media_visual_asset_sets_script", "media_visual_asset_sets"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_visual_asset_commands")
    op.drop_table("media_visual_asset_items")
    op.drop_table("media_visual_asset_set_versions")
    op.drop_table("media_visual_asset_sets")
