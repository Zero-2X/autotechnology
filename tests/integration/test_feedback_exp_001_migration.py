import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]


def test_experiment_migration_reversible():
    spec = importlib.util.spec_from_file_location("feedbackexp001", ROOT / "packages/db/migrations/versions/20260921_feedback_exp_001.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
            assert sa.inspect(conn).has_table("feedback_experiments")
            module.downgrade()
            assert not sa.inspect(conn).has_table("feedback_experiments")
