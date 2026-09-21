from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.media import MediaScriptError, MediaScriptService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


class VariantPort:
    def __init__(self, version: dict, source_map: list[dict]) -> None:
        self.version = version
        self.source_map = source_map
        self.calls: list[tuple[str, str]] = []

    def get_version(self, *, org_id: str, version_id: str):
        self.calls.append((org_id, version_id))
        return {"version": deepcopy(self.version), "source_map": deepcopy(self.source_map)}


class ClaimPort:
    def __init__(self, values: list[dict]) -> None:
        self.values = {item["id"]: item for item in values}

    def get_claim(self, *, org_id: str, claim_id: str):
        value = deepcopy(self.values[claim_id])
        if value["org_id"] != org_id:
            raise KeyError(claim_id)
        return value


def facts() -> tuple[str, str, dict, list[dict], list[dict]]:
    org, actor = str(uuid4()), str(uuid4())
    canonical, variant_id = str(uuid4()), str(uuid4())
    claims = []
    blocks = []
    source_map = []
    for index, text in enumerate((
        "Verified latency is twenty milliseconds. The measurement uses the documented test method.",
        "The supported release remains available in the United States market.",
    ), 1):
        claim_id = str(uuid4())
        claims.append({
            "id": claim_id, "org_id": org, "entity_ids": [], "statement": text,
            "fact_type": f"product.fact_{index}", "applicable_versions": [canonical],
            "applicable_regions": ["US"], "applicable_locales": ["en-US"],
            "valid_from": "2026-01-01T00:00:00Z", "valid_to": "2027-01-01T00:00:00Z",
            "review_due_at": "2026-12-01T00:00:00Z", "supersedes_claim_id": None,
            "freshness_status": "fresh", "status": "verified", "version": 1,
            "content_hash": f"{index}" * 64, "created_by": actor,
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        })
        blocks.append({"block_id": f"b{index}", "localized_text": text, "term_refs": [], "disclosure": None})
        source_map.append({"block_id": f"b{index}", "claim_id": claim_id})
    version = {
        "id": variant_id, "org_id": org, "content_variant_id": str(uuid4()),
        "canonical_content_version_id": canonical, "version_no": 3, "locale": "en-US", "market": "US",
        "audience": "engineers", "tone": "neutral", "region_profile_version_id": str(uuid4()),
        "source_variant_version_id": None, "body": {"blocks": blocks}, "term_memory_version": "terms-3",
        "disclosure": None, "policy_snapshot_id": str(uuid4()), "status": "approved",
        "snapshot_hash": "a" * 64, "created_by": actor, "created_at": "2026-09-19T00:00:00Z",
    }
    return org, actor, version, claims, source_map


def test_media_script_ports_lock_exact_variant_and_recheck_claims_for_edits() -> None:
    org, actor, variant, claims, source_map = facts()
    variant_port = VariantPort(variant, source_map)
    claim_port = ClaimPort(claims)
    service = MediaScriptService(variant_port=variant_port, claim_port=claim_port, clock=lambda: NOW)
    created = service.create_script(
        variant_version_id=variant["id"], duration_seconds=60, org_id=org, actor_id=actor,
        trace_id="integration", idempotency_key="create", created_at=NOW,
    )
    assert created["version"]["claim_refs"] == sorted(item["id"] for item in claims)
    assert variant_port.calls == [(org, variant["id"])]
    edited = service.edit_script(
        media_script_id=created["media_script"]["id"], expected_version_no=1,
        segment_edits={2: "A reviewer shortened the verified script text."}, edit_reason="reviewer wording",
        org_id=org, actor_id=actor, trace_id="edit", idempotency_key="edit", edited_at=NOW,
    )
    assert edited["version"]["version_no"] == 2
    assert edited["version"]["claim_refs"] == created["version"]["claim_refs"]
    assert len(service.list_versions(org_id=org, media_script_id=created["media_script"]["id"])) == 2

    claim_port.values[claims[0]["id"]]["freshness_status"] = "withdrawn"
    with pytest.raises(MediaScriptError) as exc:
        service.edit_script(
            media_script_id=created["media_script"]["id"], expected_version_no=2,
            segment_edits={2: "Another change."}, edit_reason="later edit", org_id=org,
            idempotency_key="withdrawn", edited_at=NOW,
        )
    assert exc.value.code == "CLAIM_NOT_FRESH"


def test_parallel_edits_allow_only_one_current_pointer_advance() -> None:
    org, actor, variant, claims, source_map = facts()
    service = MediaScriptService(
        variant_port=VariantPort(variant, source_map), claim_port=ClaimPort(claims), clock=lambda: NOW,
    )
    created = service.create_script(
        variant_version_id=variant["id"], duration_seconds=30, org_id=org, actor_id=actor,
        idempotency_key="create-race", created_at=NOW,
    )

    def edit(index: int) -> str:
        try:
            service.edit_script(
                media_script_id=created["media_script"]["id"], expected_version_no=1,
                segment_edits={2: f"Human edit number {index}."}, edit_reason=f"reason {index}",
                org_id=org, actor_id=actor, idempotency_key=f"edit-race-{index}", edited_at=NOW,
            )
            return "ok"
        except MediaScriptError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, (1, 2)))
    assert sorted(results) == ["VERSION_CONFLICT", "ok"]
    assert len(service.list_versions(org_id=org, media_script_id=created["media_script"]["id"])) == 2


def test_exact_variant_binding_and_tenant_scope_cannot_be_substituted() -> None:
    org, actor, variant, claims, source_map = facts()
    service = MediaScriptService(variant_port=VariantPort(variant, source_map), claim_port=ClaimPort(claims), clock=lambda: NOW)
    with pytest.raises(MediaScriptError) as wrong_id:
        service.create_script(
            variant_version_id=str(uuid4()), duration_seconds=30, org_id=org, actor_id=actor,
            idempotency_key="wrong-id", created_at=NOW,
        )
    assert wrong_id.value.code == "VARIANT_VERSION_NOT_FOUND"
    with pytest.raises(MediaScriptError) as foreign:
        service.create_script(
            variant_version_id=variant["id"], duration_seconds=30, org_id=str(uuid4()), actor_id=actor,
            idempotency_key="foreign", created_at=NOW,
        )
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"
