from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_media_003b_visual_asset_contracts_are_closed_and_append_only() -> None:
    for name in ("media-visual-asset-set.schema.json", "media-visual-asset-set-version.schema.json"):
        schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["x-source"] == "MEDIA-003B"
    version = json.loads((ROOT / "packages/contracts/jsonschema/media-visual-asset-set-version.schema.json").read_text(encoding="utf-8"))
    assert version["x-append-only"] is True
    assert version["properties"]["template_version"]["const"] == "media-visual-asset-set-v1"


def test_media_003b_registry_card_and_boundary_are_registered() -> None:
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-003B")
    assert task["status"] == "done"
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_003b.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/asset-version.schema.json",
        "packages/contracts/jsonschema/rights-record-version.schema.json",
        "packages/contracts/jsonschema/media-visual-asset-set.schema.json",
        "packages/contracts/jsonschema/media-visual-asset-set-version.schema.json",
    }
    card = (ROOT / "docs/tasks/MEDIA-003B.md").read_text(encoding="utf-8")
    for marker in ("## 实现规格", "AssetVersion", "RightsRecordVersion", "keyframe", "expected_version_no", "## 补充场景", "## 回滚"):
        assert marker in card
    assert "MEDIA-003C" in card and "MEDIA-004A" in card
