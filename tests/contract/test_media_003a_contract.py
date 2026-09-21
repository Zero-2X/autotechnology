from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_media_003a_subtitle_contracts_are_closed_and_append_only() -> None:
    for name in ("media-subtitle.schema.json", "media-subtitle-version.schema.json"):
        schema = json.loads((ROOT / "packages/contracts/jsonschema" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["x-source"] == "MEDIA-003A"
    version = json.loads((ROOT / "packages/contracts/jsonschema/media-subtitle-version.schema.json").read_text(encoding="utf-8"))
    assert version["x-append-only"] is True
    assert version["properties"]["template_version"]["const"] == "media-subtitle-v1"


def test_media_003a_registry_card_and_boundary_are_registered() -> None:
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(item for item in registry["tasks"] if item["id"] == "MEDIA-003A")
    assert task["status"] == "done"
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_003a.py"]
    assert set(task["contract_refs"]) >= {
        "packages/contracts/jsonschema/media-subtitle.schema.json",
        "packages/contracts/jsonschema/media-subtitle-version.schema.json",
    }
    card = (ROOT / "docs/tasks/MEDIA-003A.md").read_text(encoding="utf-8")
    for marker in ("## 实现规格", "单语", "多个 track", "accessibility", "expected_version_no", "## 补充场景", "## 回滚"):
        assert marker in card
    assert "不翻译" in card and "不调用模型" in card
