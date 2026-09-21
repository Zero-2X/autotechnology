from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.media import MediaScriptService, MediaStoryboardService, MediaSubtitleError, MediaSubtitleService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[3]


def _script() -> tuple[str, str, dict]:
    org, actor = str(uuid4()), str(uuid4())
    variant = {
        "id": str(uuid4()), "org_id": org, "content_variant_id": str(uuid4()), "canonical_content_version_id": str(uuid4()),
        "version_no": 1, "locale": "en-US", "market": "US", "audience": "engineers", "tone": "neutral",
        "region_profile_version_id": str(uuid4()), "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "intro", "localized_text": "A verified subtitle source.", "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": str(uuid4()),
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor, "created_at": "2026-01-01T00:00:00Z",
    }
    claim = {
        "id": str(uuid4()), "org_id": org, "entity_ids": [], "statement": "A verified subtitle source.", "fact_type": "product.fact",
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


def _cues(*, language: str = "en") -> list[dict]:
    values = [
        (1, 1, 0, 2000, "Opening point." if language == "en" else "开场要点。"),
        (2, 1, 2000, 4000, "Verified and traceable." if language == "en" else "结果可验证。"),
        (3, 2, 4000, 12000, "The body explains the source." if language == "en" else "正文说明来源。"),
        (4, 2, 12000, 26000, "Review the complete evidence." if language == "en" else "请查看完整证据。"),
        (5, 3, 26000, 30000, "Learn more." if language == "en" else "了解更多。"),
    ]
    return [{
        "sequence": seq, "source_segment_sequence": segment, "start_ms": start, "end_ms": end,
        "text": text, "speaker_label": None, "sound_description": None, "is_forced": False,
        "line": 90, "position": 50, "align": "center",
    } for seq, segment, start, end, text in values]


def _track(locale: str = "en-US", *, language: str = "en", kind: str = "caption", default: bool = True) -> dict:
    return {
        "locale": locale, "language_name": "English" if language == "en" else "中文", "kind": kind,
        "direction": "ltr" if language == "en" else "ltr", "is_default": default, "text_version": 1,
        "cues": _cues(language=language),
        "accessibility": {
            "captions_complete": kind == "caption", "speaker_labels_complete": False,
            "sound_descriptions_complete": False, "reading_order": "chronological", "max_lines": 2, "max_chars_per_line": 42,
        },
    }


def _fixture() -> tuple[MediaSubtitleService, str, str, dict]:
    org, actor, script = _script()
    return MediaSubtitleService(clock=lambda: NOW), org, actor, script


def test_single_and_multilingual_tracks_validate_and_are_order_independent() -> None:
    service, org, actor, script = _fixture()
    tracks = [_track("en-US", language="en", default=True), _track("zh-CN", language="zh", kind="subtitle", default=False)]
    first = service.create_subtitle(script, tracks=tracks, org_id=org, actor_id=actor, idempotency_key="multi", created_at=NOW)
    reordered = [dict(track, cues=list(reversed(track["cues"]))) for track in reversed(tracks)]
    second = MediaSubtitleService(clock=lambda: NOW).create_subtitle(
        script, tracks=reordered, org_id=org, actor_id=str(uuid4()), idempotency_key="multi-2", created_at=NOW,
    )
    schema = json.loads((ROOT / "packages/contracts/jsonschema/media-subtitle-version.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(first["version"])
    assert first["version"]["snapshot_hash"] == second["version"]["snapshot_hash"]
    assert first["version"]["track_count"] == 2
    assert [item["locale"] for item in first["version"]["tracks"]] == ["en-US", "zh-CN"]


def test_single_track_convenience_and_accessibility_fields() -> None:
    service, org, actor, script = _fixture()
    result = service.create_subtitle(
        script, locale="en-US", language_name="English", cues=_cues(), kind="caption",
        org_id=org, actor_id=actor, idempotency_key="single", created_at=NOW,
    )
    track = result["version"]["tracks"][0]
    assert track["is_default"] is True
    assert track["accessibility"]["captions_complete"] is True
    assert result["version"]["source_script_snapshot_hash"] == script["snapshot_hash"]


def test_timeline_locale_and_accessibility_gates_fail_closed() -> None:
    service, org, actor, script = _fixture()
    overlap = _track()
    overlap["cues"][1]["start_ms"] = 1500
    with pytest.raises(MediaSubtitleError) as timeline:
        service.create_subtitle(script, tracks=[overlap], org_id=org, actor_id=actor, idempotency_key="overlap", created_at=NOW)
    assert timeline.value.code == "CUE_TIMELINE_INVALID"
    duplicate = _track("en-US")
    with pytest.raises(MediaSubtitleError) as locale:
        service.create_subtitle(script, tracks=[_track("en-US"), duplicate], org_id=org, actor_id=actor, idempotency_key="duplicate", created_at=NOW)
    assert locale.value.code == "TRACK_LOCALE_DUPLICATE"
    inaccessible = _track()
    inaccessible["accessibility"]["speaker_labels_complete"] = True
    with pytest.raises(MediaSubtitleError) as access:
        service.create_subtitle(script, tracks=[inaccessible], org_id=org, actor_id=actor, idempotency_key="access", created_at=NOW)
    assert access.value.code == "ACCESSIBILITY_INVALID"


def test_storyboard_binding_revision_and_idempotency() -> None:
    service, org, actor, script = _fixture()
    storyboard = MediaStoryboardService(clock=lambda: NOW).create_storyboard(
        script, shots=[
            {"sequence": 1, "script_segment_sequence": 1, "start_ms": 0, "end_ms": 4000, "purpose": "hook", "transition": "none", "asset_refs": []},
            {"sequence": 2, "script_segment_sequence": 2, "start_ms": 4000, "end_ms": 26000, "purpose": "body", "transition": "none", "asset_refs": []},
            {"sequence": 3, "script_segment_sequence": 3, "start_ms": 26000, "end_ms": 30000, "purpose": "close", "transition": "none", "asset_refs": []},
        ], org_id=org, actor_id=actor, idempotency_key="story", created_at=NOW,
    )
    first = service.create_subtitle(
        script, storyboard_version=storyboard["version"], tracks=[_track()], org_id=org, actor_id=actor,
        idempotency_key="bound", created_at=NOW,
    )
    replay = service.create_subtitle(
        script, storyboard_version=storyboard["version"], tracks=[_track()], org_id=org, actor_id=str(uuid4()),
        idempotency_key="bound", created_at=NOW,
    )
    assert replay == first
    edited = deepcopy(_track())
    edited["cues"][0]["text"] = "Human edited opening."
    revised = service.revise_subtitle(
        media_subtitle_id=first["media_subtitle"]["id"], expected_version_no=1, tracks=[edited],
        storyboard_version=storyboard["version"], script_version=script, revision_reason="human wording",
        org_id=org, actor_id=actor, idempotency_key="bound-edit", revised_at=NOW,
    )
    assert revised["version"]["version_no"] == 2
    assert service.get_version(org_id=org, version_id=first["version"]["id"]) == first["version"]
    with pytest.raises(MediaSubtitleError) as stale:
        service.revise_subtitle(
            media_subtitle_id=first["media_subtitle"]["id"], expected_version_no=1, tracks=[edited],
            storyboard_version=storyboard["version"], script_version=script, revision_reason="race",
            org_id=org, actor_id=actor, idempotency_key="bound-race", revised_at=NOW,
        )
    assert stale.value.code == "VERSION_CONFLICT"
