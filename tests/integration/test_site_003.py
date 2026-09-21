from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]


def test_site_003_revision_is_projection_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'site003.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert "site_pages" in inspector.get_table_names()
        assert "site_page_versions" in inspector.get_table_names()
        assert "site_publications" in inspector.get_table_names()
        assert "site_structured_data" not in inspector.get_table_names()
    command.downgrade(config, "20260919_found_site_002")
    with engine.connect() as connection:
        assert sa.inspect(connection).has_table("site_publications")
    command.downgrade(config, "20260919_found_site_001")
    engine.dispose()
