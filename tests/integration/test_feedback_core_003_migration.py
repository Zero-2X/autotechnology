import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]


def migration():
    spec = importlib.util.spec_from_file_location("feedback003", ROOT / "packages/db/migrations/versions/20260921_feedback_core_003.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_feedback_item_append_only_and_observation_binding():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE observations (org_id TEXT NOT NULL, id TEXT NOT NULL)"))
        conn.execute(sa.text("INSERT INTO observations VALUES ('tenant', 'observation')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
            body = {"id": "item", "org_id": "tenant", "status": "proposed", "observation_ids": ["observation"]}
            insert = sa.text("INSERT INTO feedback_items VALUES (:org, :id, 1, :body, :hash)")
            conn.execute(insert, {"org": "tenant", "id": "item", "body": json.dumps(body), "hash": "a" * 64})
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                conn.execute(sa.text("DELETE FROM feedback_items"))
            migration().downgrade()
            assert not sa.inspect(conn).has_table("feedback_items")
            assert sa.inspect(conn).has_table("observations")
