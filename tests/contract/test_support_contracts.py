import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def test_support_thread_and_message_contracts_are_closed():
    for name in ("support-thread.schema.json", "support-message.schema.json"):
        schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text())
        Draft202012Validator.check_schema(schema); assert schema["additionalProperties"] is False
