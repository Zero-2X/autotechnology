import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]


def migration():
    spec = importlib.util.spec_from_file_location("analytics003", ROOT / "packages/db/migrations/versions/20260920_analytics_003.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_binding_append_only_and_downgrade():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE observations (org_id TEXT NOT NULL, id TEXT NOT NULL)"))
        conn.execute(sa.text("INSERT INTO observations VALUES ('tenant', 'observation')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
            body = {"id": "snapshot", "org_id": "tenant", "snapshot_hash": "a" * 64,
                    "input_observation_ids": ["observation"]}
            insert = sa.text("INSERT INTO analytics_kpi_snapshots VALUES (:org, :id, :body, :hash)")
            conn.execute(insert, {"org": "tenant", "id": "snapshot", "body": json.dumps(body), "hash": "a" * 64})
            for statement in ("UPDATE analytics_kpi_snapshots SET snapshot_hash='b'", "DELETE FROM analytics_kpi_snapshots"):
                with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                    conn.execute(sa.text(statement))
            with pytest.raises(sa.exc.IntegrityError, match="tenant mismatch"):
                conn.execute(insert, {"org": "other", "id": "snapshot", "body": json.dumps({**body, "org_id": "other"}), "hash": "a" * 64})
            migration().downgrade()
            assert not sa.inspect(conn).has_table("analytics_kpi_snapshots")
            assert sa.inspect(conn).has_table("observations")
