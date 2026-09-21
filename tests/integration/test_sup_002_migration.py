import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]


def test_escalation_migration_reversible():
    spec = importlib.util.spec_from_file_location("sup002", ROOT / "packages/db/migrations/versions/20260921_sup_002.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE support_threads (org_id TEXT NOT NULL, id TEXT NOT NULL, PRIMARY KEY(org_id,id))"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade(); assert sa.inspect(conn).has_table("support_escalations"); module.downgrade(); assert not sa.inspect(conn).has_table("support_escalations")
