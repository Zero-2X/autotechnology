import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_render_job_contract_is_closed_and_registry_linked() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/render-job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert schema["x-source"] == "MEDIA-004A"
    assert "output_profile" in schema["required"]
    assert "asset_version" in schema["properties"]["input_snapshot_hashes"]["required"]
    registry = yaml.safe_load((ROOT / "docs/task-registry.yaml").read_text(encoding="utf-8"))
    task = next(task for task in registry["tasks"] if task["id"] == "MEDIA-004A")
    assert task["migration_refs"] == ["packages/db/migrations/versions/20260920_media_004a.py"]
    assert "packages/contracts/jsonschema/render-job.schema.json" in task["contract_refs"]


def test_render_job_schema_rejects_profile_and_artifact_secrets() -> None:
    schema = json.loads((ROOT / "packages/contracts/jsonschema/render-job.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    assert list(validator.iter_errors({"id": "bad"}))
    # The closed schema must reject an otherwise plausible untracked field.
    profile = {
        "sequence": 1, "profile_key": "square", "aspect_ratio": "1:1", "width": 1080, "height": 1080,
        "frame_rate": 30, "container_format": "mp4", "video_codec": "h264", "pixel_format": "yuv420p",
        "audio_codec": "aac", "audio_sample_rate_hz": 48000, "audio_channels": 2, "subtitle_track_ids": [],
        "provider": "must-not-be-stored",
    }
    assert any(error.validator == "additionalProperties" for error in validator.iter_errors({"output_profile": profile}))
