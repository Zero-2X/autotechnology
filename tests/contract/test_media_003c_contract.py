import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_output_spec_contracts_and_registry():
    for name in ("media-output-spec", "media-output-spec-version"):
        schema = json.loads((ROOT / f"packages/contracts/jsonschema/{name}.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["x-source"] == "MEDIA-003C"
    assert schema["x-append-only"] is True
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(task for task in registry["tasks"] if task["id"] == "MEDIA-003C")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_003c.py"]
    assert "packages/contracts/jsonschema/media-output-spec-version.schema.json" in task["contract_refs"]
