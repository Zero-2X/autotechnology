from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.media import MediaScriptService, MediaVisualAssetError, MediaVisualAssetSetService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[3]


def _script() -> tuple[str, str, dict]:
    org, actor = str(uuid4()), str(uuid4())
    variant = {
        "id": str(uuid4()), "org_id": org, "content_variant_id": str(uuid4()), "canonical_content_version_id": str(uuid4()),
        "version_no": 1, "locale": "en-US", "market": "US", "audience": "engineers", "tone": "neutral",
        "region_profile_version_id": str(uuid4()), "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "intro", "localized_text": "A verified visual source.", "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": str(uuid4()),
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
    }
    claim = {
        "id": str(uuid4()), "org_id": org, "entity_ids": [], "statement": "A verified visual source.", "fact_type": "product.fact",
        "applicable_versions": [variant["canonical_content_version_id"]], "applicable_regions": [], "applicable_locales": ["en-US"],
        "valid_from": None, "valid_to": None, "review_due_at": None, "supersedes_claim_id": None,
        "freshness_status": "fresh", "status": "verified", "version": 1, "content_hash": "b" * 64,
        "created_by": actor, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }
    result = MediaScriptService(clock=lambda: NOW).create_script(
        variant, duration_seconds=30, claims=[claim], source_map=[{"block_id": "intro", "claim_id": claim["id"]}],
        org_id=org, actor_id=actor, idempotency_key="script", created_at=NOW,
    )
    return org, actor, result["version"]


def _rights(org: str, actor: str, *, status: str = "verified", media: list[str] | None = None) -> dict:
    return {
        "id": str(uuid4()), "org_id": org, "rights_record_id": str(uuid4()), "version_no": 1,
        "source_snapshot_ids": [str(uuid4())], "license_ref": "license://fixture", "contract_ref": None,
        "evidence_object_refs": ["private://evidence/1"], "terms_snapshot_hash": "c" * 64,
        "rights_holder": "Fixture holder", "permitted_regions": ["US"], "permitted_locales": ["en-US"],
        "permitted_media": media or ["image", "video", "thumbnail"], "permitted_use": "commercial",
        "valid_from": "2026-01-01T00:00:00Z", "valid_to": "2027-01-01T00:00:00Z", "status": status,
        "policy_rule_version": "rights-v1", "verified_by": actor, "verified_at": "2026-01-01T00:00:00Z",
        "verification_reason": "reviewed", "supersedes_version_id": None, "snapshot_hash": "d" * 64,
        "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
    }


def _asset(script: dict, org: str, actor: str, media_type: str, rights_id: str) -> dict:
    return {
        "id": str(uuid4()), "org_id": org, "asset_id": str(uuid4()), "variant_version_id": script["variant_version_id"],
        "version_no": 1, "media_type": media_type, "format": "png" if media_type != "video" else "mp4",
        "aspect_ratio": "16:9", "storage_object_ref": f"private://asset/{uuid4()}", "file_hash": "e" * 64,
        "rights_snapshot_ids": [rights_id], "region_profile_version_id": script["region_profile_version_id"],
        "policy_snapshot_id": script["policy_snapshot_id"], "status": "approved", "created_by": actor,
        "created_at": "2026-01-01T00:00:00Z",
    }


def _fixture() -> tuple[MediaVisualAssetSetService, str, str, dict, list[dict], list[dict]]:
    org, actor, script = _script()
    rights = [_rights(org, actor), _rights(org, actor), _rights(org, actor)]
    assets = [_asset(script, org, actor, "image", rights[0]["id"]), _asset(script, org, actor, "thumbnail", rights[1]["id"]), _asset(script, org, actor, "video", rights[2]["id"])]
    return MediaVisualAssetSetService(clock=lambda: NOW), org, actor, script, assets, rights


def _items(assets: list[dict], rights: list[dict]) -> list[dict]:
    return [
        {"sequence": 1, "role": "cover", "asset_version_id": assets[0]["id"], "timestamp_ms": None, "alt_text": "Cover image", "rights_record_version_ids": [rights[0]["id"]]},
        {"sequence": 2, "role": "thumbnail", "asset_version_id": assets[1]["id"], "timestamp_ms": None, "alt_text": "Thumbnail image", "rights_record_version_ids": [rights[1]["id"]]},
        {"sequence": 3, "role": "keyframe", "asset_version_id": assets[2]["id"], "timestamp_ms": 12000, "alt_text": "Evidence keyframe", "rights_record_version_ids": [rights[2]["id"]]},
    ]


