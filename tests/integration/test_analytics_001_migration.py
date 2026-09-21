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


def test_analytics_001_migration_guards_versioned_metric_facts_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'analytics001.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_analytics_001")
    engine = sa.create_engine(database_url)
    org, actor, definition_id, replacement_id = (str(uuid4()) for _ in range(4))
    with engine.begin() as connection:
        base = dict(
            id=definition_id, org_id=org, scope_key=org, key="publication.success_rate", version_no=1,
            metric_type="number", unit="ratio", formula="success / attempted",
            dimensions_json=json.dumps(["market"]), window="P7D",
            data_source="analytics.publication.observed", dedupe_rule="event_id",
            quality_rules_json=json.dumps({}), owner_actor_id=actor, initial_status="draft",
            snapshot_hash="a" * 64, created_by=actor, created_at=STAMP,
        )
        _insert(connection, "metric_definitions", base)
        _insert(connection, "metric_definitions", {**base, "id": replacement_id, "version_no": 2, "snapshot_hash": "b" * 64})
        _insert(connection, "metric_definition_state_events", dict(
            definition_id=definition_id, scope_key=org, sequence=1, from_status=None, to_status="draft",
            effective_at=None, retired_at=None, replacement_definition_id=None,
            actor_org_id=org, actor_id=actor, trace_id="trace", created_at=STAMP,
        ))
        _insert(connection, "analytics_metric_definition_commands", dict(
            actor_org_id=org, scope_key=org, namespace="metric_definition.create", idempotency_key="one",
            request_hash="c" * 64, definition_id=definition_id,
            response_json=json.dumps({"id": definition_id, "status": "draft"}),
            actor_id=actor, trace_id="trace", created_at=STAMP,
        ))
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE metric_definitions SET unit='percent' WHERE id=:id"), {"id": definition_id})
        with pytest.raises(sa.exc.IntegrityError, match="validation|CHECK"):
            with connection.begin_nested():
                _insert(connection, "metric_definitions", {**base, "id": str(uuid4()), "scope_key": str(uuid4())})
        with pytest.raises(sa.exc.IntegrityError, match="state validation"):
            with connection.begin_nested():
                _insert(connection, "metric_definition_state_events", dict(
                    definition_id=replacement_id, scope_key=org, sequence=1, from_status="draft", to_status="active",
                    effective_at=STAMP, retired_at=None, replacement_definition_id=None,
                    actor_org_id=org, actor_id=actor, trace_id="trace", created_at=STAMP,
                ))
    command.downgrade(config, "20260920_media_006")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        for table in ("metric_definitions", "metric_definition_state_events", "analytics_metric_definition_commands"):
            assert not inspector.has_table(table)
        assert inspector.has_table("media_asset_lineage_edges")
    engine.dispose()

