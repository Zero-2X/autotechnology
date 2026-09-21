import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest

from modules.media import MediaOutputSpecError, MediaOutputSpecService


_spec = importlib.util.spec_from_file_location("output_fixture", Path(__file__).resolve().parents[1] / "unit/media/test_media_output_spec_service.py")
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def test_exact_visual_port_and_wrong_version_rejection():
    org, actor, _, visual = _fixture.source()
    calls = []

    class Port:
        def get_version(self, *, org_id, version_id):
            calls.append((org_id, version_id))
            return visual

    service = MediaOutputSpecService(visual_port=Port())
    result = service.create_output_spec(media_visual_asset_set_version_id=visual["id"],
                                       profiles=[{"aspect_ratio": "16:9"}], org_id=org, actor_id=actor, idempotency_key="port")
    assert result["version"]["source_visual_snapshot_hash"] == visual["snapshot_hash"]
    assert calls == [(org, visual["id"])]
    with pytest.raises(MediaOutputSpecError) as wrong:
        service.create_output_spec(media_visual_asset_set_version_id=str(uuid4()),
                                   profiles=[{"aspect_ratio": "16:9"}], org_id=org, actor_id=actor, idempotency_key="wrong")
    assert wrong.value.code == "VISUAL_ASSET_VERSION_NOT_FOUND"
