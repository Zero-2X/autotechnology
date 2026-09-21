"""KNOW-001 Entity/Claim/Evidence facts and tenant-scoped relations."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_know_001"
down_revision = "20260918_found_prov_003"
branch_labels = None
depends_on = None


def _sqlite_append_only(table: str) -> None:
    for action in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN "
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
        "entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("canonical_key", sa.String(512), nullable=False),
        sa.Column("canonical_name", sa.String(512), nullable=False),
        sa.Column("aliases_json", sa.Text, nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_entities_org_id"),
        sa.UniqueConstraint("org_id", "canonical_key", name="uq_entities_canonical_key"),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_entities_status"),
        sa.CheckConstraint("version >= 0", name="ck_entities_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_entities_hash"),
    )
    op.create_index("ix_entities_org_status", "entities", ["org_id", "status", "canonical_key"])

    op.create_table(
        "claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("fact_type", sa.String(128), nullable=False),
        sa.Column("entity_ids_json", sa.Text, nullable=False),
        sa.Column("applicable_versions_json", sa.Text, nullable=False),
        sa.Column("applicable_regions_json", sa.Text, nullable=False),
        sa.Column("applicable_locales_json", sa.Text, nullable=False),
        sa.Column("valid_from", sa.String(64), nullable=True),
        sa.Column("valid_to", sa.String(64), nullable=True),
        sa.Column("review_due_at", sa.String(64), nullable=True),
        sa.Column("supersedes_claim_id", sa.String(36), nullable=True),
        sa.Column("freshness_status", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_claims_org_id"),
        sa.ForeignKeyConstraint(["org_id", "supersedes_claim_id"], ["claims.org_id", "claims.id"], name="fk_claims_supersedes"),
        sa.CheckConstraint("status IN ('draft', 'verified', 'withdrawn')", name="ck_claims_status"),
        sa.CheckConstraint("freshness_status IN ('fresh', 'review_due', 'stale', 'withdrawn')", name="ck_claims_freshness"),
        sa.CheckConstraint("version >= 0", name="ck_claims_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_claims_hash"),
    )
    op.create_index("ix_claims_org_status", "claims", ["org_id", "status", "freshness_status"])
    op.create_index("ix_claims_org_validity", "claims", ["org_id", "valid_from", "valid_to"])

    op.create_table(
        "evidences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_snapshot_id", sa.String(36), nullable=False),
        sa.Column("claim_id", sa.String(36), nullable=True),
        sa.Column("rights_record_version_id", sa.String(36), nullable=True),
        sa.Column("evidence_type", sa.String(128), nullable=False),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("locator", sa.String(2048), nullable=True),
        sa.Column("applicable_versions_json", sa.Text, nullable=False),
        sa.Column("applicable_regions_json", sa.Text, nullable=False),
        sa.Column("applicable_locales_json", sa.Text, nullable=False),
        sa.Column("valid_from", sa.String(64), nullable=True),
        sa.Column("valid_to", sa.String(64), nullable=True),
        sa.Column("review_due_at", sa.String(64), nullable=True),
        sa.Column("captured_at", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_evidences_org_id"),
        sa.ForeignKeyConstraint(["org_id", "source_snapshot_id"], ["source_snapshots.org_id", "source_snapshots.id"], name="fk_evidences_source_snapshot"),
        sa.ForeignKeyConstraint(["org_id", "claim_id"], ["claims.org_id", "claims.id"], name="fk_evidences_claim"),
        sa.ForeignKeyConstraint(["org_id", "rights_record_version_id"], ["rights_record_versions.org_id", "rights_record_versions.id"], name="fk_evidences_rights_version"),
        sa.CheckConstraint("status IN ('captured', 'valid', 'expired', 'revoked')", name="ck_evidences_status"),
        sa.CheckConstraint("version >= 0", name="ck_evidences_version"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_evidences_hash"),
    )
    op.create_index("ix_evidences_org_status", "evidences", ["org_id", "status", "captured_at"])

    op.create_table(
        "entity_claims",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "entity_id", "claim_id"),
        sa.ForeignKeyConstraint(["org_id", "entity_id"], ["entities.org_id", "entities.id"], name="fk_entity_claims_entity"),
        sa.ForeignKeyConstraint(["org_id", "claim_id"], ["claims.org_id", "claims.id"], name="fk_entity_claims_claim"),
    )
    op.create_index("ix_entity_claims_claim", "entity_claims", ["org_id", "claim_id", "entity_id"])

    op.create_table(
        "claim_evidences",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "claim_id", "evidence_id"),
        sa.ForeignKeyConstraint(["org_id", "claim_id"], ["claims.org_id", "claims.id"], name="fk_claim_evidences_claim"),
        sa.ForeignKeyConstraint(["org_id", "evidence_id"], ["evidences.org_id", "evidences.id"], name="fk_claim_evidences_evidence"),
    )
    op.create_index("ix_claim_evidences_claim", "claim_evidences", ["org_id", "claim_id", "evidence_id"])

    op.create_table(
        "knowledge_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_knowledge_commands_hash"),
    )

    op.create_table(
        "knowledge_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "aggregate_type", "aggregate_id", "sequence", name="uq_knowledge_event_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_knowledge_event_sequence"),
    )
    op.create_index("ix_knowledge_events_aggregate", "knowledge_events", ["org_id", "aggregate_type", "aggregate_id", "sequence"])

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"):
            _sqlite_append_only(table)
        op.execute(
            "CREATE TRIGGER entities_immutable_fields BEFORE UPDATE ON entities "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.canonical_key != OLD.canonical_key "
            "OR NEW.canonical_name != OLD.canonical_name OR NEW.aliases_json != OLD.aliases_json "
            "OR NEW.entity_type != OLD.entity_type OR NEW.created_by != OLD.created_by "
            "OR NEW.created_at != OLD.created_at OR NEW.content_hash != OLD.content_hash "
            "BEGIN SELECT RAISE(ABORT, 'entity identity is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER claims_immutable_fields BEFORE UPDATE ON claims "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.statement != OLD.statement "
            "OR NEW.fact_type != OLD.fact_type OR NEW.entity_ids_json != OLD.entity_ids_json "
            "OR NEW.applicable_versions_json != OLD.applicable_versions_json "
            "OR NEW.applicable_regions_json != OLD.applicable_regions_json "
            "OR NEW.applicable_locales_json != OLD.applicable_locales_json "
            "OR NEW.valid_from IS NOT OLD.valid_from OR NEW.valid_to IS NOT OLD.valid_to "
            "OR NEW.review_due_at IS NOT OLD.review_due_at OR NEW.supersedes_claim_id IS NOT OLD.supersedes_claim_id "
            "OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
            "OR NEW.content_hash != OLD.content_hash "
            "BEGIN SELECT RAISE(ABORT, 'claim identity is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER evidences_immutable_fields BEFORE UPDATE ON evidences "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.source_snapshot_id != OLD.source_snapshot_id "
            "OR NEW.rights_record_version_id IS NOT OLD.rights_record_version_id OR NEW.evidence_type != OLD.evidence_type "
            "OR NEW.quote != OLD.quote OR NEW.locator IS NOT OLD.locator "
            "OR NEW.applicable_versions_json != OLD.applicable_versions_json "
            "OR NEW.applicable_regions_json != OLD.applicable_regions_json "
            "OR NEW.applicable_locales_json != OLD.applicable_locales_json "
            "OR NEW.valid_from IS NOT OLD.valid_from OR NEW.valid_to IS NOT OLD.valid_to "
            "OR NEW.review_due_at IS NOT OLD.review_due_at OR NEW.captured_at != OLD.captured_at "
            "OR NEW.created_by != OLD.created_by OR NEW.created_at != OLD.created_at "
            "OR NEW.content_hash != OLD.content_hash "
            "BEGIN SELECT RAISE(ABORT, 'evidence identity is immutable'); END"
        )
        op.execute("CREATE TRIGGER evidences_no_delete BEFORE DELETE ON evidences BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END")
    elif dialect == "postgresql":
        for table in ("entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"):
            _postgres_append_only(table)
        for table, condition, message in (
            ("entities", "NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.canonical_key <> OLD.canonical_key OR NEW.canonical_name <> OLD.canonical_name OR NEW.aliases_json <> OLD.aliases_json OR NEW.entity_type <> OLD.entity_type OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at OR NEW.content_hash <> OLD.content_hash", "entity identity is immutable"),
            ("claims", "NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.statement <> OLD.statement OR NEW.fact_type <> OLD.fact_type OR NEW.entity_ids_json <> OLD.entity_ids_json OR NEW.applicable_versions_json <> OLD.applicable_versions_json OR NEW.applicable_regions_json <> OLD.applicable_regions_json OR NEW.applicable_locales_json <> OLD.applicable_locales_json OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.valid_to IS DISTINCT FROM OLD.valid_to OR NEW.review_due_at IS DISTINCT FROM OLD.review_due_at OR NEW.supersedes_claim_id IS DISTINCT FROM OLD.supersedes_claim_id OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at OR NEW.content_hash <> OLD.content_hash", "claim identity is immutable"),
            ("evidences", "NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.source_snapshot_id <> OLD.source_snapshot_id OR NEW.rights_record_version_id IS DISTINCT FROM OLD.rights_record_version_id OR NEW.evidence_type <> OLD.evidence_type OR NEW.quote <> OLD.quote OR NEW.locator IS DISTINCT FROM OLD.locator OR NEW.applicable_versions_json <> OLD.applicable_versions_json OR NEW.applicable_regions_json <> OLD.applicable_regions_json OR NEW.applicable_locales_json <> OLD.applicable_locales_json OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.valid_to IS DISTINCT FROM OLD.valid_to OR NEW.review_due_at IS DISTINCT FROM OLD.review_due_at OR NEW.captured_at <> OLD.captured_at OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at OR NEW.content_hash <> OLD.content_hash", "evidence identity is immutable"),
        ):
            op.execute(
                f"CREATE FUNCTION {table}_immutable_fields() RETURNS trigger AS $$ BEGIN IF {condition} "
                f"THEN RAISE EXCEPTION '{message}'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
            )
            op.execute(
                f"CREATE TRIGGER {table}_immutable_fields BEFORE UPDATE ON {table} FOR EACH ROW "
                f"EXECUTE FUNCTION {table}_immutable_fields()"
            )
        op.execute("CREATE FUNCTION evidences_no_delete() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'evidence is append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER evidences_no_delete BEFORE DELETE ON evidences FOR EACH ROW EXECUTE FUNCTION evidences_no_delete()")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        for trigger in ("entities_immutable_fields", "claims_immutable_fields", "evidences_immutable_fields", "evidences_no_delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    elif dialect == "postgresql":
        for table in ("entity_claims", "claim_evidences", "knowledge_commands", "knowledge_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        for table in ("entities", "claims", "evidences"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_fields ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable_fields()")
        op.execute("DROP TRIGGER IF EXISTS evidences_no_delete ON evidences")
        op.execute("DROP FUNCTION IF EXISTS evidences_no_delete()")
    op.drop_index("ix_knowledge_events_aggregate", table_name="knowledge_events")
    op.drop_table("knowledge_events")
    op.drop_table("knowledge_commands")
    op.drop_index("ix_claim_evidences_claim", table_name="claim_evidences")
    op.drop_table("claim_evidences")
    op.drop_index("ix_entity_claims_claim", table_name="entity_claims")
    op.drop_table("entity_claims")
    op.drop_index("ix_evidences_org_status", table_name="evidences")
    op.drop_table("evidences")
    op.drop_index("ix_claims_org_validity", table_name="claims")
    op.drop_index("ix_claims_org_status", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_entities_org_status", table_name="entities")
    op.drop_table("entities")
