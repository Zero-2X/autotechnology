from copy import deepcopy
import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from modules.media import MediaOutputSpecError, MediaOutputSpecService


_spec = importlib.util.spec_from_file_location("output_visual_fixture", Path(__file__).with_name("test_media_visual_asset_service.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def source():
    service, org, actor, script, assets, rights = _fixture._fixture()
    visual = service.create_asset_set(script, items=_fixture._items(assets, rights), asset_versions=assets,
                                      rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="source",
                                      created_at=_fixture.NOW)["version"]
    return org, actor, script, visual


def test_three_ratios_defaults_and_reordering():
    org, actor, script, visual = source()
    service = MediaOutputSpecService()
    profiles = [{"aspect_ratio": ratio} for ratio in ("16:9", "1:1", "9:16")]
    first = service.create_output_spec(visual, script_version=script, profiles=profiles, require_all_ratios=True,
                                       org_id=org, actor_id=actor, idempotency_key="create")
    replay = service.create_output_spec(visual, profiles=list(reversed(profiles)), require_all_ratios=True,
                                        org_id=org, actor_id=actor, idempotency_key="create")
    assert first == replay
    assert [(p["width"], p["height"]) for p in first["version"]["profiles"]] == [(1080, 1920), (1080, 1080), (1920, 1080)]


@pytest.mark.parametrize("profile,code", [
    ({"aspect_ratio": []}, "OUTPUT_RATIO_INVALID"),
    ({"aspect_ratio": "9:16", "width": 1920, "height": 1080}, "OUTPUT_DIMENSIONS_INVALID"),
    ({"aspect_ratio": "1:1", "width": True}, "OUTPUT_DIMENSIONS_INVALID"),
    ({"aspect_ratio": "1:1", "frame_rate": float("nan")}, "OUTPUT_FRAME_RATE_INVALID"),
    ({"aspect_ratio": "1:1", "unknown_option": 1}, "OUTPUT_PROFILE_INVALID"),
    ({"aspect_ratio": "1:1", "token": "must-not-be-logged"}, "SENSITIVE_INPUT_REJECTED"),
])
def test_invalid_profile_rejected(profile, code):
    with pytest.raises(MediaOutputSpecError) as error:
        MediaOutputSpecService().validate_profiles([profile])
    assert error.value.code == code


def test_revision_retry_after_success_and_stale_writer():
    org, actor, _, visual = source()
    service = MediaOutputSpecService()
    first = service.create_output_spec(visual, profiles=[{"aspect_ratio": "1:1"}], org_id=org, actor_id=actor, idempotency_key="create")
    kwargs = dict(media_output_spec_id=first["media_output_spec"]["id"], expected_version_no=1,
                  profiles=[{"aspect_ratio": "9:16"}], visual_asset_set_version=visual, revision_reason="portrait",
                  org_id=org, actor_id=actor, idempotency_key="revise")
    second = service.revise_output_spec(**kwargs)
    assert service.revise_output_spec(**kwargs) == second
    assert service.get_version(org_id=org, version_id=first["version"]["id"]) == first["version"]
    with pytest.raises(MediaOutputSpecError) as stale:
        service.revise_output_spec(**{**kwargs, "idempotency_key": "stale"})
    assert stale.value.code == "VERSION_CONFLICT"


def test_source_tenant_and_snapshot_rejected():
    org, actor, script, visual = source()
    service = MediaOutputSpecService()
    with pytest.raises(MediaOutputSpecError) as foreign:
        service.create_output_spec(visual, profiles=[{"aspect_ratio": "1:1"}], org_id=str(uuid4()), actor_id=actor, idempotency_key="foreign")
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"
    changed = deepcopy(script)
    changed["snapshot_hash"] = "0" * 64
    with pytest.raises(MediaOutputSpecError) as mismatch:
        service.create_output_spec(visual, script_version=changed, profiles=[{"aspect_ratio": "1:1"}], org_id=org, actor_id=actor, idempotency_key="mismatch")
    assert mismatch.value.code == "SOURCE_SNAPSHOT_MISMATCH"
