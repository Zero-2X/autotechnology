from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from modules.media import MediaScriptService, MediaSubtitleError, MediaSubtitleService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def _script(duration: int) -> tuple[str, str, dict]:
    org, actor = str(uuid4()), str(uuid4())
    variant = {
        "id": str(uuid4()), "org_id": org, "content_variant_id": str(uuid4()), "canonical_content_version_id": str(uuid4()),
        "version_no": 1, "locale": "en-US", "market": "US", "audience": "engineers", "tone": "neutral",
        "region_profile_version_id": str(uuid4()), "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "b", "localized_text": "A verified caption source.", "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": str(uuid4()),
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
    }
    claim = {
        "id": str(uuid4()), "org_id": org, "entity_ids": [], "statement": "A verified caption source.", "fact_type": "product.fact",
        "applicable_versions": [variant["canonical_content_version_id"]], "applicable_regions": [], "applicable_locales": ["en-US"],
        "valid_from": None, "valid_to": None, "review_due_at": None, "supersedes_claim_id": None,
        "freshness_status": "fresh", "status": "verified", "version": 1, "content_hash": "b" * 64,
        "created_by": actor, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
    }
    result = MediaScriptService(clock=lambda: NOW).create_script(
        variant, duration_seconds=duration, claims=[claim], source_map=[{"block_id": "b", "claim_id": claim["id"]}],
        org_id=org, actor_id=actor, idempotency_key=f"script-{duration}", created_at=NOW,
    )
    return org, actor, result["version"]


def _tracks(script: dict) -> list[dict]:
    cues = [{
        "sequence": index, "source_segment_sequence": segment["sequence"], "start_ms": segment["start_ms"],
        "end_ms": segment["end_ms"], "text": segment["text"], "speaker_label": None,
        "sound_description": None, "is_forced": False, "line": 90, "position": 50, "align": "center",
    } for index, segment in enumerate(script["segments"], 1)]
    return [{
        "locale": "en-US", "language_name": "English", "kind": "caption", "direction": "ltr",
        "is_default": True, "text_version": 1, "cues": cues,
        "accessibility": {"captions_complete": True, "speaker_labels_complete": False,
                          "sound_descriptions_complete": False, "reading_order": "chronological",
                          "max_lines": 2, "max_chars_per_line": 42},
    }]


def test_supported_durations_keep_exact_script_timeline_and_no_external_work() -> None:
    for duration in (30, 60, 90):
        org, actor, script = _script(duration)
        version = MediaSubtitleService(clock=lambda: NOW).create_subtitle(
            script, tracks=_tracks(script), org_id=org, actor_id=actor,
            idempotency_key=f"duration-{duration}", created_at=NOW,
        )["version"]
        assert version["duration_seconds"] == duration
        assert version["tracks"][0]["cues"][0]["start_ms"] == 0
        assert version["tracks"][0]["cues"][-1]["end_ms"] == duration * 1000
        assert "render" not in version
        assert "provider" not in version


def test_exact_port_binding_and_tenant_scope() -> None:
    org, actor, script = _script(30)
    class Port:
        def __init__(self): self.calls = []
        def get_version(self, *, org_id: str, version_id: str):
            self.calls.append((org_id, version_id))
            return {"version": deepcopy(script)}
    port = Port()
    service = MediaSubtitleService(script_port=port, clock=lambda: NOW)
    result = service.create_subtitle(
        media_script_version_id=script["id"], tracks=_tracks(script), org_id=org, actor_id=actor,
        idempotency_key="port", created_at=NOW,
    )
    assert result["version"]["media_script_version_id"] == script["id"]
    assert port.calls == [(org, script["id"])]
    with pytest.raises(MediaSubtitleError) as foreign:
        service.create_subtitle(script, tracks=_tracks(script), org_id=str(uuid4()), actor_id=actor, idempotency_key="foreign", created_at=NOW)
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"


def test_parallel_revisions_allow_one_pointer_advance() -> None:
    org, actor, script = _script(30)
    service = MediaSubtitleService(clock=lambda: NOW)
    first = service.create_subtitle(script, tracks=_tracks(script), org_id=org, actor_id=actor, idempotency_key="create", created_at=NOW)
    subtitle_id = first["media_subtitle"]["id"]

    def revise(index: int) -> str:
        tracks = _tracks(script)
        tracks[0]["cues"][1]["text"] = f"Reviewer {index} text."
        try:
            service.revise_subtitle(
                media_subtitle_id=subtitle_id, expected_version_no=1, tracks=tracks,
                revision_reason=f"review {index}", script_version=script, org_id=org, actor_id=actor,
                idempotency_key=f"revise-{index}", revised_at=NOW,
            )
            return "ok"
        except MediaSubtitleError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(revise, (1, 2)))
    assert sorted(values) == ["VERSION_CONFLICT", "ok"]
    assert len(service.list_versions(org_id=org, media_subtitle_id=subtitle_id)) == 2
