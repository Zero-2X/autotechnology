from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.media import FakeMediaProbe, MediaAssetQAService, MediaQAError


_SPEC = importlib.util.spec_from_file_location("media_render_fixture_for_qa", Path(__file__).with_name("test_media_render_service.py"))
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


def _render():
    service, renderer, org, actor, script, visual, output, assets = _FIXTURE._service()
    created = service.create_render_job(
        script_version=script, visual_asset_set_version=visual, output_spec_version=output,
        profile_key="square", org_id=org, actor_id=actor, idempotency_key="qa-render",
        created_at=_FIXTURE._fixture.NOW if hasattr(_FIXTURE, "_fixture") else None,
    )
    result = service.execute_render_job(media_render_job_id=created["render_job"]["id"], org_id=org, actor_id=actor)
    return service, renderer, org, actor, created["render_job"], result["artifacts"][0]


def _probe_facts(job, artifact):
    profile = job["output_profile"]
    return {
        artifact["storage_object_ref"]: {
            "container_format": profile["container_format"], "width": profile["width"], "height": profile["height"],
            "frame_rate": profile["frame_rate"], "video_codec": profile["video_codec"],
            "pixel_format": profile["pixel_format"], "duration_seconds": job["duration_seconds"],
            "audio_codec": profile["audio_codec"], "audio_sample_rate_hz": profile["audio_sample_rate_hz"],
            "audio_channels": profile["audio_channels"], "present": profile["audio_codec"] != "none",
        }
    }


def test_media_qa_passes_all_four_checks_and_replays_without_probe_or_storage_side_effect() -> None:
    service, _, org, actor, job, artifact = _render()
    probe = FakeMediaProbe(_probe_facts(job, artifact))
    qa = MediaAssetQAService(render_service=service, probe=probe)
    first = qa.run_media_qa(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                             idempotency_key="qa-1", evaluated_at="2026-09-20T12:00:00Z")
    assert first["status"] == "passed"
    assert all(item["status"] == "passed" for item in first["checks"].values())
    assert first["findings"] == []
    assert len(probe.calls) == 1
    replay = qa.run_media_qa(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                              idempotency_key="qa-1", evaluated_at="2026-09-20T12:00:00Z")
    assert replay == first
    assert len(probe.calls) == 1
    schema = __import__("json").loads((Path(__file__).resolve().parents[3] / "packages/contracts/jsonschema/qa-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first)
    assert qa.outbox_events[0]["event_type"] == "asset.qa_requested"
    assert qa.outbox_events[0]["payload_hash"]


def test_media_qa_reports_visual_audio_and_file_mismatches() -> None:
    service, _, org, actor, job, artifact = _render()
    facts = _probe_facts(job, artifact)
    facts[artifact["storage_object_ref"]]["width"] += 2
    facts[artifact["storage_object_ref"]]["audio_channels"] = 1 if job["output_profile"]["audio_channels"] != 1 else 2
    qa = MediaAssetQAService(render_service=service, probe=FakeMediaProbe(facts))
    report = qa.run_media_qa(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                              idempotency_key="qa-mismatch", evaluated_at="2026-09-20T12:00:00Z")
    codes = {item["code"] for item in report["findings"]}
    assert report["status"] == "failed"
    assert {"VIDEO_PROFILE_MISMATCH", "AUDIO_PROFILE_MISMATCH"} <= codes


def test_media_qa_unknown_probe_is_review_and_subtitle_cues_are_checked() -> None:
    service, _, org, actor, job, artifact = _render()
    qa = MediaAssetQAService(render_service=service, probe=FakeMediaProbe(default={"status": "unknown"}))
    review = qa.run_media_qa(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                              idempotency_key="qa-review", evaluated_at="2026-09-20T12:00:00Z")
    assert review["status"] == "needs_review"
    assert any(item["code"] == "MEDIA_PROBE_UNAVAILABLE" for item in review["findings"])

    track_id = str(uuid4())
    profile = deepcopy(job["output_profile"])
    profile["subtitle_track_ids"] = [track_id]
    subtitle = {
        "id": str(uuid4()), "org_id": org, "tracks": [{"id": track_id, "locale": "en-US", "cues": [
            {"start_ms": 1000, "end_ms": 2200, "text": "first"},
            {"start_ms": 2000, "end_ms": 2500, "text": "overlap"},
        ]}], "duration_seconds": job["duration_seconds"],
    }
    passed_facts = FakeMediaProbe(_probe_facts(job, artifact))
    report = MediaAssetQAService(render_service=service, probe=passed_facts).run_media_qa(
        media_render_job_id=job["id"], org_id=org, actor_id=actor, profile=profile,
        subtitle_version=subtitle, idempotency_key="qa-subtitle", evaluated_at="2026-09-20T12:00:00Z",
    )
    assert report["status"] == "failed"
    assert any(item["code"] == "SUBTITLE_CUE_OVERLAP" for item in report["findings"])


def test_media_qa_checks_tenant_and_expected_version_before_probe() -> None:
    service, _, org, actor, job, _ = _render()
    probe = FakeMediaProbe()
    qa = MediaAssetQAService(render_service=service, probe=probe)
    with pytest.raises(MediaQAError) as foreign:
        qa.run_media_qa(media_render_job_id=job["id"], org_id=str(uuid4()), actor_id=actor, idempotency_key="foreign")
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"
    with pytest.raises(MediaQAError) as stale:
        qa.run_media_qa(media_render_job_id=job["id"], org_id=org, actor_id=actor,
                        idempotency_key="stale", expected_version=999)
    assert stale.value.code == "VERSION_CONFLICT"
    assert probe.calls == []
