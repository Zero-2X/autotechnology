"""GEO_REGION-001 tenant scoped region profiles and immutable versions.

The application service owns the full transition policy.  This revision adds
the durable projection and repeats the tenant, identity, JSON and append only
guards at the database boundary.  SQLite does not enable foreign keys in the
repository Alembic environment, so equivalent insert guards are installed
there explicitly.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260920_geo_region_001"
down_revision = "20260920_geo_content_003"
branch_labels = None
depends_on = None


PROFILE_CURRENT_FK = "fk_region_profiles_current_version"
VERSION_PROFILE_FK = "fk_region_profile_versions_profile"
SITE_VERSION_REGION_FK = "fk_site_page_versions_region_profile_version"


def _sqlite_triggers() -> None:
    """Install guards used when SQLite foreign-key enforcement is disabled."""

    op.execute(
        "CREATE TRIGGER region_profiles_no_replace BEFORE INSERT ON region_profiles "
        "WHEN EXISTS (SELECT 1 FROM region_profiles WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'region_profiles is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profiles_identity_immutable BEFORE UPDATE ON region_profiles "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id "
        "OR NEW.region_code != OLD.region_code OR NEW.created_at != OLD.created_at "
        "OR NOT (OLD.status = NEW.status OR (OLD.status = 'active' AND NEW.status = 'retired')) "
        "BEGIN SELECT RAISE(ABORT, 'region profile identity or state is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profiles_no_delete BEFORE DELETE ON region_profiles "
        "BEGIN SELECT RAISE(ABORT, 'region_profiles is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profiles_require_current BEFORE INSERT ON region_profiles "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM region_profile_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.current_version_id AND region_profile_id = NEW.id AND status = 'active') "
        "BEGIN SELECT RAISE(ABORT, 'region profile current version reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profiles_require_current_update BEFORE UPDATE ON region_profiles "
        "WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM region_profile_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.current_version_id AND region_profile_id = NEW.id AND status = 'active') "
        "BEGIN SELECT RAISE(ABORT, 'region profile current version reference invalid'); END"
    )

    op.execute(
        "CREATE TRIGGER region_profile_versions_no_replace BEFORE INSERT ON region_profile_versions "
        "WHEN EXISTS (SELECT 1 FROM region_profile_versions WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'region_profile_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_require_profile BEFORE INSERT ON region_profile_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM region_profiles WHERE org_id = NEW.org_id "
        "AND id = NEW.region_profile_id AND region_code = NEW.region_code) "
        "BEGIN SELECT RAISE(ABORT, 'region profile tenant reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_validate_json BEFORE INSERT ON region_profile_versions "
        "WHEN json_valid(NEW.locales) = 0 OR json_type(NEW.locales) != 'array' "
        "OR json_array_length(NEW.locales) < 1 "
        "OR (SELECT count(*) FROM json_each(NEW.locales)) != "
        "(SELECT count(DISTINCT value) FROM json_each(NEW.locales)) "
        "OR json_valid(NEW.disclosure_rules) = 0 OR json_type(NEW.disclosure_rules) != 'array' "
        "OR json_valid(NEW.restricted_topics) = 0 OR json_type(NEW.restricted_topics) != 'array' "
        "OR json_valid(NEW.platform_eligibility) = 0 OR json_type(NEW.platform_eligibility) != 'array' "
        "BEGIN SELECT RAISE(ABORT, 'region profile version JSON projection invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_identity_immutable BEFORE UPDATE ON region_profile_versions "
        "WHEN NEW.id != OLD.id OR NEW.org_id != OLD.org_id OR NEW.region_profile_id != OLD.region_profile_id "
        "OR NEW.version_no != OLD.version_no OR NEW.region_code != OLD.region_code "
        "OR NEW.locales != OLD.locales OR NEW.timezone != OLD.timezone "
        "OR NEW.date_number_format != OLD.date_number_format OR NEW.units != OLD.units "
        "OR NEW.currency != OLD.currency OR NEW.terminology_version != OLD.terminology_version "
        "OR NEW.disclosure_rules != OLD.disclosure_rules OR NEW.restricted_topics != OLD.restricted_topics "
        "OR NEW.data_residency != OLD.data_residency OR NEW.retention_days != OLD.retention_days "
        "OR NEW.deletion_sla_hours != OLD.deletion_sla_hours "
        "OR NEW.platform_eligibility != OLD.platform_eligibility "
        "OR coalesce(NEW.policy_snapshot_id, '') != coalesce(OLD.policy_snapshot_id, '') "
        "OR coalesce(NEW.valid_from, '') != coalesce(OLD.valid_from, '') "
        "OR coalesce(NEW.valid_to, '') != coalesce(OLD.valid_to, '') "
        "OR coalesce(NEW.review_due_at, '') != coalesce(OLD.review_due_at, '') "
        "OR NEW.snapshot_hash != OLD.snapshot_hash OR NEW.created_by != OLD.created_by "
        "OR NEW.created_at != OLD.created_at "
        "OR NOT (OLD.status = NEW.status OR (OLD.status = 'draft' AND NEW.status = 'active') "
        "OR (OLD.status = 'active' AND NEW.status = 'retired')) "
        "BEGIN SELECT RAISE(ABORT, 'region profile version is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_no_delete BEFORE DELETE ON region_profile_versions "
        "BEGIN SELECT RAISE(ABORT, 'region_profile_versions is append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_require_profile_update BEFORE UPDATE ON region_profile_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM region_profiles WHERE org_id = NEW.org_id "
        "AND id = NEW.region_profile_id AND region_code = NEW.region_code) "
        "BEGIN SELECT RAISE(ABORT, 'region profile tenant reference invalid'); END"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_require_site_parent BEFORE INSERT ON site_page_versions "
        "WHEN NOT EXISTS (SELECT 1 FROM region_profile_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.region_profile_version_id) "
        "BEGIN SELECT RAISE(ABORT, 'site page region version reference invalid'); END"
    )


def _postgres_triggers() -> None:
    op.execute(
        "CREATE FUNCTION region_profiles_guard() RETURNS trigger AS $$ "
        "BEGIN "
        "IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'region_profiles is append-only'; END IF; "
        "IF TG_OP = 'UPDATE' THEN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.region_code <> OLD.region_code "
        "OR NEW.created_at <> OLD.created_at THEN RAISE EXCEPTION 'region profile identity is immutable'; END IF; "
        "IF NOT (NEW.status = OLD.status OR (OLD.status = 'active' AND NEW.status = 'retired')) "
        "THEN RAISE EXCEPTION 'invalid region profile state transition'; END IF; END IF; "
        "IF NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM region_profile_versions "
        "WHERE org_id = NEW.org_id AND id = NEW.current_version_id "
        "AND region_profile_id = NEW.id AND status = 'active') "
        "THEN RAISE EXCEPTION 'region profile current version reference invalid'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER region_profiles_guard BEFORE INSERT OR UPDATE OR DELETE ON region_profiles "
        "FOR EACH ROW EXECUTE FUNCTION region_profiles_guard()"
    )
    op.execute(
        "CREATE FUNCTION region_profile_versions_guard() RETURNS trigger AS $$ "
        "BEGIN "
        "IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'region_profile_versions is append-only'; END IF; "
        "IF TG_OP = 'UPDATE' THEN "
        "IF NEW.id <> OLD.id OR NEW.org_id <> OLD.org_id OR NEW.region_profile_id <> OLD.region_profile_id "
        "OR NEW.version_no <> OLD.version_no OR NEW.region_code <> OLD.region_code "
        "OR NEW.locales <> OLD.locales OR NEW.timezone <> OLD.timezone "
        "OR NEW.date_number_format <> OLD.date_number_format OR NEW.units <> OLD.units "
        "OR NEW.currency <> OLD.currency OR NEW.terminology_version <> OLD.terminology_version "
        "OR NEW.disclosure_rules <> OLD.disclosure_rules OR NEW.restricted_topics <> OLD.restricted_topics "
        "OR NEW.data_residency <> OLD.data_residency OR NEW.retention_days <> OLD.retention_days "
        "OR NEW.deletion_sla_hours <> OLD.deletion_sla_hours OR NEW.platform_eligibility <> OLD.platform_eligibility "
        "OR NEW.policy_snapshot_id IS DISTINCT FROM OLD.policy_snapshot_id "
        "OR NEW.valid_from IS DISTINCT FROM OLD.valid_from OR NEW.valid_to IS DISTINCT FROM OLD.valid_to "
        "OR NEW.review_due_at IS DISTINCT FROM OLD.review_due_at OR NEW.snapshot_hash <> OLD.snapshot_hash "
        "OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at "
        "THEN RAISE EXCEPTION 'region profile version is immutable'; END IF; "
        "IF NOT (NEW.status = OLD.status OR (OLD.status = 'draft' AND NEW.status = 'active') "
        "OR (OLD.status = 'active' AND NEW.status = 'retired')) "
        "THEN RAISE EXCEPTION 'invalid region profile version state transition'; END IF; END IF; "
        "IF NOT EXISTS (SELECT 1 FROM region_profiles WHERE org_id = NEW.org_id "
        "AND id = NEW.region_profile_id AND region_code = NEW.region_code) "
        "THEN RAISE EXCEPTION 'region profile tenant reference invalid'; END IF; "
        "RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER region_profile_versions_guard BEFORE INSERT OR UPDATE OR DELETE ON region_profile_versions "
        "FOR EACH ROW EXECUTE FUNCTION region_profile_versions_guard()"
    )
    op.execute(
        "CREATE FUNCTION site_page_versions_region_guard() RETURNS trigger AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM region_profile_versions WHERE org_id = NEW.org_id "
        "AND id = NEW.region_profile_version_id) THEN "
        "RAISE EXCEPTION 'site page region version reference invalid'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER site_page_versions_region_guard BEFORE INSERT OR UPDATE ON site_page_versions "
        "FOR EACH ROW EXECUTE FUNCTION site_page_versions_region_guard()"
    )


def upgrade() -> None:
    op.create_table(
        "region_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("region_code", sa.String(32), nullable=False),
        sa.Column("current_version_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "region_code"),
        sa.CheckConstraint("length(region_code) >= 2", name="ck_region_profile_code_length"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_region_profile_status"),
    )
    op.create_table(
        "region_profile_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("region_profile_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("region_code", sa.String(32), nullable=False),
        sa.Column("locales", sa.Text, nullable=False),
        sa.Column("timezone", sa.String(128), nullable=False),
        sa.Column("date_number_format", sa.String(256), nullable=False),
        sa.Column("units", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("terminology_version", sa.String(128), nullable=False),
        sa.Column("disclosure_rules", sa.Text, nullable=False),
        sa.Column("restricted_topics", sa.Text, nullable=False),
        sa.Column("data_residency", sa.String(128), nullable=False),
        sa.Column("retention_days", sa.Integer, nullable=False),
        sa.Column("deletion_sla_hours", sa.Integer, nullable=False),
        sa.Column("platform_eligibility", sa.Text, nullable=False),
        sa.Column("policy_snapshot_id", sa.String(36), nullable=True),
        sa.Column("valid_from", sa.String(40), nullable=True),
        sa.Column("valid_to", sa.String(40), nullable=True),
        sa.Column("review_due_at", sa.String(40), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("org_id", "id"),
        sa.UniqueConstraint("org_id", "region_profile_id", "version_no"),
        sa.ForeignKeyConstraint(
            ["org_id", "region_profile_id"],
            ["region_profiles.org_id", "region_profiles.id"],
            name=VERSION_PROFILE_FK,
        ),
        sa.CheckConstraint("version_no >= 1", name="ck_region_version_no"),
        sa.CheckConstraint("units IN ('metric', 'imperial', 'mixed')", name="ck_region_version_units"),
        sa.CheckConstraint("length(currency) = 3", name="ck_region_version_currency"),
        sa.CheckConstraint("retention_days >= 0 AND retention_days <= 36500", name="ck_region_version_retention"),
        sa.CheckConstraint("deletion_sla_hours >= 0 AND deletion_sla_hours <= 87600", name="ck_region_version_deletion_sla"),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_region_version_status"),
        sa.CheckConstraint("length(snapshot_hash) = 64", name="ck_region_version_snapshot_hash"),
    )
    op.create_index(
        "ix_region_profiles_status",
        "region_profiles",
        ["org_id", "status", "region_code"],
    )
    op.create_index(
        "ix_region_profile_versions_lookup",
        "region_profile_versions",
        ["org_id", "region_profile_id", "status", "version_no"],
    )

    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.create_foreign_key(
            PROFILE_CURRENT_FK,
            "region_profiles",
            "region_profile_versions",
            ["org_id", "current_version_id"],
            ["org_id", "id"],
        )
        op.create_foreign_key(
            SITE_VERSION_REGION_FK,
            "site_page_versions",
            "region_profile_versions",
            ["org_id", "region_profile_version_id"],
            ["org_id", "id"],
        )
        _postgres_triggers()
    elif dialect == "sqlite":
        _sqlite_triggers()


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS site_page_versions_region_guard ON site_page_versions")
        op.execute("DROP FUNCTION IF EXISTS site_page_versions_region_guard()")
        op.execute("DROP TRIGGER IF EXISTS region_profile_versions_guard ON region_profile_versions")
        op.execute("DROP FUNCTION IF EXISTS region_profile_versions_guard()")
        op.execute("DROP TRIGGER IF EXISTS region_profiles_guard ON region_profiles")
        op.execute("DROP FUNCTION IF EXISTS region_profiles_guard()")
        op.drop_constraint(SITE_VERSION_REGION_FK, "site_page_versions", type_="foreignkey")
        op.drop_constraint(PROFILE_CURRENT_FK, "region_profiles", type_="foreignkey")
    elif dialect == "sqlite":
        for name, table in (
            ("region_profile_versions_require_site_parent", "site_page_versions"),
            ("region_profile_versions_require_profile_update", "region_profile_versions"),
            ("region_profile_versions_no_delete", "region_profile_versions"),
            ("region_profile_versions_identity_immutable", "region_profile_versions"),
            ("region_profile_versions_validate_json", "region_profile_versions"),
            ("region_profile_versions_require_profile", "region_profile_versions"),
            ("region_profile_versions_no_replace", "region_profile_versions"),
            ("region_profiles_require_current_update", "region_profiles"),
            ("region_profiles_require_current", "region_profiles"),
            ("region_profiles_no_delete", "region_profiles"),
            ("region_profiles_identity_immutable", "region_profiles"),
            ("region_profiles_no_replace", "region_profiles"),
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_region_profile_versions_lookup", table_name="region_profile_versions")
    op.drop_index("ix_region_profiles_status", table_name="region_profiles")
    op.drop_table("region_profile_versions")
    op.drop_table("region_profiles")
