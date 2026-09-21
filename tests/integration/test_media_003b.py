from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.media import MediaVisualAssetError, MediaVisualAssetSetService


ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
_SPEC = importlib.util.spec_from_file_location("media_003b_unit_fixture", ROOT / "tests/unit/media/test_media_visual_asset_service.py")
assert _SPEC and _SPEC.loader
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


def test_storyboard_optional_source_and_exact_asset_rights_ports() -> None:
    service, org, actor, script, assets, rights = _FIXTURE._fixture()
    class AssetPort:
        def __init__(self): self.calls = []
        def get_version(self, *, org_id: str, version_id: str):
            self.calls.append((org_id, version_id))
            return next(item for item in assets if item["id"] == version_id)
    class RightsPort:
        def get_version(self, *, org_id: str, version_id: str):
            return next(item for item in rights if item["id"] == version_id)
    port = AssetPort()
    service = MediaVisualAssetSetService(asset_port=port, rights_port=RightsPort(), clock=lambda: NOW)
    result = service.create_asset_set(
        script, items=_FIXTURE._items(assets, rights), org_id=org, actor_id=actor,
        idempotency_key="ports", created_at=NOW,
    )
    assert result["version"]["item_count"] == 3
    assert len(port.calls) == 3


def test_cross_tenant_and_missing_rights_fail_closed() -> None:
    service, org, actor, script, assets, rights = _FIXTURE._fixture()
    with pytest.raises(MediaVisualAssetError) as foreign:
        service.create_asset_set(script, items=_FIXTURE._items(assets, rights), asset_versions=assets, rights_versions=rights,
                                 org_id=str(uuid4()), actor_id=actor, idempotency_key="foreign", created_at=NOW)
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"
    items = deepcopy(_FIXTURE._items(assets, rights))
    items[0]["rights_record_version_ids"] = []
    with pytest.raises(MediaVisualAssetError) as missing:
        service.create_asset_set(script, items=items, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor,
                                 idempotency_key="missing", created_at=NOW)
    assert missing.value.code == "RIGHTS_REFERENCE_REQUIRED"
