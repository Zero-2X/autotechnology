from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.media import MediaScriptService, MediaStoryboardError, MediaStoryboardService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _script(duration: int) -> tuple[str, str, dict]:
    org, actor = str(uuid4()), str(uuid4())
    variant = {
        "id": str(uuid4()), "org_id": org, "content_variant_id": str(uuid4()),
        "canonical_content_version_id": str(uuid4()), "version_no": 1, "locale": "en-US", "market": "US",
        "audience": "engineers", "tone": "neutral", "region_profile_version_id": str(uuid4()),
        "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "b", "localized_text": "A verified integration fact.", "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": str(uuid4()),
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
    }
    claim = {
        "id": str(uuid4()), "org_id": org, "entity_ids": [], "statement": "A verified integration fact.",
        "fact_type": "product.fact", "applicable_versions": [variant["canonical_content_version_id"]],
        "applicable_regions": [], "applicable_locales": ["en-US"], "valid_from": None, "valid_to": None,
        "review_due_at": None, "supersedes_claim_id": None, "freshness_status": "fresh", "status": "verified",
        "version": 1, "content_hash": "b" * 64, "created_by": actor,
        "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }
    result = MediaScriptService(clock=lambda: NOW).create_script(
        variant, duration_seconds=duration, claims=[claim], source_map=[{"block_id": "b", "claim_id": claim["id"]}],
        org_id=org, actor_id=actor, idempotency_key=f"script-{duration}", created_at=NOW,
    )
    return org, actor, result["version"]


def _text_shots(script: dict) -> list[dict]:
    return [
        {"sequence": index, "script_segment_sequence": segment["sequence"], "start_ms": segment["start_ms"],
         "end_ms": segment["end_ms"], "purpose": f"Segment {index}", "transition": "none", "asset_refs": []}
        for index, segment in enumerate(script["segments"], 1)
    ]


class ExactPorts:
    def __init__(self, script: dict, assets: list[dict], rights: list[dict]) -> None:
        self.script = script
        self.assets = {item["id"]: item for item in assets}
        self.rights = {item["id"]: item for item in rights}
        self.calls: list[tuple[str, str, str]] = []

    def get_version(self, *, org_id: str, version_id: str):
        self.calls.append(("script", org_id, version_id))
        if version_id != self.script["id"]:
            raise KeyError(version_id)
        return {"version": deepcopy(self.script)}


def test_all_supported_durations_cover_script_without_rendering_or_subtitles() -> None:
    for duration in (30, 60, 90):
        org, actor, script = _script(duration)
        service = MediaStoryboardService(clock=lambda: NOW)
        result = service.create_storyboard(
            media_script_version_id=script["id"], script_version=script, shots=_text_shots(script),
            org_id=org, actor_id=actor, idempotency_key=f"duration-{duration}", created_at=NOW,
        )
        version = result["version"]
        assert version["duration_seconds"] == duration
        assert version["shots"][0]["start_ms"] == 0
        assert version["shots"][-1]["end_ms"] == duration * 1000
        assert "subtitle" not in version
        assert "render" not in version


def test_ports_are_exact_and_rejected_dependencies_do_not_leak() -> None:
    org, actor, script = _script(30)
    class ScriptPort:
        def __init__(self): self.calls = []
        def get_version(self, *, org_id: str, version_id: str):
            self.calls.append((org_id, version_id))
            return deepcopy(script)
    port = ScriptPort()
    service = MediaStoryboardService(script_port=port, clock=lambda: NOW)
    result = service.create_storyboard(
        media_script_version_id=script["id"], shots=_text_shots(script), org_id=org, actor_id=actor,
        idempotency_key="port", created_at=NOW,
    )
    assert result["version"]["media_script_version_id"] == script["id"]
    assert port.calls == [(org, script["id"])]
    with pytest.raises(MediaStoryboardError) as missing:
        service.create_storyboard(media_script_version_id=str(uuid4()), shots=_text_shots(script), org_id=org, actor_id=actor, idempotency_key="missing", created_at=NOW)
    assert missing.value.code == "SCRIPT_VERSION_NOT_FOUND"
    assert "secret" not in str(missing.value).lower()


def test_parallel_revisions_allow_one_expected_version_advance() -> None:
    org, actor, script = _script(30)
    service = MediaStoryboardService(clock=lambda: NOW)
    first = service.create_storyboard(script, shots=_text_shots(script), org_id=org, actor_id=actor, idempotency_key="create", created_at=NOW)
    storyboard_id = first["media_storyboard"]["id"]

    def revise(index: int) -> str:
        shots = _text_shots(script)
        shots[1]["purpose"] = f"Reviewer {index} wording"
        try:
            service.revise_storyboard(
                media_storyboard_id=storyboard_id, expected_version_no=1, shots=shots,
                revision_reason=f"review {index}", script_version=script, org_id=org, actor_id=actor,
                idempotency_key=f"revise-{index}", revised_at=NOW,
            )
            return "ok"
        except MediaStoryboardError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(revise, (1, 2)))
    assert sorted(values) == ["VERSION_CONFLICT", "ok"]
    assert len(service.list_versions(org_id=org, media_storyboard_id=storyboard_id)) == 2
