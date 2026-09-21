from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_media_002_contracts_are_closed_and_append_only_version_is_declared() -> None:
    for name in ("media-storyboard.schema.json", "media-storyboard-version.schema.json"):
        schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["x-source"] == "MEDIA-002"
    version = json.loads((ROOT / "packages/contracts/jsonschema/media-storyboard-version.schema.json").read_text(encoding="utf-8"))
    assert version["x-append-only"] is True
    assert version["properties"]["template_version"]["const"] == "media-storyboard-v1"


def test_media_002_registry_and_card_point_to_real_boundary_artifacts() -> None:
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-002")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_002.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/asset-version.schema.json",
        "packages/contracts/jsonschema/rights-record-version.schema.json",
        "packages/contracts/jsonschema/media-storyboard.schema.json",
        "packages/contracts/jsonschema/media-storyboard-version.schema.json",
    }
    card = (ROOT / "docs/tasks/MEDIA-002.md").read_text(encoding="utf-8")
    for marker in ("## 实现规格", "输入数组重排不改变 snapshot hash", "RightsRecordVersion", "expected_version_no", "MEDIA-003A", "MEDIA-004A"):
        assert marker in card
    assert "adapters/platforms" in card
