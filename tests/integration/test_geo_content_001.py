from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]


def test_geo_content_001_migration_creates_append_only_projection_and_downgrades_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'geo_content_001.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    # Pin this regression to the GEO_CONTENT-001 revision.  Later task
    # migrations (including GEO_CONTENT-002) must not change its ownership
    # assertions when the repository head advances.
    command.upgrade(config, "20260919_geo_content_001")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        assert {"geo_content_checks", "geo_content_commands", "site_publications"}.issubset(tables)
        assert "geo_query_fixtures" not in tables
        connection.exec_driver_sql(
            "INSERT INTO geo_content_checks (id, org_id, actor_id, trace_id, rule_version, status, score, input_hash, output_hash, payload, created_at) "
            "VALUES ('a', 'o', 'a', 't', 'geo-content-001.v1', 'pass', 1, ?, ?, '{}', '2026-01-01T00:00:00Z')",
            ("a" * 64, "b" * 64),
        )
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("UPDATE geo_content_checks SET status = 'fail' WHERE id = 'a'")
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("DELETE FROM geo_content_checks WHERE id = 'a'")
    command.downgrade(config, "20260919_found_site_003")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert not inspector.has_table("geo_content_checks")
        assert not inspector.has_table("geo_content_commands")
        assert inspector.has_table("site_publications")
    engine.dispose()
