import importlib.util
from io import StringIO
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def test_action_schema_and_cleanup_order():
    schema = json.loads((ROOT / "packages/contracts/jsonschema/feedback-action.schema.json").read_text())
    Draft202012Validator.check_schema(schema); assert schema["additionalProperties"] is False
    spec = importlib.util.spec_from_file_location("feedback005pg", ROOT / "packages/db/migrations/versions/20260921_feedback_core_005.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        module.upgrade(); module.downgrade()
    sql = output.getvalue()
    assert "feedback_core_005_guard" in sql
    assert sql.index("DROP TRIGGER IF EXISTS feedback_actions_validate") < sql.index("DROP FUNCTION IF EXISTS feedback_core_005_guard")
