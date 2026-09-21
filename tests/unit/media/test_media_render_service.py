from copy import deepcopy
import importlib.util
from pathlib import Path
import threading
import time
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.media import (
    FakeRenderer,
    MediaOutputSpecService,
    MediaRenderError,
    MediaRenderService,
    MediaVisualAssetSetService,
)


ROOT = Path(__file__).resolve().parents[3]
_fixture_spec = importlib.util.spec_from_file_location("render_visual_fixture", Path(__file__).with_name("test_media_visual_asset_service.py"))
_fixture = importlib.util.module_from_spec(_fixture_spec)
assert _fixture_spec.loader is not None
_fixture_spec.loader.exec_module(_fixture)


def _source(*, profile: str = "square"):
    visual_service, org, actor, script, assets, rights = _fixture._fixture()
    visual = visual_service.create_asset_set(
        script, items=_fixture._items(assets, rights), asset_versions=assets, rights_versions=rights,
        org_id=org, actor_id=actor, idempotency_key="visual", created_at=_fixture.NOW,
    )["version"]
    ratio = {"square": "1:1", "portrait": "9:16", "landscape": "16:9"}[profile]
    output = MediaOutputSpecService().create_output_spec(
        visual, profiles=[{"aspect_ratio": ratio}], org_id=org, actor_id=actor,
        idempotency_key="output", created_at=_fixture.NOW,
    )["version"]
    return org, actor, script, visual, output, assets


def _service():
    org, actor, script, visual, output, assets = _source()
    renderer = FakeRenderer(content=b"rendered-bytes")
    service = MediaRenderService(renderer=renderer)
    return service, renderer, org, actor, script, visual, output, assets


def test_create_locks_versions_profile_hashes_and_replays() -> None:
    service, _, org, actor, script, visual, output, _ = _service()
    first = service.create_render_job(
        script_version=script, visual_asset_set_version=visual, output_spec_version=output,
        profile_key="square", org_id=org, actor_id=actor, idempotency_key="render-1",
        created_at=_fixture.NOW,
    )
    replay = service.create_render_job(
        script_version=deepcopy(script), visual_asset_set_version=deepcopy(visual), output_spec_version=deepcopy(output),
        profile_key="square", org_id=org, actor_id=str(uuid4()), idempotency_key="render-1",
        created_at=_fixture.NOW,
    )
    assert first == replay
    job = first["render_job"]
    schema = __import__("json").loads((ROOT / "packages/contracts/jsonschema/render-job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(job)
    assert job["media_script_version_id"] == script["id"]
    assert job["input_snapshot_hashes"]["visual_asset_set"] == visual["snapshot_hash"]
    assert job["output_profile"]["profile_key"] == "square"
    assert len(service.store.jobs) == 1


def test_create_rejects_reused_key_lineage_and_profile_requirements() -> None:
    service, _, org, actor, script, visual, output, _ = _service()
    service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                              profile_key="square", org_id=org, actor_id=actor, idempotency_key="same")
    replay = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                       profile_key="square", org_id=org, actor_id=actor, idempotency_key="same",
                                       trace_id="different")
    assert replay["render_job"]["id"] == next(iter(service.store.jobs))
    changed_output = deepcopy(output)
    changed_output["profiles"] = [dict(output["profiles"][0], profile_key="square-alt")]
    changed_output["snapshot_hash"] = "f" * 64
    with pytest.raises(MediaRenderError) as reused:
        service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=changed_output,
                                  profile_key="square-alt", org_id=org, actor_id=actor, idempotency_key="same")
    assert reused.value.code in {"IDEMPOTENCY_KEY_REUSED", "SOURCE_LINEAGE_MISMATCH"}
    changed = deepcopy(script)
    changed["snapshot_hash"] = "f" * 64
    with pytest.raises(MediaRenderError) as lineage:
        service.create_render_job(script_version=changed, visual_asset_set_version=visual, output_spec_version=output,
                                  profile_key="square", org_id=org, actor_id=actor, idempotency_key="lineage")
    assert lineage.value.code == "SOURCE_LINEAGE_MISMATCH"
    with pytest.raises(MediaRenderError) as profile:
        service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                  profile_key="portrait", org_id=org, actor_id=actor, idempotency_key="profile")
    assert profile.value.code == "OUTPUT_PROFILE_NOT_FOUND"


def test_execute_confirms_private_artifact_and_does_not_rerender_replay() -> None:
    service, renderer, org, actor, script, visual, output, _ = _service()
    created = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                        profile_key="square", org_id=org, actor_id=actor, idempotency_key="execute")
    result = service.execute_render_job(media_render_job_id=created["render_job"]["id"], org_id=org, actor_id=actor)
    assert result["render_job"]["status"] == "succeeded"
    artifact = result["artifacts"][0]
    assert artifact["storage_object_ref"].startswith("private://")
    assert artifact["content_hash"]
    assert artifact["size_bytes"] == len(b"rendered-bytes")
    assert artifact["input_hash"] == created["render_job"]["input_hash"]
    assert service.outbox_events[0]["event_type"] == "asset.render_started"
    assert len(renderer.calls) == 1
    replay = service.execute_render_job(media_render_job_id=created["render_job"]["id"], org_id=org, actor_id=actor)
    assert replay == result
    assert len(renderer.calls) == 1


def test_target_asset_version_is_locked_and_cross_tenant_is_rejected() -> None:
    org, actor, script, visual, output, assets = _source(profile="landscape")
    service = MediaRenderService()
    created = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                        profile_key="landscape", asset_version=assets[2], org_id=org, actor_id=actor,
                                        idempotency_key="target")
    assert created["render_job"]["asset_version_no"] == 1
    assert created["render_job"]["input_snapshot_hashes"]["asset_version"] == assets[2]["file_hash"]
    foreign = deepcopy(assets[2]); foreign["org_id"] = str(uuid4())
    with pytest.raises(MediaRenderError) as error:
        service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                  profile_key="landscape", asset_version=foreign, org_id=org, actor_id=actor,
                                  idempotency_key="foreign")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_unknown_renderer_result_marks_job_unknown() -> None:
    service, _, org, actor, script, visual, output, _ = _service()

    class UnknownRenderer:
        def render(self, *_args, **_kwargs):
            raise RuntimeError("external renderer unavailable")

    service.renderer = UnknownRenderer()
    created = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                        profile_key="square", org_id=org, actor_id=actor, idempotency_key="unknown")
    with pytest.raises(MediaRenderError) as error:
        service.execute_render_job(media_render_job_id=created["render_job"]["id"], org_id=org, actor_id=actor)
    assert error.value.code == "RENDER_RESULT_UNKNOWN"
    assert service.get_job(media_render_job_id=created["render_job"]["id"], org_id=org)["status"] == "unknown"


def test_concurrent_workers_atomically_claim_once() -> None:
    service, _, org, actor, script, visual, output, _ = _service()

    class SlowRenderer(FakeRenderer):
        def render(self, job, *, profile):
            time.sleep(0.03)
            return super().render(job, profile=profile)

    renderer = SlowRenderer(content=b"once")
    service.renderer = renderer
    created = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                        profile_key="square", org_id=org, actor_id=actor, idempotency_key="parallel")
    results, errors = [], []

    def worker():
        try:
            results.append(service.execute_render_job(media_render_job_id=created["render_job"]["id"], org_id=org, actor_id=actor))
        except MediaRenderError as error:
            errors.append(error.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(renderer.calls) == 1
    assert len(results) == 1
    assert errors == ["RENDER_JOB_IN_PROGRESS"]
