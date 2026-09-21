from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from modules.media import MediaAssetLineageError, MediaAssetLineageService


def _fixture():
    org, actor, variant_id, asset_id, root_id, canonical_id, claim_id, rights_id = (str(uuid4()) for _ in range(8))
    variant = {"id": variant_id, "org_id": org, "version_no": 2, "status": "approved", "snapshot_hash": "a" * 64,
               "canonical_content_version_id": canonical_id, "market": "US", "locale": "en-US"}
    claim = {"id": claim_id, "org_id": org, "status": "verified", "freshness_status": "fresh", "applicable_versions": [canonical_id], "content_hash": "b" * 64}
    rights = {"id": rights_id, "org_id": org, "status": "verified", "valid_from": None, "valid_to": None,
              "permitted_regions": ["US"], "permitted_locales": ["en-US"], "permitted_media": ["video"], "permitted_use": "commercial", "snapshot_hash": "c" * 64}
    asset = {"id": asset_id, "org_id": org, "asset_id": root_id, "variant_version_id": variant_id, "version_no": 1,
             "media_type": "video", "format": "mp4", "aspect_ratio": "16:9", "storage_object_ref": "private://asset/file",
             "file_hash": "d" * 64, "rights_snapshot_ids": [rights_id], "region_profile_version_id": str(uuid4()),
             "policy_snapshot_id": str(uuid4()), "status": "planned", "created_by": actor, "created_at": "2026-09-20T12:00:00Z"}
    return org, actor, asset, variant, claim, rights


def test_asset_lineage_captures_variant_claim_and_rights_snapshots() -> None:
    org, actor, asset, variant, claim, rights = _fixture()
    service = MediaAssetLineageService()
    result = service.create_asset_version(asset_version=asset, variant_version=variant, claims=[claim], rights_versions=[rights],
                                          org_id=org, actor_id=actor, market="US", locale="en-US", idempotency_key="lineage",
                                          created_at="2026-09-20T12:00:00Z")
    assert result["lineage"]["status"] == "valid"
    lineage = result["lineage"]
    assert result["asset_version"] == asset
    assert lineage["variant_version"]["snapshot_hash"] == variant["snapshot_hash"]
    assert lineage["claims"][0]["snapshot_hash"] == claim["content_hash"]
    assert lineage["rights_record_versions"][0]["snapshot_hash"] == rights["snapshot_hash"]
    assert {edge["lineage_type"] for edge in result["edges"]} == {"variant", "claim", "rights"}
    assert len(service.store.edges) == 3
    assert service.outbox_events[0]["event_type"] == "asset.created"


def test_asset_lineage_blocks_variant_or_claim_and_withdraws_bad_rights() -> None:
    org, actor, asset, variant, claim, rights = _fixture()
    service = MediaAssetLineageService()
    blocked_variant = {**variant, "status": "withdrawn"}
    decision = service.check_lineage(asset_version=asset, variant_version=blocked_variant, claims=[claim], rights_versions=[rights], org_id=org, market="US", locale="en-US")
    assert decision["status"] == "blocked"
    stale_claim = {**claim, "freshness_status": "stale"}
    decision = service.check_lineage(asset_version=asset, variant_version=variant, claims=[stale_claim], rights_versions=[rights], org_id=org, market="US", locale="en-US")
    assert decision["status"] == "blocked"
    withdrawn_rights = {**rights, "status": "withdrawn"}
    decision = service.check_lineage(asset_version=asset, variant_version=variant, claims=[claim], rights_versions=[withdrawn_rights], org_id=org, market="US", locale="en-US")
    assert decision["status"] == "withdrawn"
    propagated = service.propagate_dependency_change(asset_version=asset, variant_version=variant, claims=[claim], rights_versions=[withdrawn_rights], org_id=org, market="US", locale="en-US")
    assert propagated["asset_version"]["status"] == "withdrawn"
    assert asset["status"] == "planned"


def test_asset_lineage_is_idempotent_and_rejects_tenant_or_snapshot_conflicts() -> None:
    org, actor, asset, variant, claim, rights = _fixture()
    service = MediaAssetLineageService()
    args = dict(asset_version=asset, variant_version=variant, claims=[claim], rights_versions=[rights], org_id=org, actor_id=actor,
                market="US", locale="en-US", idempotency_key="same", created_at="2026-09-20T12:00:00Z")
    first = service.create_asset_version(**args)
    assert service.create_asset_version(**args) == first
    with pytest.raises(MediaAssetLineageError) as reused:
        service.create_asset_version(**{**args, "idempotency_key": "same", "market": "GB"})
    assert reused.value.code == "IDEMPOTENCY_KEY_REUSED"
    foreign = {**rights, "org_id": str(uuid4())}
    with pytest.raises(MediaAssetLineageError) as scope:
        service.create_asset_version(**{**args, "rights_versions": [foreign], "idempotency_key": "foreign"})
    assert scope.value.code == "TENANT_SCOPE_VIOLATION"
    changed = deepcopy(variant); changed["snapshot_hash"] = "f" * 64
    mismatch = service.check_lineage(asset_version=first["asset_version"], variant_version=changed, claims=[claim], rights_versions=[rights], lineage=first["lineage"], org_id=org)
    assert mismatch["status"] == "blocked"
    assert "variant_snapshot_changed" in mismatch["reasons"]


def test_withdraw_appends_status_projection_without_rewriting_version() -> None:
    org, actor, asset, variant, claim, rights = _fixture()
    service = MediaAssetLineageService()
    created = service.create_asset_version(
        asset_version=asset, variant_version=variant, claims=[claim], rights_versions=[rights],
        org_id=org, actor_id=actor, market="US", locale="en-US", idempotency_key="create-before-withdraw",
        created_at="2026-09-20T12:00:00Z",
    )
    immutable = deepcopy(service.store.versions[(org, asset["id"])])
    withdrawn = service.withdraw(asset_version=created["asset_version"], reason="rights revoked", org_id=org,
                                   actor_id=actor, idempotency_key="withdraw")
    assert withdrawn["asset_version"]["status"] == "withdrawn"
    assert service.store.versions[(org, asset["id"])] == immutable
    assert service.store.status_projections[(org, asset["id"])]["status"] == "withdrawn"
    assert service.outbox_events[-1]["event_type"] == "asset.withdrawn"
