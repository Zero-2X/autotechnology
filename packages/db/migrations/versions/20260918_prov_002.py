"""PROV-002 adds rights identities, immutable authorization versions, and audit events."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_prov_002"
down_revision = "20260918_found_prov_001"
branch_labels = None
depends_on = None


def _sqlite_append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_no_{action.lower()} "
            f"BEFORE {action} ON {table} BEGIN "
            f"SELECT RAISE(ABORT, '{table} is append-only'); END"
        )


def _postgres_append_only(table: str) -> None:
    op.execute(
        f"CREATE FUNCTION {table}_immutable() RETURNS trigger AS $$ "
        f"BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        f"CREATE TRIGGER {table}_no_mutation BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
    )


def upgrade() -> None:
    op.create_table(
        "rights_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_rights_records_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "source_id"], ["sources.org_id", "sources.id"], name="fk_rights_records_source"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'expired', 'revoked', 'complaint_hold')",
            name="ck_rights_records_status",
        ),
    )
    op.create_index("ix_rights_records_current", "rights_records", ["org_id", "source_id", "status"])

    op.create_table(
        "rights_record_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("rights_record_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("source_snapshot_ids", sa.Text, nullable=False),
        sa.Column("license_ref", sa.String(2048), nullable=True),
        sa.Column("contract_ref", sa.String(2048), nullable=True),
        sa.Column("evidence_object_refs", sa.Text, nullable=False),
        sa.Column("terms_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("rights_holder", sa.String(512), nullable=False),
        sa.Column("permitted_regions", sa.Text, nullable=False),
        sa.Column("permitted_locales", sa.Text, nullable=False),
        sa.Column("permitted_media", sa.Text, nullable=False),
        sa.Column("permitted_use", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.String(64), nullable=True),
        sa.Column("valid_to", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("policy_rule_version", sa.String(256), nullable=False),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("verified_at", sa.String(64), nullable=True),
        sa.Column("verification_reason", sa.String(2048), nullable=True),
        sa.Column("supersedes_version_id", sa.String(36), nullable=True),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "rights_record_id", "version_no", name="uq_rights_record_version"),
        sa.UniqueConstraint("org_id", "id", name="uq_rights_record_versions_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "rights_record_id"],
            ["rights_records.org_id", "rights_records.id"],
            name="fk_rights_record_versions_record",
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_rights_record_version_no"),
        sa.CheckConstraint(
            "permitted_use IN ('research', 'derivative', 'commercial')",
            name="ck_rights_record_version_use",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'expired', 'revoked', 'complaint_hold')",
            name="ck_rights_record_version_status",
        ),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_rights_record_version_hash"),
        sa.CheckConstraint(
            "terms_snapshot_hash IS NULL OR length(terms_snapshot_hash) = 64",
            name="ck_rights_record_version_terms_hash",
        ),
    )
    op.create_index(
        "ix_rights_record_versions_current",
        "rights_record_versions",
        ["org_id", "rights_record_id", "version_no", "status"],
    )

    op.create_table(
        "rights_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_rights_commands_hash"),
    )
    op.create_table(
        "rights_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "aggregate_type", "aggregate_id", "sequence", name="uq_rights_event_sequence"),
        sa.CheckConstraint(
            "event_type IN ('rights.version.created', 'rights.version.verified', 'rights.version.expired', "
            "'rights.version.revoked', 'rights.version.complaint_hold')",
            name="ck_rights_event_type",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_rights_event_sequence"),
    )
    op.create_index("ix_rights_events_org_aggregate", "rights_events", ["org_id", "aggregate_id", "sequence"])

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("rights_commands", "rights_events"):
            _sqlite_append_only(table)
        op.execute(
            "CREATE TRIGGER rights_record_versions_no_delete "
            "BEFORE DELETE ON rights_record_versions BEGIN "
            "SELECT RAISE(ABORT, 'rights record versions are immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER rights_record_versions_immutable_fields "
            "BEFORE UPDATE ON rights_record_versions "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.rights_record_id != OLD.rights_record_id "
            "OR NEW.version_no != OLD.version_no OR NEW.source_snapshot_ids != OLD.source_snapshot_ids "
            "OR NEW.license_ref IS NOT OLD.license_ref OR NEW.contract_ref IS NOT OLD.contract_ref "
            "OR NEW.evidence_object_refs != OLD.evidence_object_refs "
            "OR NEW.terms_snapshot_hash IS NOT OLD.terms_snapshot_hash "
            "OR NEW.rights_holder != OLD.rights_holder OR NEW.permitted_regions != OLD.permitted_regions "
            "OR NEW.permitted_locales != OLD.permitted_locales OR NEW.permitted_media != OLD.permitted_media "
            "OR NEW.permitted_use != OLD.permitted_use OR NEW.valid_from IS NOT OLD.valid_from "
            "OR NEW.valid_to IS NOT OLD.valid_to OR NEW.policy_rule_version != OLD.policy_rule_version "
            "OR NEW.supersedes_version_id IS NOT OLD.supersedes_version_id "
            "OR NEW.snapshot_hash != OLD.snapshot_hash OR NEW.created_by != OLD.created_by "
            "OR NEW.created_at != OLD.created_at "
            "OR json_extract(NEW.payload, '$.rights_record_id') IS NOT json_extract(OLD.payload, '$.rights_record_id') "
            "OR json_extract(NEW.payload, '$.version_no') IS NOT json_extract(OLD.payload, '$.version_no') "
            "OR json_extract(NEW.payload, '$.source_snapshot_ids') IS NOT json_extract(OLD.payload, '$.source_snapshot_ids') "
            "OR json_extract(NEW.payload, '$.rights_holder') IS NOT json_extract(OLD.payload, '$.rights_holder') "
            "OR json_extract(NEW.payload, '$.permitted_use') IS NOT json_extract(OLD.payload, '$.permitted_use') "
            "OR json_extract(NEW.payload, '$.snapshot_hash') IS NOT json_extract(OLD.payload, '$.snapshot_hash') "
            "OR (OLD.status IN ('expired', 'revoked', 'complaint_hold') AND NEW.status != OLD.status) "
            "OR (OLD.status = 'pending' AND NEW.status NOT IN ('pending', 'verified', 'expired', 'revoked', 'complaint_hold')) "
            "OR (OLD.status = 'verified' AND NEW.status NOT IN ('verified', 'expired', 'revoked', 'complaint_hold')) "
            "BEGIN SELECT RAISE(ABORT, 'rights record version identity is immutable'); END"
        )
    elif dialect == "postgresql":
        for table in ("rights_commands", "rights_events"):
            _postgres_append_only(table)
        op.execute(
            "CREATE FUNCTION rights_record_versions_no_delete() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'rights record versions are immutable'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER rights_record_versions_no_delete BEFORE DELETE ON rights_record_versions "
            "FOR EACH ROW EXECUTE FUNCTION rights_record_versions_no_delete()"
        )
        op.execute(
            "CREATE FUNCTION rights_record_versions_immutable_fields() RETURNS trigger AS $$ "
            "BEGIN IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.rights_record_id <> OLD.rights_record_id "
            "OR NEW.version_no <> OLD.version_no OR NEW.source_snapshot_ids <> OLD.source_snapshot_ids "
            "OR NEW.license_ref IS DISTINCT FROM OLD.license_ref OR NEW.contract_ref IS DISTINCT FROM OLD.contract_ref "
            "OR NEW.evidence_object_refs <> OLD.evidence_object_refs "
            "OR NEW.terms_snapshot_hash IS DISTINCT FROM OLD.terms_snapshot_hash "
            "OR NEW.rights_holder <> OLD.rights_holder OR NEW.permitted_regions <> OLD.permitted_regions "
            "OR NEW.permitted_locales <> OLD.permitted_locales OR NEW.permitted_media <> OLD.permitted_media "
            "OR NEW.permitted_use <> OLD.permitted_use OR NEW.valid_from IS DISTINCT FROM OLD.valid_from "
            "OR NEW.valid_to IS DISTINCT FROM OLD.valid_to OR NEW.policy_rule_version <> OLD.policy_rule_version "
            "OR NEW.supersedes_version_id IS DISTINCT FROM OLD.supersedes_version_id "
            "OR NEW.snapshot_hash <> OLD.snapshot_hash OR NEW.created_by <> OLD.created_by "
            "OR NEW.created_at <> OLD.created_at "
            "OR (OLD.status IN ('expired', 'revoked', 'complaint_hold') AND NEW.status <> OLD.status) "
            "THEN RAISE EXCEPTION 'rights record version identity is immutable'; END IF; RETURN NEW; END; "
            "$$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER rights_record_versions_immutable_fields BEFORE UPDATE ON rights_record_versions "
            "FOR EACH ROW EXECUTE FUNCTION rights_record_versions_immutable_fields()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("rights_commands", "rights_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute("DROP TRIGGER IF EXISTS rights_record_versions_no_delete")
        op.execute("DROP TRIGGER IF EXISTS rights_record_versions_immutable_fields")
    elif dialect == "postgresql":
        for table in ("rights_commands", "rights_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        op.execute("DROP TRIGGER IF EXISTS rights_record_versions_no_delete ON rights_record_versions")
        op.execute("DROP FUNCTION IF EXISTS rights_record_versions_no_delete()")
        op.execute("DROP TRIGGER IF EXISTS rights_record_versions_immutable_fields ON rights_record_versions")
        op.execute("DROP FUNCTION IF EXISTS rights_record_versions_immutable_fields()")
    op.drop_index("ix_rights_events_org_aggregate", table_name="rights_events")
    op.drop_table("rights_events")
    op.drop_table("rights_commands")
    op.drop_index("ix_rights_record_versions_current", table_name="rights_record_versions")
    op.drop_table("rights_record_versions")
    op.drop_index("ix_rights_records_current", table_name="rights_records")
    op.drop_table("rights_records")
