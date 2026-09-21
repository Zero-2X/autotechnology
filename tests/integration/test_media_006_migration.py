from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-09-20T12:00:00Z"


def _insert(connection, table: str, values: dict) -> None:
    columns = ", ".join(values)
    parameters = ", ".join(f":{key}" for key in values)
    connection.execute(sa.text(f"INSERT INTO {table} ({columns}) VALUES ({parameters})"), values)


def test_media_006_migration_guards_lineage_facts_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'media006.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_media_006")
    engine = sa.create_engine(database_url)
    org, other, actor, asset, source = (str(uuid4()) for _ in range(5))
    with engine.begin() as connection:
        edge = dict(org_id=org, source_org_id=org, asset_version_id=asset, sequence=1, lineage_type="variant",
                    source_id=source, source_version_no=2, source_snapshot_hash="a" * 64,
                    relation="derived_from", created_at=STAMP)
        _insert(connection, "media_asset_lineage_edges", edge)
        check = dict(org_id=org, source_org_id=org, asset_version_id=asset, sequence=1, status="valid",
                     reasons_json=json.dumps([]), decision_hash="b" * 64, actor_id=actor, trace_id="trace", created_at=STAMP)
        _insert(connection, "media_asset_lineage_checks", check)
        command_row = dict(org_id=org, source_org_id=org, namespace="create-lineage", idempotency_key="one",
                           request_hash="c" * 64, asset_version_id=asset, command="create_asset_version",
                           response_json=json.dumps({"status": "valid"}), actor_id=actor, trace_id="trace", created_at=STAMP)
        _insert(connection, "media_asset_lineage_commands", command_row)
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE media_asset_lineage_edges SET relation='fact_support' WHERE asset_version_id=:id"), {"id": asset})
        with pytest.raises(sa.exc.IntegrityError, match="validation|tenant"):
            with connection.begin_nested():
                _insert(connection, "media_asset_lineage_edges", {**edge, "sequence": 2, "source_org_id": other, "source_id": str(uuid4())})
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("DELETE FROM media_asset_lineage_checks WHERE asset_version_id=:id"), {"id": asset})
    command.downgrade(config, "20260920_media_005b")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("media_asset_lineage_edges", "media_asset_lineage_checks", "media_asset_lineage_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_qa_content_evaluations")
    engine.dispose()
