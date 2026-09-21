from __future__ import annotations

from pathlib import Path

import pytest


def test_geo_content_002_migration_owns_only_append_only_fixture_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sa = pytest.importorskip("sqlalchemy")
    command = pytest.importorskip("alembic.command")
    config_module = pytest.importorskip("alembic.config")
    database_url = f"sqlite:///{(tmp_path / 'geo_content_002.db').as_posix()}"
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_module.Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    # Pin this ownership regression to GEO_CONTENT-002.  Later revisions own
    # their own projections and must not change this task's table boundary.
    command.upgrade(config, "20260919_geo_content_002")
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        inspector = sa.inspect(connection)
        assert inspector.has_table("geo_query_fixtures")
        assert not inspector.has_table("geo_runs")
        connection.exec_driver_sql(
            "INSERT INTO geo_query_fixtures "
            "(id, org_id, query, locale, region, expected_entities, expected_claim_ids, status, version, fixture_hash, created_by, created_at, updated_by, updated_at, payload) "
            "VALUES ('f', 'o', 'q', 'en-US', 'US', '[]', '[]', 'created', 1, "
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', NULL, '2026-09-19T00:00:00Z', NULL, NULL, '{}')"
        )
        with pytest.raises(Exception, match="append-only"):
            connection.exec_driver_sql("UPDATE geo_query_fixtures SET status='active' WHERE id='f'")
        with pytest.raises(Exception, match="append-only"):
            connection.exec_driver_sql("DELETE FROM geo_query_fixtures WHERE id='f'")
    command.downgrade(config, "20260919_geo_content_001")
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table("geo_query_fixtures")
