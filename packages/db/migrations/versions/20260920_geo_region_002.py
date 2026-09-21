"""GEO_REGION-002 append-only region policy decision projection.

The region profile and version rows owned by GEO_REGION-001 remain immutable
facts.  This revision stores only the deterministic *result* of an offline
eligibility or deletion-policy evaluation.  It deliberately has no payload or
answer/body column: checks, reasons, alternate links and propagation targets
are compact JSON projections and are guarded as such at the database edge.

The repository's SQLite Alembic fixtures do not enable ``PRAGMA foreign_keys``
for every connection.  The SQLite triggers below therefore repeat the tenant
and parent-reference checks that PostgreSQL gets from composite foreign keys.
Both backends reject replacement, updates and deletes so an audit decision can
only be superseded by a new row.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260920_geo_region_002"
down_revision = "20260920_geo_region_001"
branch_labels = None
depends_on = None


DECISION_REGION_FK = "fk_region_policy_decisions_region_version"
DECISION_SITE_FK = "fk_region_policy_decisions_site_page_version"


# Keep the status set broad enough for both public contracts used by the
# service (eligible/deny/manual_review) and the deletion projection
# (planned/queued/failed/already_deleted).  The service still owns transition
# semantics; the database only accepts known vocabulary.
STATUS_VALUES = (
    "eligible",
    "blocked",
    "deny",
    "review",
    "manual_review",
    "planned",
    "queued",
    "failed",
    "completed",
    "already_deleted",
)


def _sqlite_triggers() -> None:
    """Install tenant, JSON and append-only guards for SQLite."""

    op.execute(
        "CREATE TRIGGER region_policy_decisions_no_replace BEFORE INSERT ON region_policy_decisions "
        "WHEN EXISTS (SELECT 1 FROM region_policy_decisions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'region_policy_decisions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_no_update BEFORE UPDATE ON region_policy_decisions "
        "BEGIN SELECT RAISE(ABORT, 'region_policy_decisions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_no_delete BEFORE DELETE ON region_policy_decisions "
        "BEGIN SELECT RAISE(ABORT, 'region_policy_decisions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_require_region_version BEFORE INSERT ON region_policy_decisions "
        "WHEN NOT EXISTS (SELECT 1 FROM region_profile_versions "
        "WHERE org_id = NEW.org_id AND id = NEW.region_profile_version_id "
        "AND status IN ('active', 'retired')) "
        "BEGIN SELECT RAISE(ABORT, 'region policy region version tenant reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_require_site_version BEFORE INSERT ON region_policy_decisions "
        "WHEN NEW.site_page_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.site_page_version_id "
        "AND region_profile_version_id = NEW.region_profile_version_id "
        "AND status IN ('ready', 'published')) "
        "BEGIN SELECT RAISE(ABORT, 'region policy site page tenant reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_require_page_version BEFORE INSERT ON region_policy_decisions "
        "WHEN NEW.page_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.page_version_id "
        "AND region_profile_version_id = NEW.region_profile_version_id "
        "AND status IN ('ready', 'published')) "
        "BEGIN SELECT RAISE(ABORT, 'region policy page version tenant reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_page_version_alias BEFORE INSERT ON region_policy_decisions "
        "WHEN NEW.site_page_version_id IS NOT NULL AND NEW.page_version_id IS NOT NULL "
        "AND NEW.site_page_version_id != NEW.page_version_id "
        "BEGIN SELECT RAISE(ABORT, 'region policy page version aliases differ'); END"
    )
    # SQLite CHECK constraints cannot contain subqueries.  Validate the JSON
    # projection and reject common raw-answer/body keys in a trigger instead.
    op.execute(
        "CREATE TRIGGER region_policy_decisions_validate_json BEFORE INSERT ON region_policy_decisions "
        "WHEN json_valid(NEW.checks_json) = 0 OR json_type(NEW.checks_json) != 'array' "
        "OR json_valid(NEW.reasons_json) = 0 OR json_type(NEW.reasons_json) != 'array' "
        "OR json_valid(NEW.hreflang_json) = 0 OR json_type(NEW.hreflang_json) != 'array' "
        "OR json_valid(NEW.targets_json) = 0 OR json_type(NEW.targets_json) != 'array' "
        "OR json_valid(NEW.required_disclosures_json) = 0 OR json_type(NEW.required_disclosures_json) != 'array' "
        "OR json_valid(NEW.matched_restrictions_json) = 0 OR json_type(NEW.matched_restrictions_json) != 'array' "
        "OR lower(NEW.checks_json) LIKE '%\"answer\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"answer_body\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"raw_answer\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"raw_body\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"body\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"content\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"html\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"markdown\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"payload\"%' "
        "OR lower(NEW.checks_json) LIKE '%\"text\"%' "
        "OR lower(NEW.reasons_json) LIKE '%\"answer\"%' "
        "OR lower(NEW.reasons_json) LIKE '%\"raw_answer\"%' "
        "OR lower(NEW.reasons_json) LIKE '%\"content\"%' "
        "OR lower(NEW.reasons_json) LIKE '%\"payload\"%' "
        "OR lower(NEW.hreflang_json) LIKE '%\"answer\"%' "
        "OR lower(NEW.hreflang_json) LIKE '%\"content\"%' "
        "OR lower(NEW.targets_json) LIKE '%\"answer\"%' "
        "OR lower(NEW.targets_json) LIKE '%\"content\"%' "
        "OR lower(NEW.required_disclosures_json) LIKE '%\"answer\"%' "
        "OR lower(NEW.required_disclosures_json) LIKE '%\"content\"%' "
        "OR lower(NEW.matched_restrictions_json) LIKE '%\"answer\"%' "
        "OR lower(NEW.matched_restrictions_json) LIKE '%\"content\"%' "
        "BEGIN SELECT RAISE(ABORT, 'region policy JSON projection contains raw body'); END"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_validate_hashes BEFORE INSERT ON region_policy_decisions "
        "WHEN length(coalesce(NEW.input_hash, NEW.input_snapshot_hash, '')) != 64 "
        "OR coalesce(NEW.input_hash, NEW.input_snapshot_hash, '') GLOB '*[^0-9A-Fa-f]*' "
        "OR (NEW.decision_type = 'page' AND length(coalesce(NEW.decision_hash, '')) != 64) "
        "OR (NEW.decision_type = 'page' AND coalesce(NEW.decision_hash, '') GLOB '*[^0-9A-Fa-f]*') "
        "OR (NEW.decision_type = 'deletion' AND length(coalesce(NEW.plan_hash, NEW.decision_hash, '')) != 64) "
        "OR (NEW.decision_type = 'deletion' AND coalesce(NEW.plan_hash, NEW.decision_hash, '') GLOB '*[^0-9A-Fa-f]*') "
        "OR length(coalesce(NEW.request_hash, '')) != 64 "
        "OR coalesce(NEW.request_hash, '') GLOB '*[^0-9A-Fa-f]*' "
        "BEGIN SELECT RAISE(ABORT, 'region policy hash projection invalid'); END"
    )


def _postgres_triggers() -> None:
    """Install equivalent guards for PostgreSQL."""

    op.execute(
        "CREATE FUNCTION region_policy_decisions_guard() RETURNS trigger AS $$ "
        "BEGIN "
        "IF TG_OP = 'UPDATE' OR TG_OP = 'DELETE' THEN "
        "RAISE EXCEPTION 'region_policy_decisions is append-only'; END IF; "
        "IF NOT EXISTS (SELECT 1 FROM region_profile_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.region_profile_version_id "
        "AND status IN ('active', 'retired')) THEN "
        "RAISE EXCEPTION 'region policy region version tenant reference invalid'; END IF; "
        "IF NEW.site_page_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.site_page_version_id "
        "AND region_profile_version_id = NEW.region_profile_version_id "
        "AND status IN ('ready', 'published')) THEN "
        "RAISE EXCEPTION 'region policy site page tenant reference invalid'; END IF; "
        "IF NEW.page_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM site_page_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.page_version_id "
        "AND region_profile_version_id = NEW.region_profile_version_id "
        "AND status IN ('ready', 'published')) THEN "
        "RAISE EXCEPTION 'region policy page version tenant reference invalid'; END IF; "
        "IF NEW.site_page_version_id IS NOT NULL AND NEW.page_version_id IS NOT NULL "
        "AND NEW.site_page_version_id <> NEW.page_version_id THEN "
        "RAISE EXCEPTION 'region policy page version aliases differ'; END IF; "
        "IF jsonb_typeof(NEW.checks_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.reasons_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.hreflang_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.targets_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.required_disclosures_json::jsonb) <> 'array' "
        "OR jsonb_typeof(NEW.matched_restrictions_json::jsonb) <> 'array' THEN "
        "RAISE EXCEPTION 'region policy JSON projection invalid'; END IF; "
        "IF length(coalesce(NEW.input_hash, NEW.input_snapshot_hash, '')) <> 64 "
        "OR coalesce(NEW.input_hash, NEW.input_snapshot_hash, '') !~ '^[0-9A-Fa-f]{64}$' "
        "OR (NEW.decision_type = 'page' AND length(coalesce(NEW.decision_hash, '')) <> 64) "
        "OR (NEW.decision_type = 'page' AND coalesce(NEW.decision_hash, '') !~ '^[0-9A-Fa-f]{64}$') "
        "OR (NEW.decision_type = 'deletion' AND length(coalesce(NEW.plan_hash, NEW.decision_hash, '')) <> 64) THEN "
        "RAISE EXCEPTION 'region policy hash projection invalid'; END IF; "
        "IF NEW.decision_type = 'deletion' AND coalesce(NEW.plan_hash, NEW.decision_hash, '') !~ '^[0-9A-Fa-f]{64}$' THEN "
        "RAISE EXCEPTION 'region policy hash projection invalid'; END IF; "
        "IF coalesce(NEW.request_hash, '') !~ '^[0-9A-Fa-f]{64}$' THEN "
        "RAISE EXCEPTION 'region policy hash projection invalid'; END IF; "
        "IF lower(NEW.checks_json) ~ '\"(answer|answer_body|raw_answer|raw_body|body|content|html|markdown|payload|text)\"' "
        "OR lower(NEW.reasons_json) ~ '\"(answer|answer_body|raw_answer|raw_body|body|content|html|markdown|payload|text)\"' "
        "OR lower(NEW.hreflang_json) ~ '\"(answer|answer_body|raw_answer|raw_body|body|content|html|markdown|payload|text)\"' "
        "OR lower(NEW.targets_json) ~ '\"(answer|answer_body|raw_answer|raw_body|body|content|html|markdown|payload|text)\"' "
        "OR lower(NEW.required_disclosures_json) ~ '\"(answer|answer_body|raw_answer|raw_body|body|content|html|markdown|payload|text)\"' "
        "OR lower(NEW.matched_restrictions_json) ~ '\"(answer|answer_body|raw_answer|raw_body|body|content|html|markdown|payload|text)\"' THEN "
        "RAISE EXCEPTION 'region policy JSON projection contains raw body'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER region_policy_decisions_guard "
        "BEFORE INSERT OR UPDATE OR DELETE ON region_policy_decisions "
        "FOR EACH ROW EXECUTE FUNCTION region_policy_decisions_guard()"
    )


def upgrade() -> None:
    op.create_table(
        "region_policy_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("decision_type", sa.String(16), nullable=False),
        sa.Column("region_profile_version_id", sa.String(36), nullable=False),
        sa.Column("site_page_version_id", sa.String(36), nullable=True),
        # ``page_version_id`` is the public contract name.  Keep the explicit
        # SITE table name as well for callers that use the persistence naming
        # convention; triggers require the aliases to agree when both appear.
        sa.Column("page_version_id", sa.String(36), nullable=True),
        sa.Column("subject_id", sa.String(36), nullable=True),
        sa.Column("subject_type", sa.String(64), nullable=True),
        sa.Column("page_key", sa.String(512), nullable=True),
        sa.Column("locale", sa.String(64), nullable=True),
        sa.Column("market", sa.String(64), nullable=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("decision", sa.String(24), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        # Compact, non-sensitive projections.  Raw page/answer bodies are not
        # accepted; see the backend-specific JSON triggers above.
        sa.Column("checks_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("reasons_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("hreflang_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("targets_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("required_disclosures_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("matched_restrictions_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("x_default_locale", sa.String(32), nullable=True),
        sa.Column("deletion_action", sa.String(24), nullable=True),
        sa.Column("retention_expires_at", sa.String(40), nullable=True),
        sa.Column("anchor_at", sa.String(40), nullable=True),
        sa.Column("delete_by", sa.String(40), nullable=True),
        sa.Column("due_at", sa.String(40), nullable=True),
        sa.Column("data_residency", sa.String(128), nullable=True),
        sa.Column("retention_days", sa.Integer, nullable=True),
        sa.Column("deletion_sla_hours", sa.Integer, nullable=True),
        sa.Column("legal_hold", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("policy_snapshot_id", sa.String(36), nullable=True),
        sa.Column("policy_snapshot_ref", sa.String(256), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("plan_hash", sa.String(64), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("trace_id", sa.String(256), nullable=True),
        sa.Column("evaluated_at", sa.String(40), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "decision_type", "idempotency_key", name="uq_region_policy_decisions_idempotency"),
        sa.ForeignKeyConstraint(
            ["org_id", "region_profile_version_id"],
            ["region_profile_versions.org_id", "region_profile_versions.id"],
            name=DECISION_REGION_FK,
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "site_page_version_id"],
            ["site_page_versions.org_id", "site_page_versions.id"],
            name=DECISION_SITE_FK,
        ),
        sa.ForeignKeyConstraint(
            ["org_id", "page_version_id"],
            ["site_page_versions.org_id", "site_page_versions.id"],
            name="fk_region_policy_decisions_page_version",
        ),
        sa.CheckConstraint("decision_type IN ('page', 'deletion')", name="ck_region_policy_decision_type"),
        sa.CheckConstraint(
            "status IN ('eligible', 'blocked', 'deny', 'review', 'manual_review', 'planned', 'queued', 'failed', 'completed', 'already_deleted')",
            name="ck_region_policy_decision_status",
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('eligible', 'deny', 'manual_review')",
            name="ck_region_policy_decision_value",
        ),
        sa.CheckConstraint(
            "deletion_action IS NULL OR deletion_action IN ('retain', 'delete', 'manual_review', 'already_deleted')",
            name="ck_region_policy_deletion_action",
        ),
        sa.CheckConstraint("retention_days IS NULL OR (retention_days >= 0 AND retention_days <= 36500)", name="ck_region_policy_retention"),
        sa.CheckConstraint("deletion_sla_hours IS NULL OR (deletion_sla_hours >= 0 AND deletion_sla_hours <= 87600)", name="ck_region_policy_deletion_sla"),
        sa.CheckConstraint("input_hash IS NULL OR length(input_hash) = 64", name="ck_region_policy_input_hash"),
        sa.CheckConstraint("decision_hash IS NULL OR length(decision_hash) = 64", name="ck_region_policy_decision_hash"),
        sa.CheckConstraint("request_hash IS NULL OR length(request_hash) = 64", name="ck_region_policy_request_hash"),
        sa.CheckConstraint("input_snapshot_hash IS NULL OR length(input_snapshot_hash) = 64", name="ck_region_policy_snapshot_hash"),
        sa.CheckConstraint("plan_hash IS NULL OR length(plan_hash) = 64", name="ck_region_policy_plan_hash"),
        sa.CheckConstraint("decision_type = 'deletion' OR deletion_action IS NULL", name="ck_region_policy_page_no_delete_action"),
        sa.CheckConstraint("site_page_version_id IS NULL OR page_version_id IS NULL OR site_page_version_id = page_version_id", name="ck_region_policy_page_alias"),
        sa.CheckConstraint("decision_type = 'page' OR decision IS NULL", name="ck_region_policy_deletion_no_decision"),
    )
    op.create_index(
        "ix_region_policy_decisions_lookup",
        "region_policy_decisions",
        ["org_id", "region_profile_version_id", "decision_type", "created_at"],
    )
    op.create_index(
        "ix_region_policy_decisions_subject",
        "region_policy_decisions",
        ["org_id", "subject_id", "created_at"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _postgres_triggers()
    elif dialect == "sqlite":
        _sqlite_triggers()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS region_policy_decisions_guard ON region_policy_decisions")
        op.execute("DROP FUNCTION IF EXISTS region_policy_decisions_guard()")
    elif dialect == "sqlite":
        for name in (
            "region_policy_decisions_validate_json",
            "region_policy_decisions_validate_hashes",
            "region_policy_decisions_page_version_alias",
            "region_policy_decisions_require_page_version",
            "region_policy_decisions_require_site_version",
            "region_policy_decisions_require_region_version",
            "region_policy_decisions_no_delete",
            "region_policy_decisions_no_update",
            "region_policy_decisions_no_replace",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_region_policy_decisions_subject", table_name="region_policy_decisions")
    op.drop_index("ix_region_policy_decisions_lookup", table_name="region_policy_decisions")
    op.drop_table("region_policy_decisions")
