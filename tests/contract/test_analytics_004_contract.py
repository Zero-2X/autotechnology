import importlib.util
import json
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def test_geo_quality_schema_is_closed_and_postgres_guards_are_reversible():
    schema = json.loads((ROOT / "packages/contracts/jsonschema/analytics-geo-quality-snapshot.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    spec = importlib.util.spec_from_file_location("analytics004pg", ROOT / "packages/db/migrations/versions/20260921_analytics_004.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        module.upgrade()
        module.downgrade()
    sql = output.getvalue()
    assert "jsonb_array_elements_text" in sql
    assert sql.index("DROP TRIGGER IF EXISTS analytics_geo_quality_snapshots_validate") < sql.index("DROP FUNCTION IF EXISTS analytics_004_snapshot_guard")
