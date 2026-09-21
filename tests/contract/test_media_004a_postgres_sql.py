import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_postgres_render_migration_emits_and_removes_guards() -> None:
    path = Path(__file__).resolve().parents[2] / "packages/db/migrations/versions/20260920_media_004a.py"
    spec = importlib.util.spec_from_file_location("render_job_postgres_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    for table in ("media_render_jobs", "media_render_job_inputs", "media_render_artifacts", "media_render_commands"):
        assert f"CREATE TABLE {table}" in sql
    for function, table in (
        ("media_render_jobs_validate", "media_render_jobs"),
        ("media_render_jobs_identity_guard", "media_render_jobs"),
        ("media_render_artifacts_guard", "media_render_artifacts"),
        ("media_render_commands_guard", "media_render_commands"),
    ):
        assert f"CREATE FUNCTION {function}()" in sql
        trigger_drop = sql.index(f"DROP TRIGGER IF EXISTS {function} ON {table}")
        function_drop = sql.index(f"DROP FUNCTION IF EXISTS {function}()")
        assert trigger_drop < function_drop
