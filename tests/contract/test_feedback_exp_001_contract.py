import importlib.util
from io import StringIO
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def test_experiment_contract_and_postgres_sql():
    schema = json.loads((ROOT / "packages/contracts/jsonschema/feedback-experiment.schema.json").read_text())
    Draft202012Validator.check_schema(schema); assert schema["additionalProperties"] is False
    spec = importlib.util.spec_from_file_location("feedbackexp001pg", ROOT / "packages/db/migrations/versions/20260921_feedback_exp_001.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    output = StringIO()
    with Operations.context(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})):
        module.upgrade(); module.downgrade()
    assert "feedback_exp_001_immutable" in output.getvalue()
