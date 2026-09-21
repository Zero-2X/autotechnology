from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.media import MediaScriptService, MediaStoryboardError, MediaStoryboardService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[3]


def _script(duration: int = 30) -> tuple[str, str, dict, dict]:
    org, actor = str(uuid4()), str(uuid4())
    variant_id, canonical_id, region_id, policy_id, claim_id = (str(uuid4()) for _ in range(5))
    variant = {
        "id": variant_id, "org_id": org, "content_variant_id": str(uuid4()),
        "canonical_content_version_id": canonical_id, "version_no": 1, "locale": "en-US",
        "market": "US", "audience": "engineers", "tone": "neutral",
        "region_profile_version_id": region_id, "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "intro", "localized_text": "A verified fact is available.", "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": policy_id,
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor,
        "created_at": "2026-09-19T00:00:00Z",
    }
    claim = {
        "id": claim_id, "org_id": org, "entity_ids": [], "statement": "A verified fact is available.",
        "fact_type": "product.fact", "applicable_versions": [canonical_id], "applicable_regions": [],
        "applicable_locales": ["en-US"], "valid_from": None, "valid_to": None, "review_due_at": None,
        "supersedes_claim_id": None, "freshness_status": "fresh", "status": "verified", "version": 1,
        "content_hash": "b" * 64, "created_by": actor, "created_at": "2026-09-19T00:00:00Z",
        "updated_at": "2026-09-19T00:00:00Z",
    }
    result = MediaScriptService(clock=lambda: NOW).create_script(
        variant, duration_seconds=duration, claims=[claim],
        source_map=[{"block_id": "intro", "claim_id": claim_id}],
        org_id=org, actor_id=actor, idempotency_key=f"script-{duration}", created_at=NOW,
    )
    return org, actor, result["version"], variant


def _rights(org: str, actor: str, *, media: list[str] | None = None, status: str = "verified") -> dict:
    return {
        "id": str(uuid4()), "org_id": org, "rights_record_id": str(uuid4()), "version_no": 1,
        "source_snapshot_ids": [str(uuid4())], "license_ref": "license://fixture", "contract_ref": None,
        "evidence_object_refs": ["private://evidence/1"], "terms_snapshot_hash": "c" * 64,
        "rights_holder": "Fixture holder", "permitted_regions": ["US"], "permitted_locales": ["en-US"],
        "permitted_media": media or ["image", "audio", "document"], "permitted_use": "commercial",
        "valid_from": "2026-01-01T00:00:00Z", "valid_to": "2027-01-01T00:00:00Z",
        "status": status, "policy_rule_version": "rights-v1", "verified_by": actor,
        "verified_at": "2026-01-01T00:00:00Z", "verification_reason": "reviewed",
        "supersedes_version_id": None, "snapshot_hash": "d" * 64, "created_by": actor,
        "created_at": "2026-01-01T00:00:00Z",
    }


def _assets(script: dict, org: str, actor: str) -> tuple[list[dict], list[dict]]:
    values: list[dict] = []
    rights: list[dict] = []
    for media_type, role_media in (("image", ["image"]), ("audio", ["audio"]), ("document", ["document"]), ("audio", ["audio"])):
        right = _rights(org, actor, media=role_media)
        rights.append(right)
        values.append({
            "id": str(uuid4()), "org_id": org, "asset_id": str(uuid4()),
            "variant_version_id": script["variant_version_id"], "version_no": 1,
            "media_type": media_type, "format": "png" if media_type == "image" else ("woff2" if media_type == "document" else "wav"),
            "aspect_ratio": "9:16" if media_type == "image" else None,
            "storage_object_ref": f"private://asset/{uuid4()}", "file_hash": ("e" * 64),
            "rights_snapshot_ids": [right["id"]], "region_profile_version_id": script["region_profile_version_id"],
            "policy_snapshot_id": script["policy_snapshot_id"], "status": "approved", "created_by": actor,
            "created_at": "2026-09-19T00:00:00Z",
        })
    return values, rights


