"""PROV-001 adds tenant-scoped sources, snapshots, and provenance audit logs."""

from alembic import op
import sqlalchemy as sa


revision = "20260918_found_prov_001"
down_revision = "20260918_found_topic_008"
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
        "sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("fetch_method", sa.String(32), nullable=False),
        sa.Column("canonical_url", sa.String(4096), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_snapshot_id", sa.String(36), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_sources_org_id"),
        sa.UniqueConstraint("org_id", "canonical_url", name="uq_sources_org_url"),
        sa.CheckConstraint(
            "source_type IN ('url', 'file', 'api', 'manual', 'support')",
            name="ck_sources_type",
        ),
        sa.CheckConstraint(
            "fetch_method IN ('url', 'file', 'api', 'manual', 'support', 'rss', 'crawler', 'upload')",
            name="ck_sources_fetch_method",
        ),
        sa.CheckConstraint(
            "status IN ('none', 'ingested', 'quarantined', 'usable', 'expired', 'revoked', 'blocked')",
            name="ck_sources_status",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_sources_confidence"),
        sa.CheckConstraint("version >= 1", name="ck_sources_version"),
    )
    op.create_index("ix_sources_org_status", "sources", ["org_id", "status", "created_at"])

    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("captured_at", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_object_ref", sa.String(4096), nullable=False),
        sa.Column("terms_snapshot_ref", sa.String(2048), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "id", name="uq_source_snapshots_org_id"),
        sa.ForeignKeyConstraint(
            ["org_id", "source_id"],
            ["sources.org_id", "sources.id"],
            name="fk_source_snapshots_source",
        ),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_source_snapshots_hash"),
        sa.CheckConstraint("storage_object_ref LIKE 'private://%'", name="ck_source_snapshots_private_ref"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_source_snapshots_confidence"),
        sa.CheckConstraint(
            "status IN ('captured', 'quarantined', 'usable', 'expired', 'revoked', 'blocked')",
            name="ck_source_snapshots_status",
        ),
        sa.CheckConstraint("version >= 0", name="ck_source_snapshots_version"),
    )
    op.create_index(
        "ix_source_snapshots_current",
        "source_snapshots",
        ["org_id", "source_id", "version", "status"],
    )

    op.create_table(
        "source_commands",
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("trace_id", sa.String(256), nullable=False),
        sa.Column("response", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("org_id", "idempotency_key"),
        sa.CheckConstraint("length(payload_hash) = 64", name="ck_source_commands_hash"),
    )

    op.create_table(
        "source_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "org_id", "aggregate_type", "aggregate_id", "sequence",
            name="uq_source_event_sequence",
        ),
        sa.CheckConstraint(
            "event_type IN ('source.ingested', 'source.quarantined', 'source.usable', "
            "'source.expired', 'source.revoked', 'source.blocked')",
            name="ck_source_event_type",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_source_event_sequence"),
    )
    op.create_index("ix_source_events_org_aggregate", "source_events", ["org_id", "aggregate_id", "sequence"])

    op.create_table(
        "source_snapshot_state_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("envelope", sa.Text, nullable=False),
        sa.UniqueConstraint("org_id", "snapshot_id", "sequence", name="uq_source_snapshot_event_sequence"),
        sa.ForeignKeyConstraint(
            ["org_id", "snapshot_id"],
            ["source_snapshots.org_id", "source_snapshots.id"],
            name="fk_source_snapshot_state_event_snapshot",
        ),
        sa.CheckConstraint(
            "event_type IN ('source.snapshot.quarantined', 'source.snapshot.usable', "
            "'source.snapshot.expired', 'source.snapshot.revoked', 'source.snapshot.blocked')",
            name="ck_source_snapshot_event_type",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_source_snapshot_event_sequence"),
    )
    op.create_index(
        "ix_source_snapshot_state_events_org_snapshot",
        "source_snapshot_state_events",
        ["org_id", "snapshot_id", "sequence"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("source_commands", "source_events", "source_snapshot_state_events"):
            _sqlite_append_only(table)
        op.execute(
            "CREATE TRIGGER source_snapshots_immutable_fields "
            "BEFORE UPDATE ON source_snapshots "
            "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.source_id != OLD.source_id "
            "OR NEW.captured_at != OLD.captured_at OR NEW.content_hash != OLD.content_hash "
            "OR NEW.storage_object_ref != OLD.storage_object_ref "
            "OR NEW.terms_snapshot_ref IS NOT OLD.terms_snapshot_ref "
            "OR NEW.confidence != OLD.confidence OR NEW.created_at != OLD.created_at "
            "BEGIN SELECT RAISE(ABORT, 'source snapshot identity is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER source_snapshots_no_delete "
            "BEFORE DELETE ON source_snapshots BEGIN "
            "SELECT RAISE(ABORT, 'source snapshots are immutable'); END"
        )
    elif dialect == "postgresql":
        for table in ("source_commands", "source_events", "source_snapshot_state_events"):
            _postgres_append_only(table)
        op.execute(
            "CREATE FUNCTION source_snapshots_immutable_fields() RETURNS trigger AS $$ "
            "BEGIN IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.source_id <> OLD.source_id "
            "OR NEW.captured_at <> OLD.captured_at OR NEW.content_hash <> OLD.content_hash "
            "OR NEW.storage_object_ref <> OLD.storage_object_ref "
            "OR NEW.terms_snapshot_ref IS DISTINCT FROM OLD.terms_snapshot_ref "
            "OR NEW.confidence <> OLD.confidence OR NEW.created_at <> OLD.created_at "
            "THEN RAISE EXCEPTION 'source snapshot identity is immutable'; END IF; RETURN NEW; END; "
            "$$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER source_snapshots_immutable_fields "
            "BEFORE UPDATE ON source_snapshots FOR EACH ROW "
            "EXECUTE FUNCTION source_snapshots_immutable_fields()"
        )
        op.execute(
            "CREATE FUNCTION source_snapshots_no_delete() RETURNS trigger AS $$ "
            "BEGIN RAISE EXCEPTION 'source snapshots are immutable'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER source_snapshots_no_delete BEFORE DELETE ON source_snapshots FOR EACH ROW "
            "EXECUTE FUNCTION source_snapshots_no_delete()"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in ("source_commands", "source_events", "source_snapshot_state_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_delete")
        op.execute("DROP TRIGGER IF EXISTS source_snapshots_immutable_fields")
        op.execute("DROP TRIGGER IF EXISTS source_snapshots_no_delete")
    elif dialect == "postgresql":
        for table in ("source_commands", "source_events", "source_snapshot_state_events"):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        op.execute("DROP TRIGGER IF EXISTS source_snapshots_immutable_fields ON source_snapshots")
        op.execute("DROP FUNCTION IF EXISTS source_snapshots_immutable_fields()")
        op.execute("DROP TRIGGER IF EXISTS source_snapshots_no_delete ON source_snapshots")
        op.execute("DROP FUNCTION IF EXISTS source_snapshots_no_delete()")
    op.drop_index("ix_source_snapshot_state_events_org_snapshot", table_name="source_snapshot_state_events")
    op.drop_table("source_snapshot_state_events")
    op.drop_index("ix_source_events_org_aggregate", table_name="source_events")
    op.drop_table("source_events")
    op.drop_table("source_commands")
    op.drop_index("ix_source_snapshots_current", table_name="source_snapshots")
    op.drop_table("source_snapshots")
    op.drop_index("ix_sources_org_status", table_name="sources")
    op.drop_table("sources")
