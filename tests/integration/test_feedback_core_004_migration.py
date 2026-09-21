import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]


def migration():
    spec = importlib.util.spec_from_file_location("feedback004", ROOT / "packages/db/migrations/versions/20260921_feedback_core_004.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def test_recommendation_binding_and_append_only():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE feedback_items (org_id TEXT NOT NULL, id TEXT NOT NULL, version_no INTEGER NOT NULL, item_json TEXT NOT NULL, snapshot_hash TEXT NOT NULL, PRIMARY KEY(org_id,id,version_no))"))
        conn.execute(sa.text("INSERT INTO feedback_items VALUES ('tenant','item',1,'{}',:hash)"), {"hash": "a" * 64})
        with Operations.context(MigrationContext.configure(conn)):
            migration().upgrade()
            body = {"id": "rec", "org_id": "tenant", "feedback_item_id": "item"}
            conn.execute(sa.text("INSERT INTO feedback_recommendations VALUES ('tenant','rec',:body,:hash)"), {"body": json.dumps(body), "hash": "b" * 64})
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                conn.execute(sa.text("DELETE FROM feedback_recommendations"))
            migration().downgrade()
            assert not sa.inspect(conn).has_table("feedback_recommendations")
