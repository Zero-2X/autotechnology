import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_postgres_output_spec_migration_emits_and_removes_guards():
    path = Path(__file__).resolve().parents[2] / "packages/db/migrations/versions/20260920_media_003c.py"
    spec = importlib.util.spec_from_file_location("output_spec_postgres_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        migration.upgrade()
        migration.downgrade()
    sql = output.getvalue()
    assert "CREATE TABLE media_output_specs" in sql
    assert "ck_output_items_exact_ratio" in sql
    for function, table in (
        ("media_output_spec_profiles_json_guard", "media_output_spec_versions"),
        ("media_output_specs_pointer_guard", "media_output_specs"),
        ("media_output_specs_identity_guard", "media_output_specs"),
        ("media_output_spec_versions_guard", "media_output_spec_versions"),
        ("media_output_spec_items_guard", "media_output_spec_items"),
        ("media_output_spec_commands_guard", "media_output_spec_commands"),
    ):
        assert f"CREATE FUNCTION {function}()" in sql
        trigger_drop = sql.index(f"DROP TRIGGER IF EXISTS {function} ON {table}")
        function_drop = sql.index(f"DROP FUNCTION IF EXISTS {function}()")
        assert trigger_drop < function_drop
