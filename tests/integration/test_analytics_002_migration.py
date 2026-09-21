from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
STAMP = "2026-09-20T14:00:00Z"


def _insert(connection, table: str, values: dict) -> None:
    columns = ", ".join(values)
    parameters = ", ".join(f":{key}" for key in values)
    connection.execute(sa.text(f"INSERT INTO {table} ({columns}) VALUES ({parameters})"), values)


def test_analytics_002_migration_guards_observations_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'analytics002.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "20260920_analytics_002")
    engine = sa.create_engine(database_url)
    org, actor, definition_id, observation_id, subject_id, event_id = (str(uuid4()) for _ in range(6))
    with engine.begin() as connection:
        _insert(connection, "metric_definitions", dict(
            id=definition_id, org_id=org, scope_key=org, key="publication.success_rate", version_no=1,
            metric_type="number", unit="ratio", formula="identity", dimensions_json=json.dumps(["market"]),
            window="P7D", data_source="analytics.publication.observed", dedupe_rule="event_id",
            quality_rules_json=json.dumps({}), owner_actor_id=actor, initial_status="draft",
            snapshot_hash="a" * 64, created_by=actor, created_at=STAMP,
        ))
        _insert(connection, "metric_definition_state_events", dict(
            definition_id=definition_id, scope_key=org, sequence=1, from_status=None, to_status="draft",
            effective_at=None, retired_at=None, replacement_definition_id=None,
            actor_org_id=org, actor_id=actor, trace_id="trace", created_at=STAMP,
        ))
        _insert(connection, "metric_definition_state_events", dict(
            definition_id=definition_id, scope_key=org, sequence=2, from_status="draft", to_status="active",
            effective_at=STAMP, retired_at=None, replacement_definition_id=None,
            actor_org_id=org, actor_id=actor, trace_id="trace", created_at=STAMP,
        ))
        row = dict(
            id=observation_id, org_id=org, source="fake", subject_type="publication", subject_id=subject_id,
            metric_definition_id=definition_id, metric_definition_version_no=1,
            metric_name="publication.success_rate", metric_type="number", metric_value_json="0.75",
            observed_at=STAMP, locale="en-US", region="US", data_quality="estimated",
            dedupe_key="fake:publication:one", source_snapshot_ref=None, observation_version=1,
            snapshot_hash="b" * 64, source_event_type="analytics.publication.observed",
            source_event_id=event_id, account_evidence_hash=None, created_by=actor, created_at=STAMP,
        )
        _insert(connection, "observations", row)
        _insert(connection, "analytics_observation_commands", dict(
            org_id=org, namespace="observation.record", idempotency_key="one", request_hash="c" * 64,
            observation_id=observation_id, response_hash="d" * 64, actor_id=actor, trace_id="trace", created_at=STAMP,
        ))
        with pytest.raises(sa.exc.IntegrityError, match="append-only"):
            with connection.begin_nested():
                connection.execute(sa.text("UPDATE observations SET data_quality='validated' WHERE id=:id"), {"id": observation_id})
        with pytest.raises(sa.exc.IntegrityError, match="validation|UNIQUE"):
            with connection.begin_nested():
                _insert(connection, "observations", {**row, "id": str(uuid4()), "source_event_id": str(uuid4()), "metric_value_json": "0.8"})
        with pytest.raises(sa.exc.IntegrityError, match="validation"):
            with connection.begin_nested():
                _insert(connection, "observations", {
                    **row, "id": str(uuid4()), "dedupe_key": "platform:one", "source": "platform",
                    "source_event_id": str(uuid4()), "source_snapshot_ref": "private://platform/one", "account_evidence_hash": None,
                })
    command.downgrade(config, "20260920_analytics_001")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        assert not inspector.has_table("observations")
        assert not inspector.has_table("analytics_observation_commands")
        assert inspector.has_table("metric_definitions")
    engine.dispose()