def test_visual_set_is_contract_valid_and_order_independent() -> None:
    service, org, actor, script, assets, rights = _fixture()
    first = service.create_asset_set(script, items=_items(assets, rights), asset_versions=assets, rights_versions=rights,
                                     org_id=org, actor_id=actor, idempotency_key="set-1", created_at=NOW)
    reordered = [dict(item) for item in reversed(_items(assets, rights))]
    second = MediaVisualAssetSetService(clock=lambda: NOW).create_asset_set(
        script, items=reordered, asset_versions=list(reversed(assets)), rights_versions=list(reversed(rights)),
        org_id=org, actor_id=str(uuid4()), idempotency_key="set-2", created_at=NOW,
    )
    schema = json.loads((ROOT / "packages/contracts/jsonschema/media-visual-asset-set-version.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first["version"])
    assert first["version"]["snapshot_hash"] == second["version"]["snapshot_hash"]
    assert first["version"]["item_count"] == 3
    assert "token" not in json.dumps(first).lower()


def test_visual_lineage_role_rights_and_cover_gates_fail_closed() -> None:
    service, org, actor, script, assets, rights = _fixture()
    no_cover = _items(assets, rights)
    no_cover[0]["role"] = "keyframe"
    no_cover[0]["timestamp_ms"] = 1000
    no_cover[1]["role"] = "keyframe"
    no_cover[1]["timestamp_ms"] = 2000
    with pytest.raises(MediaVisualAssetError) as cover:
        service.create_asset_set(script, items=no_cover, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="no-cover", created_at=NOW)
    assert cover.value.code == "COVER_REQUIRED"
    out_of_range = _items(assets, rights)
    out_of_range[2]["timestamp_ms"] = 30000
    with pytest.raises(MediaVisualAssetError) as keyframe:
        service.create_asset_set(script, items=out_of_range, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="keyframe", created_at=NOW)
    assert keyframe.value.code == "KEYFRAME_TIME_INVALID"
    expired = deepcopy(rights[0]); expired["status"] = "expired"
    with pytest.raises(MediaVisualAssetError) as rights_error:
        service.create_asset_set(script, items=_items(assets, rights), asset_versions=assets, rights_versions=[expired, *rights[1:]], org_id=org, actor_id=actor, idempotency_key="expired", created_at=NOW)
    assert rights_error.value.code == "RIGHTS_NOT_VERIFIED"
    foreign_script = deepcopy(script); foreign_script["variant_version_id"] = str(uuid4())
    with pytest.raises(MediaVisualAssetError) as lineage:
        service.create_asset_set(foreign_script, items=_items(assets, rights), asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="lineage", created_at=NOW)
    assert lineage.value.code == "ASSET_LINEAGE_MISMATCH"


def test_idempotency_revision_and_previous_version_immutability() -> None:
    service, org, actor, script, assets, rights = _fixture()
    items = _items(assets, rights)
    first = service.create_asset_set(script, items=items, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="same", created_at=NOW)
    replay = service.create_asset_set(script, items=list(reversed(items)), asset_versions=assets, rights_versions=rights, org_id=org, actor_id=str(uuid4()), idempotency_key="same", created_at=NOW)
    assert replay == first
    changed = deepcopy(items); changed[0]["alt_text"] = "Human edited cover"
    revised = service.revise_asset_set(media_visual_asset_set_id=first["media_visual_asset_set"]["id"], expected_version_no=1,
                                       items=changed, asset_versions=assets, rights_versions=rights, script_version=script,
                                       revision_reason="review", org_id=org, actor_id=actor, idempotency_key="edit", revised_at=NOW)
    assert revised["version"]["version_no"] == 2
    assert service.get_version(org_id=org, version_id=first["version"]["id"]) == first["version"]
    with pytest.raises(MediaVisualAssetError) as conflict:
        service.revise_asset_set(media_visual_asset_set_id=first["media_visual_asset_set"]["id"], expected_version_no=1,
                                 items=changed, asset_versions=assets, rights_versions=rights, script_version=script,
                                 revision_reason="race", org_id=org, actor_id=actor, idempotency_key="race", revised_at=NOW)
    assert conflict.value.code == "VERSION_CONFLICT"
