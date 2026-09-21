"""MEDIA-001 script roots, immutable versions, Claim refs and commands."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_media_001"
down_revision = "20260920_site_004"
branch_labels = None
depends_on = None


_TABLES = (
    "media_script_versions",
    "media_script_claim_refs",
    "media_script_commands",
)


def _sqlite_guards() -> None:
    op.execute(
        "CREATE TRIGGER media_script_versions_no_replace BEFORE INSERT ON media_script_versions "
        "WHEN EXISTS (SELECT 1 FROM media_script_versions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'media_script_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_script_claim_refs_no_replace BEFORE INSERT ON media_script_claim_refs "
        "WHEN EXISTS (SELECT 1 FROM media_script_claim_refs WHERE org_id = NEW.org_id "
        "AND script_version_id = NEW.script_version_id AND claim_id = NEW.claim_id "
        "AND segment_sequence = NEW.segment_sequence) "
        "BEGIN SELECT RAISE(ABORT, 'media_script_claim_refs is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER media_script_commands_no_replace BEFORE INSERT ON media_script_commands "
        "WHEN EXISTS (SELECT 1 FROM media_script_commands WHERE org_id = NEW.org_id "
        "AND namespace = NEW.namespace AND idempotency_key = NEW.idempotency_key) "
        "BEGIN SELECT RAISE(ABORT, 'media_script_commands is append-only'); END"
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        )
    op.execute(
        "CREATE TRIGGER media_scripts_immutable_identity BEFORE UPDATE ON media_scripts "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR "
        "NEW.variant_version_id != OLD.variant_version_id OR NEW.duration_seconds != OLD.duration_seconds "
        "BEGIN SELECT RAISE(ABORT, 'media script identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER media_scripts_current_version_guard BEFORE INSERT ON media_scripts "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM media_script_versions WHERE id = NEW.current_version_id AND org_id = NEW.org_id "
        "AND media_script_id = NEW.id AND version_no = 1) "
        "BEGIN SELECT RAISE(ABORT, 'media script current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_scripts_current_version_guard_update BEFORE UPDATE ON media_scripts "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM media_script_versions WHERE id = NEW.current_version_id AND org_id = NEW.org_id "
        "AND media_script_id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'media script current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_script_versions_validate BEFORE INSERT ON media_script_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM media_scripts WHERE id = NEW.media_script_id AND org_id = NEW.org_id "
        "AND variant_version_id = NEW.variant_version_id AND duration_seconds = NEW.duration_seconds) "
        "OR NOT EXISTS (SELECT 1 FROM variant_versions WHERE id = NEW.variant_version_id AND org_id = NEW.org_id "
        "AND status = 'approved' AND json_valid(payload) = 1 "
        "AND json_extract(payload, '$.policy_snapshot_id') IS NOT NULL) "
        "OR json_valid(NEW.segments_json) = 0 OR json_type(NEW.segments_json) != 'array' "
        "OR json_valid(NEW.claim_refs_json) = 0 OR json_type(NEW.claim_refs_json) != 'array' "
        "OR json_valid(NEW.claim_snapshot_hashes_json) = 0 OR json_type(NEW.claim_snapshot_hashes_json) != 'array' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"model\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"credential\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"token\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"secret\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"password\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"authorization\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) LIKE '%\"raw_output\"%' "
        "OR length(NEW.snapshot_hash) != 64 OR NEW.snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR length(NEW.source_variant_snapshot_hash) != 64 "
        "OR NEW.source_variant_snapshot_hash GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'media script version validation failed'); END"
    )
    op.execute(
        "CREATE TRIGGER media_script_claim_refs_validate BEFORE INSERT ON media_script_claim_refs "
        "WHEN NOT EXISTS (SELECT 1 FROM media_script_versions WHERE id = NEW.script_version_id AND org_id = NEW.org_id) "
        "OR json_valid(NEW.source_block_ids_json) = 0 OR json_type(NEW.source_block_ids_json) != 'array' "
        "OR NOT EXISTS (SELECT 1 FROM claims WHERE id = NEW.claim_id AND org_id = NEW.org_id "
        "AND status = 'verified' AND freshness_status = 'fresh') "
        "BEGIN SELECT RAISE(ABORT, 'media script Claim reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER media_script_commands_validate BEFORE INSERT ON media_script_commands "
        "WHEN length(NEW.request_hash) != 64 OR NEW.request_hash GLOB '*[^0-9A-Fa-f]*' "
        "OR json_valid(NEW.response_json) = 0 "
        "OR lower(NEW.response_json) LIKE '%\"model\"%' OR lower(NEW.response_json) LIKE '%\"provider\"%' "
        "OR lower(NEW.response_json) LIKE '%\"credential\"%' OR lower(NEW.response_json) LIKE '%\"token\"%' "
        "OR lower(NEW.response_json) LIKE '%\"secret\"%' OR lower(NEW.response_json) LIKE '%\"password\"%' "
        "OR lower(NEW.response_json) LIKE '%\"authorization\"%' OR lower(NEW.response_json) LIKE '%\"api_key\"%' "
        "OR lower(NEW.response_json) LIKE '%\"raw_output\"%' "
        "BEGIN SELECT RAISE(ABORT, 'media script command validation failed'); END"
    )


def _postgres_guards() -> None:
    op.execute(
        "CREATE FUNCTION media_script_append_only_guard() RETURNS trigger AS $$ "
        "BEGIN IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN "
        "RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION media_script_append_only_guard()"
        )
    op.execute(
        "CREATE FUNCTION media_scripts_identity_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.variant_version_id <> OLD.variant_version_id "
        "OR NEW.duration_seconds <> OLD.duration_seconds THEN RAISE EXCEPTION 'media script identity is immutable'; END IF; "
        "IF NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM media_script_versions WHERE id = NEW.current_version_id "
        "AND org_id = NEW.org_id AND media_script_id = NEW.id) THEN RAISE EXCEPTION 'media script current version reference invalid'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_scripts_identity_guard BEFORE UPDATE ON media_scripts "
        "FOR EACH ROW EXECUTE FUNCTION media_scripts_identity_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_script_versions_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_scripts WHERE id = NEW.media_script_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM variant_versions WHERE id = NEW.variant_version_id AND org_id = NEW.org_id "
        "AND status = 'approved' AND payload::jsonb->>'policy_snapshot_id' IS NOT NULL) "
        "OR NOT EXISTS (SELECT 1 FROM media_scripts WHERE id = NEW.media_script_id AND org_id = NEW.org_id "
        "AND variant_version_id = NEW.variant_version_id AND duration_seconds = NEW.duration_seconds) "
        "THEN RAISE EXCEPTION 'media script version validation failed'; END IF; "
        "IF jsonb_typeof(NEW.segments_json::jsonb) <> 'array' OR jsonb_typeof(NEW.claim_refs_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.claim_snapshot_hashes_json::jsonb) <> 'array' THEN RAISE EXCEPTION 'media script JSON projection invalid'; END IF; "
        "IF lower(NEW.segments_json || NEW.claim_refs_json || NEW.claim_snapshot_hashes_json) "
        "~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' THEN "
        "RAISE EXCEPTION 'media script JSON contains provider or credential fields'; END IF; "
        "IF NEW.snapshot_hash !~ '^[0-9A-Fa-f]{64}$' OR NEW.source_variant_snapshot_hash !~ '^[0-9A-Fa-f]{64}$' THEN "
        "RAISE EXCEPTION 'media script hash projection invalid'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_script_versions_guard BEFORE INSERT ON media_script_versions "
        "FOR EACH ROW EXECUTE FUNCTION media_script_versions_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_script_claim_refs_guard() RETURNS trigger AS $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM media_script_versions WHERE id = NEW.script_version_id AND org_id = NEW.org_id) "
        "OR NOT EXISTS (SELECT 1 FROM claims WHERE id = NEW.claim_id AND org_id = NEW.org_id AND status = 'verified' "
        "AND freshness_status = 'fresh') THEN RAISE EXCEPTION 'media script Claim reference invalid'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_script_claim_refs_guard BEFORE INSERT ON media_script_claim_refs "
        "FOR EACH ROW EXECUTE FUNCTION media_script_claim_refs_guard()"
    )
    op.execute(
        "CREATE FUNCTION media_script_commands_guard() RETURNS trigger AS $$ BEGIN "
        "IF NEW.request_hash !~ '^[0-9A-Fa-f]{64}$' OR jsonb_typeof(NEW.response_json::jsonb) IS NULL THEN "
        "RAISE EXCEPTION 'media script command hash or JSON invalid'; END IF; "
        "IF lower(NEW.response_json) ~ '\"(model|provider|credential|token|secret|password|authorization|api_key|raw_output)\"' THEN "
        "RAISE EXCEPTION 'media script command contains provider or credential fields'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER media_script_commands_guard BEFORE INSERT ON media_script_commands "
        "FOR EACH ROW EXECUTE FUNCTION media_script_commands_guard()"
    )


def upgrade() -> None:
    op.create_table(
        "media_scripts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("variant_version_id", sa.String(36), nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_scripts_org_id"),
        sa.UniqueConstraint("org_id", "variant_version_id", "duration_seconds", name="uq_media_scripts_source_duration"),
        sa.ForeignKeyConstraint(["org_id", "variant_version_id"], ["variant_versions.org_id", "variant_versions.id"], name="fk_media_scripts_variant"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_scripts_duration"),
        sa.CheckConstraint("status IN ('draft', 'in_review', 'approved', 'withdrawn')", name="ck_media_scripts_status"),
    )
    op.create_table(
        "media_script_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("media_script_id", sa.String(36), nullable=False),
        sa.Column("variant_version_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("duration_seconds", sa.Integer, nullable=False),
        sa.Column("locale", sa.String(64), nullable=False),
        sa.Column("market", sa.String(64), nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False),
        sa.Column("policy_snapshot_id", sa.String(36), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("segments_json", sa.Text, nullable=False),
        sa.Column("claim_refs_json", sa.Text, nullable=False),
        sa.Column("claim_snapshot_hashes_json", sa.Text, nullable=False),
        sa.Column("source_variant_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("word_count", sa.Integer, nullable=False),
        sa.Column("estimated_duration_seconds", sa.Float, nullable=False),
        sa.Column("human_edited", sa.Boolean, nullable=False),
        sa.Column("edit_reason", sa.String(1000), nullable=True),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_media_script_versions_org_id"),
        sa.UniqueConstraint("org_id", "media_script_id", "version_no", name="uq_media_script_versions_no"),
        sa.ForeignKeyConstraint(["org_id", "media_script_id"], ["media_scripts.org_id", "media_scripts.id"], name="fk_media_script_versions_script"),
        sa.ForeignKeyConstraint(["org_id", "variant_version_id"], ["variant_versions.org_id", "variant_versions.id"], name="fk_media_script_versions_variant"),
        sa.ForeignKeyConstraint(["org_id", "supersedes_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_script_versions_supersedes"),
        sa.CheckConstraint("version_no >= 1", name="ck_media_script_versions_no"),
        sa.CheckConstraint("duration_seconds IN (30, 60, 90)", name="ck_media_script_versions_duration"),
        sa.CheckConstraint("template_version = 'media-script-v1'", name="ck_media_script_versions_template"),
        sa.CheckConstraint("status IN ('draft', 'edited', 'in_review', 'approved', 'superseded', 'withdrawn')", name="ck_media_script_versions_status"),
        sa.CheckConstraint("word_count >= 1", name="ck_media_script_versions_word_count"),
        sa.CheckConstraint("estimated_duration_seconds > 0 AND estimated_duration_seconds <= 90", name="ck_media_script_versions_estimated"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_media_script_versions_hash"),
        sa.CheckConstraint("length(source_variant_snapshot_hash) = 64", name="ck_media_script_versions_source_hash"),
    )
    op.create_table(
        "media_script_claim_refs",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("script_version_id", sa.String(36), nullable=False),
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("segment_sequence", sa.Integer, nullable=False),
        sa.Column("source_block_ids_json", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "script_version_id", "claim_id", "segment_sequence"),
        sa.ForeignKeyConstraint(["org_id", "script_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_script_claim_refs_version"),
        sa.ForeignKeyConstraint(["org_id", "claim_id"], ["claims.org_id", "claims.id"], name="fk_media_script_claim_refs_claim"),
        sa.CheckConstraint("segment_sequence IN (1, 2, 3)", name="ck_media_script_claim_refs_segment"),
    )
    op.create_table(
        "media_script_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("media_script_id", sa.String(36), nullable=False),
        sa.Column("result_version_id", sa.String(36), nullable=False),
        sa.Column("response_json", sa.Text, nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("org_id", "namespace", "idempotency_key"),
        sa.ForeignKeyConstraint(["org_id", "media_script_id"], ["media_scripts.org_id", "media_scripts.id"], name="fk_media_script_commands_script"),
        sa.ForeignKeyConstraint(["org_id", "result_version_id"], ["media_script_versions.org_id", "media_script_versions.id"], name="fk_media_script_commands_version"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_media_script_commands_hash"),
    )
    op.create_index("ix_media_scripts_variant", "media_scripts", ["org_id", "variant_version_id", "duration_seconds"])
    op.create_index("ix_media_script_versions_script", "media_script_versions", ["org_id", "media_script_id", "version_no"])
    op.create_index("ix_media_script_claim_refs_claim", "media_script_claim_refs", ["org_id", "claim_id"])
    op.create_index("ix_media_script_commands_script", "media_script_commands", ["org_id", "media_script_id", "created_at"])
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_guards()
    elif op.get_bind().dialect.name == "postgresql":
        _postgres_guards()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        names = [
            "media_script_commands_validate", "media_script_claim_refs_validate", "media_script_versions_validate",
            "media_scripts_current_version_guard_update", "media_scripts_current_version_guard", "media_scripts_immutable_identity",
            "media_script_commands_no_delete", "media_script_commands_no_update", "media_script_claim_refs_no_delete",
            "media_script_claim_refs_no_update", "media_script_versions_no_delete", "media_script_versions_no_update",
            "media_script_versions_no_replace",
            "media_script_commands_no_replace", "media_script_claim_refs_no_replace",
        ]
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        for table in _TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
        for name in (
            "media_script_commands_guard", "media_script_claim_refs_guard", "media_script_versions_guard",
            "media_scripts_identity_guard", "media_script_append_only_guard",
        ):
            op.execute(f"DROP FUNCTION IF EXISTS {name}()")
    for index, table in (
        ("ix_media_script_commands_script", "media_script_commands"),
        ("ix_media_script_claim_refs_claim", "media_script_claim_refs"),
        ("ix_media_script_versions_script", "media_script_versions"),
        ("ix_media_scripts_variant", "media_scripts"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_script_commands")
    op.drop_table("media_script_claim_refs")
    op.drop_table("media_script_versions")
    op.drop_table("media_scripts")