def _shots(script: dict, assets: list[dict], rights: list[dict]) -> list[dict]:
    roles = ["visual", "music", "font", "voiceover"]
    return [
        {"sequence": 1, "script_segment_sequence": 1, "start_ms": 0, "end_ms": 4000,
         "purpose": "Open with the verified point.", "transition": "cut",
         "asset_refs": [{"role": roles[0], "asset_version_id": assets[0]["id"], "rights_record_version_ids": [rights[0]["id"]]}]},
        {"sequence": 2, "script_segment_sequence": 2, "start_ms": 4000, "end_ms": 26000,
         "purpose": "Explain the evidence and context.", "transition": "dissolve",
         "asset_refs": [
             {"role": roles[1], "asset_version_id": assets[1]["id"], "rights_record_version_ids": [rights[1]["id"]]},
             {"role": roles[2], "asset_version_id": assets[2]["id"], "rights_record_version_ids": [rights[2]["id"]]},
         ]},
        {"sequence": 3, "script_segment_sequence": 3, "start_ms": 26000, "end_ms": 30000,
         "purpose": "Close with the next action.", "transition": "fade",
         "asset_refs": [{"role": roles[3], "asset_version_id": assets[3]["id"], "rights_record_version_ids": [rights[3]["id"]]}]},
    ]


def _service_fixture() -> tuple[MediaStoryboardService, dict, list[dict], list[dict], str, str]:
    org, actor, script, _variant = _script()
    assets, rights = _assets(script, org, actor)
    return MediaStoryboardService(clock=lambda: NOW), script, assets, rights, org, actor


