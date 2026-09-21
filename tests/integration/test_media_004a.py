from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from modules.media import MediaOutputSpecService, MediaRenderError, MediaRenderService


_SPEC = importlib.util.spec_from_file_location("render_output_fixture", Path(__file__).resolve().parents[1] / "unit/media/test_media_output_spec_service.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


class _Port:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def get_version(self, *, org_id, version_id):
        self.calls.append((org_id, version_id))
        if version_id != self.value["id"]:
            raise KeyError(version_id)
        return self.value


class _Task:
    def __init__(self, job_id, org_id):
        self.aggregate_id = job_id
        self.org_id = org_id
        self.trace_id = "worker-trace"


class _Context:
    def __init__(self):
        self.count = 0

    def checkpoint(self):
        self.count += 1


def test_exact_ports_and_worker_handler_execute_locked_job() -> None:
    org, actor, script, visual = _FIXTURE.source()
    output = MediaOutputSpecService().create_output_spec(
        visual, profiles=[{"aspect_ratio": "1:1"}], org_id=org, actor_id=actor, idempotency_key="output",
    )["version"]
    ports = {
        "script_port": _Port(script), "visual_port": _Port(visual), "output_port": _Port(output),
    }
    service = MediaRenderService(**ports)
    created = service.create_render_job(
        media_script_version_id=script["id"], media_visual_asset_set_version_id=visual["id"],
        media_output_spec_version_id=output["id"], profile_key="square", org_id=org, actor_id=actor,
        idempotency_key="worker-create",
    )
    context = _Context()
    service.worker_handler(_Task(created["render_job"]["id"], org), context)
    assert service.get_job(media_render_job_id=created["render_job"]["id"], org_id=org)["status"] == "succeeded"
    assert context.count == 2
    assert ports["script_port"].calls == [(org, script["id"])]
    assert ports["visual_port"].calls == [(org, visual["id"])]
    assert ports["output_port"].calls == [(org, output["id"])]


def test_current_pointer_changes_do_not_change_job_snapshot() -> None:
    org, actor, script, visual = _FIXTURE.source()
    output = MediaOutputSpecService().create_output_spec(
        visual, profiles=[{"aspect_ratio": "1:1"}], org_id=org, actor_id=actor, idempotency_key="output",
    )["version"]
    service = MediaRenderService()
    created = service.create_render_job(script_version=script, visual_asset_set_version=visual, output_spec_version=output,
                                        profile_key="square", org_id=org, actor_id=actor, idempotency_key="lock")
    changed_visual = deepcopy(visual)
    changed_visual["snapshot_hash"] = "f" * 64
    with pytest.raises(MediaRenderError) as error:
        service.create_render_job(script_version=script, visual_asset_set_version=changed_visual, output_spec_version=output,
                                  profile_key="square", org_id=org, actor_id=actor, idempotency_key="changed")
    assert error.value.code == "SOURCE_LINEAGE_MISMATCH"
    assert service.get_job(media_render_job_id=created["render_job"]["id"], org_id=org)["input_snapshot_hashes"]["visual_asset_set"] == visual["snapshot_hash"]
