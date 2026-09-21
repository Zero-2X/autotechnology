from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]


def test_site_001_migration_creates_tenant_tables_and_locks_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'site001.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    org = "11111111-1111-4111-8111-111111111111"
    page = "22222222-2222-4222-8222-222222222222"
    version = "33333333-3333-4333-8333-333333333333"
    with engine.begin() as connection:
        inspector = sa.inspect(connection)
        assert {"site_pages", "site_page_versions", "site_page_commands"} <= set(inspector.get_table_names())
        # SITE-001 now runs after GEO_REGION-001 at the migration head.  Seed
        # the referenced region snapshot used by this fixture so the new
        # tenant-scoped SitePageVersion guard is exercised without weakening
        # the production constraint.
        connection.execute(sa.text(
            "INSERT INTO region_profiles (id, org_id, region_code, current_version_id, status, created_at) "
            "VALUES ('77777777-7777-4777-8777-777777777777', :org, 'US', NULL, 'active', :stamp)"
        ), {"org": org, "stamp": "2026-09-19T00:00:00Z"})
        connection.execute(sa.text(
            "INSERT INTO region_profile_versions "
            "(id, org_id, region_profile_id, version_no, region_code, locales, timezone, date_number_format, "
            "units, currency, terminology_version, disclosure_rules, restricted_topics, data_residency, "
            "retention_days, deletion_sla_hours, platform_eligibility, policy_snapshot_id, valid_from, valid_to, "
            "review_due_at, status, snapshot_hash, created_by, created_at) VALUES "
            "('55555555-5555-4555-8555-555555555555', :org, '77777777-7777-4777-8777-777777777777', 1, 'US', "
            "'[\"en-US\"]', 'UTC', 'YYYY-MM-DD', 'imperial', 'USD', 'v1', '[]', '[]', 'US', 1, 1, '[]', NULL, "
            "NULL, NULL, NULL, 'draft', :hash, :org, :stamp)"
        ), {"org": org, "stamp": "2026-09-19T00:00:00Z", "hash": "b" * 64})
        connection.execute(sa.text(
            "INSERT INTO site_pages "
            "(id, org_id, page_key, locale, url_path, current_version_id, created_by, created_at, updated_at, payload) "
            "VALUES (:id, :org, 'guide', 'en-US', '/guide', NULL, :actor, :stamp, :stamp, '{}')"
        ), {"id": page, "org": org, "actor": org, "stamp": "2026-09-19T00:00:00Z"})
        connection.execute(sa.text(
            "INSERT INTO site_page_versions "
            "(id, org_id, site_page_id, version_no, canonical_content_version_id, variant_version_id, "
            "region_profile_version_id, locale, url_path, render_mode, status, snapshot_hash, published_at, "
            "created_by, created_at, payload) VALUES "
            "(:id, :org, :page, 1, :canonical, NULL, :region, 'en-US', '/guide', 'ssr', 'draft', :hash, NULL, :actor, :stamp, '{}')"
        ), {
            "id": version, "org": org, "page": page,
            "canonical": "44444444-4444-4444-8444-444444444444",
            "region": "55555555-5555-4555-8555-555555555555",
            "hash": "a" * 64, "actor": org, "stamp": "2026-09-19T00:00:00Z",
        })
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE site_page_versions SET status = 'ready' WHERE id = :id"), {"id": version})
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM site_page_versions WHERE id = :id"), {"id": version})
    command.downgrade(config, "20260919_found_model_003")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("site_page_versions")
        assert not sa.inspect(connection).has_table("site_pages")
    engine.dispose()