def test_create_output_is_contract_valid_and_order_independent() -> None:
    service, script, assets, rights, org, actor = _service_fixture()
    first = service.create_storyboard(
        script, media_script_version_id=script["id"], shots=_shots(script, assets, rights),
        asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor,
        idempotency_key="storyboard-1", created_at=NOW,
    )
    # Change shot, asset and reference array order while preserving semantics.
    reordered = [dict(item, asset_refs=list(reversed(item["asset_refs"]))) for item in reversed(_shots(script, assets, rights))]
    second_service = MediaStoryboardService(clock=lambda: NOW)
    second = second_service.create_storyboard(
        script, media_script_version_id=script["id"], shots=reordered,
        asset_versions=list(reversed(assets)), rights_versions=list(reversed(rights)), org_id=org,
        actor_id=str(uuid4()), idempotency_key="storyboard-2", created_at=datetime(2026, 9, 20, 12, 1, tzinfo=timezone.utc),
    )
    schema = json.loads((ROOT / "packages/contracts/jsonschema/media-storyboard-version.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first["version"])
    assert first["version"]["snapshot_hash"] == second["version"]["snapshot_hash"]
    assert first["version"]["asset_reference_count"] == 4
    assert first["media_storyboard"]["duration_seconds"] == 30
    assert "private://" in json.dumps(first)
    assert "model" not in json.dumps(first).lower()


def test_text_only_storyboard_and_idempotent_replay() -> None:
    service, script, _assets_value, _rights_value, org, actor = _service_fixture()
    shots = [{
        "sequence": 1, "script_segment_sequence": 1, "start_ms": 0, "end_ms": 4000,
        "purpose": "Text only opening.", "transition": "none", "asset_refs": [],
    }, {
        "sequence": 2, "script_segment_sequence": 2, "start_ms": 4000, "end_ms": 26000,
        "purpose": "Text only body.", "transition": "none", "asset_refs": [],
    }, {
        "sequence": 3, "script_segment_sequence": 3, "start_ms": 26000, "end_ms": 30000,
        "purpose": "Text only close.", "transition": "none", "asset_refs": [],
    }]
    first = service.create_storyboard(script, shots=shots, org_id=org, actor_id=actor, idempotency_key="text", created_at=NOW)
    replay = service.create_storyboard(script, shots=shots, org_id=org, actor_id=str(uuid4()), idempotency_key="text", created_at=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert first == replay
    assert first["version"]["asset_reference_count"] == 0
    assert first["version"]["rights_snapshot_ids"] == []


def test_timeline_and_role_rights_gates_fail_closed() -> None:
    service, script, assets, rights, org, actor = _service_fixture()
    shots = _shots(script, assets, rights)
    bad_gap = deepcopy(shots)
    bad_gap[1]["start_ms"] = 4500
    with pytest.raises(MediaStoryboardError) as gap:
        service.create_storyboard(script, shots=bad_gap, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="gap", created_at=NOW)
    assert gap.value.code == "SHOT_TIMELINE_INVALID"
    bad_role = deepcopy(shots)
    bad_role[0]["asset_refs"][0]["role"] = "music"
    with pytest.raises(MediaStoryboardError) as role:
        service.create_storyboard(script, shots=bad_role, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="role", created_at=NOW)
    assert role.value.code == "ASSET_ROLE_MISMATCH"
    expired = deepcopy(rights[0]); expired["status"] = "expired"
    with pytest.raises(MediaStoryboardError) as rights_error:
        service.create_storyboard(script, shots=shots, asset_versions=assets, rights_versions=[expired, *rights[1:]], org_id=org, actor_id=actor, idempotency_key="expired", created_at=NOW)
    assert rights_error.value.code == "RIGHTS_NOT_VERIFIED"


def test_tenant_lineage_and_idempotent_conflict_are_audited() -> None:
    service, script, assets, rights, org, actor = _service_fixture()
    shots = _shots(script, assets, rights)
    with pytest.raises(MediaStoryboardError) as tenant:
        service.create_storyboard(script, shots=shots, asset_versions=assets, rights_versions=rights, org_id=str(uuid4()), actor_id=actor, idempotency_key="foreign", created_at=NOW)
    assert tenant.value.code == "TENANT_SCOPE_VIOLATION"
    first = service.create_storyboard(script, shots=shots, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="conflict", created_at=NOW)
    conflicting = deepcopy(shots)
    conflicting[0]["purpose"] = "A different purpose changes the request."
    with pytest.raises(MediaStoryboardError) as conflict:
        service.create_storyboard(script, shots=conflicting, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="conflict", created_at=NOW)
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"
    assert first["media_storyboard"]["id"]
    assert service.audit_log[-1]["error_code"] == "IDEMPOTENCY_KEY_REUSED"


def test_revision_is_optimistic_and_keeps_previous_version_immutable() -> None:
    service, script, assets, rights, org, actor = _service_fixture()
    shots = _shots(script, assets, rights)
    first = service.create_storyboard(script, shots=shots, asset_versions=assets, rights_versions=rights, org_id=org, actor_id=actor, idempotency_key="create", created_at=NOW)
    edited_shots = deepcopy(shots)
    edited_shots[1]["purpose"] = "A human reviewer clarified the evidence." 
    revised = service.revise_storyboard(
        media_storyboard_id=first["media_storyboard"]["id"], expected_version_no=1,
        shots=edited_shots, asset_versions=assets, rights_versions=rights,
        revision_reason="review wording", script_version=script, org_id=org, actor_id=actor,
        idempotency_key="revise", revised_at=NOW,
    )
    assert revised["version"]["version_no"] == 2
    assert service.get_version(org_id=org, version_id=first["version"]["id"]) == first["version"]
    with pytest.raises(MediaStoryboardError) as stale:
        service.revise_storyboard(
            media_storyboard_id=first["media_storyboard"]["id"], expected_version_no=1,
            shots=edited_shots, asset_versions=assets, rights_versions=rights,
            revision_reason="race", script_version=script, org_id=org, actor_id=actor,
            idempotency_key="race", revised_at=NOW,
        )
    assert stale.value.code == "VERSION_CONFLICT"
