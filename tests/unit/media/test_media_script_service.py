from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from modules.media import MediaScriptError, MediaScriptService


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def fixture(*, locale: str = "en-US") -> tuple[str, str, dict, dict]:
    org, actor = str(uuid4()), str(uuid4())
    variant_id, canonical_id, region_id, policy_id, claim_id = (str(uuid4()) for _ in range(5))
    text = (
        "The service reduces processing time to twenty milliseconds. "
        "This second sentence explains the verified result and keeps the source traceable."
        if locale == "en-US" else "服务将处理时间降低到二十毫秒。第二句话说明已验证结果并保留来源追踪。"
    )
    variant = {
        "id": variant_id, "org_id": org, "content_variant_id": str(uuid4()),
        "canonical_content_version_id": canonical_id, "version_no": 1, "locale": locale,
        "market": "US", "audience": "engineers", "tone": "neutral",
        "region_profile_version_id": region_id, "source_variant_version_id": None,
        "body": {"blocks": [{"block_id": "intro", "localized_text": text, "term_refs": [], "disclosure": None}]},
        "term_memory_version": "terms-v1", "disclosure": None, "policy_snapshot_id": policy_id,
        "status": "approved", "snapshot_hash": "a" * 64, "created_by": actor,
        "created_at": "2026-09-19T00:00:00Z",
    }
    claim = {
        "id": claim_id, "org_id": org, "entity_ids": [], "statement": "Processing time is twenty milliseconds.",
        "fact_type": "performance.latency", "applicable_versions": [canonical_id],
        "applicable_regions": [], "applicable_locales": [locale], "valid_from": None, "valid_to": None,
        "review_due_at": None, "supersedes_claim_id": None, "freshness_status": "fresh", "status": "verified",
        "version": 1, "content_hash": "b" * 64, "created_by": actor,
        "created_at": "2026-09-19T00:00:00Z", "updated_at": "2026-09-19T00:00:00Z",
    }
    return org, actor, variant, claim


def create(service: MediaScriptService, variant: dict, claim: dict, org: str, actor: str, *, duration: int = 30, key: str = "create-1"):
    return service.create_script(
        variant, duration_seconds=duration, source_map=[{"block_id": "intro", "claim_id": claim["id"]}],
        claims=[claim], org_id=org, actor_id=actor, trace_id="trace-a", idempotency_key=key,
        created_at=NOW,
    )


def test_all_durations_have_fixed_contiguous_timeline_and_contract_output() -> None:
    org, actor, variant, claim = fixture()
    service = MediaScriptService(clock=lambda: NOW)
    schema = json.loads((__import__("pathlib").Path("packages/contracts/jsonschema/media-script-version.schema.json")).read_text())
    for duration, expected in {
        30: [(0, 4000), (4000, 26000), (26000, 30000)],
        60: [(0, 7000), (7000, 53000), (53000, 60000)],
        90: [(0, 10000), (10000, 80000), (80000, 90000)],
    }.items():
        result = create(service, variant, claim, org, actor, duration=duration, key=f"duration-{duration}")
        version = result["version"]
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(version)
        assert [(item["start_ms"], item["end_ms"]) for item in version["segments"]] == expected
        assert version["word_count"] <= {30: 75, 60: 150, 90: 225}[duration]
        assert version["segments"][0]["kind"] == "hook"
        assert version["segments"][1]["kind"] == "body"
        assert version["segments"][2]["kind"] == "cta"


def test_direct_block_claim_extensions_and_reordered_inputs_are_deterministic() -> None:
    org, actor, variant, claim = fixture()
    variant["body"]["blocks"][0]["claim_refs"] = [claim["id"]]
    service = MediaScriptService(clock=lambda: NOW)
    first = service.create_script(variant, duration_seconds=30, claims=[claim], org_id=org, actor_id=actor,
                                  trace_id="one", idempotency_key="det-1", created_at=NOW)
    other_claim = deepcopy(claim)
    other_claim["id"] = str(uuid4())
    other_claim["content_hash"] = "c" * 64
    second = MediaScriptService(clock=lambda: NOW).create_script(
        {**variant, "body": {"blocks": list(reversed(variant["body"]["blocks"]))}}, duration_seconds=30,
        claims=[other_claim, claim], claim_ids=[claim["id"]], org_id=org, actor_id=str(uuid4()),
        trace_id="two", idempotency_key="det-2", created_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    )
    assert first["version"]["snapshot_hash"] == second["version"]["snapshot_hash"]


def test_variant_and_claim_gates_are_fail_closed() -> None:
    org, actor, variant, claim = fixture()
    service = MediaScriptService(clock=lambda: NOW)
    for field, value, code in (("status", "draft", "VARIANT_NOT_APPROVED"), ("policy_snapshot_id", None, "VARIANT_NOT_APPROVED")):
        candidate = deepcopy(variant)
        candidate[field] = value
        with pytest.raises(MediaScriptError) as exc:
            create(service, candidate, claim, org, actor, key=f"gate-{field}")
        assert exc.value.code == code
    for field, value, code in (("status", "draft", "CLAIM_NOT_VERIFIED"), ("freshness_status", "stale", "CLAIM_NOT_FRESH")):
        candidate = deepcopy(claim)
        candidate[field] = value
        with pytest.raises(MediaScriptError) as exc:
            create(service, variant, candidate, org, actor, key=f"claim-{field}")
        assert exc.value.code == code
    foreign = deepcopy(claim)
    foreign["org_id"] = str(uuid4())
    with pytest.raises(MediaScriptError) as exc:
        create(service, variant, foreign, org, actor, key="claim-foreign")
    assert exc.value.code in {"CLAIM_REFERENCE_INVALID", "TENANT_SCOPE_VIOLATION"}


def test_idempotency_and_duration_roots_are_stable() -> None:
    org, actor, variant, claim = fixture()
    service = MediaScriptService(clock=lambda: NOW)
    first = create(service, variant, claim, org, actor, key="same")
    replay = service.create_script(variant, duration_seconds=30, source_map=[{"block_id": "intro", "claim_id": claim["id"]}],
                                  claims=[claim], org_id=org, actor_id=str(uuid4()), trace_id="other",
                                  idempotency_key="same", created_at=datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert replay.as_contract() == first.as_contract()
    with pytest.raises(MediaScriptError) as exc:
        service.create_script(variant, duration_seconds=60, source_map=[{"block_id": "intro", "claim_id": claim["id"]}],
                              claims=[claim], org_id=org, actor_id=actor, trace_id="x", idempotency_key="same", created_at=NOW)
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"
    second = create(service, variant, claim, org, actor, duration=60, key="other-duration")
    assert first["media_script"]["id"] != second["media_script"]["id"]
    with pytest.raises(MediaScriptError) as exists:
        create(service, variant, claim, org, actor, key="third")
    assert exists.value.code == "SCRIPT_ALREADY_EXISTS"


def test_human_edit_is_append_only_and_preserves_lineage() -> None:
    org, actor, variant, claim = fixture()
    service = MediaScriptService(clock=lambda: NOW)
    first = create(service, variant, claim, org, actor)
    original = deepcopy(first["version"])
    edited = service.edit_script(
        media_script_id=first["media_script"]["id"], expected_version_no=1,
        segment_edits=[{"sequence": 2, "text": "A human edited factual sentence."}],
        edit_reason="clarify wording", claims=[claim], variant_version=variant,
        org_id=org, actor_id=actor, trace_id="edit", idempotency_key="edit-1", edited_at=NOW,
    )
    assert edited["version"]["version_no"] == 2
    assert edited["version"]["supersedes_version_id"] == original["id"]
    assert edited["version"]["segments"][0] == original["segments"][0]
    assert edited["version"]["segments"][1]["kind"] == original["segments"][1]["kind"]
    assert edited["version"]["segments"][1]["claim_refs"] == original["segments"][1]["claim_refs"]
    assert edited["version"]["segments"][1]["start_ms"] == original["segments"][1]["start_ms"]
    assert service.get_version(org_id=org, version_id=original["id"]) == original
    with pytest.raises(MediaScriptError) as conflict:
        service.edit_script(media_script_id=first["media_script"]["id"], expected_version_no=1,
                            segment_edits=[{"sequence": 1, "text": "another"}], edit_reason="race",
                            claims=[claim], variant_version=variant, org_id=org, idempotency_key="edit-2")
    assert conflict.value.code == "VERSION_CONFLICT"


def test_edit_rejects_empty_noop_overflow_and_claim_withdrawal() -> None:
    org, actor, variant, claim = fixture()
    service = MediaScriptService(clock=lambda: NOW)
    first = create(service, variant, claim, org, actor)
    for edits, reason, code in (
        ([], "x", "SCRIPT_EDIT_INVALID"),
        ([{"sequence": 2, "text": first["version"]["segments"][1]["text"]}], "x", "SCRIPT_EDIT_INVALID"),
        ([{"sequence": 2, "text": "word " * 200}], "x", "SCRIPT_EDIT_INVALID"),
    ):
        with pytest.raises(MediaScriptError) as exc:
            service.edit_script(media_script_id=first["media_script"]["id"], expected_version_no=1,
                                segment_edits=edits, edit_reason=reason, claims=[claim], variant_version=variant,
                                org_id=org, idempotency_key=f"invalid-{len(edits)}-{len(reason)}")
        assert exc.value.code == code
    withdrawn = deepcopy(claim)
    withdrawn["status"] = "withdrawn"
    with pytest.raises(MediaScriptError) as exc:
        service.edit_script(media_script_id=first["media_script"]["id"], expected_version_no=1,
                            segment_edits=[{"sequence": 2, "text": "new text"}], edit_reason="reason",
                            claims=[withdrawn], variant_version=variant, org_id=org, idempotency_key="withdrawn")
    assert exc.value.code == "CLAIM_NOT_VERIFIED"


def test_tenant_reads_and_dependency_failures_do_not_leak_details() -> None:
    org, actor, variant, claim = fixture()
    class Failing:
        def get_claim(self, **_: object):
            raise RuntimeError("authorization=secret token=private")
    service = MediaScriptService(claim_port=Failing(), clock=lambda: NOW)
    with pytest.raises(MediaScriptError) as exc:
        service.create_script(
            variant, duration_seconds=30,
            source_map=[{"block_id": "intro", "claim_id": claim["id"]}],
            org_id=org, actor_id=actor, idempotency_key="dependency", created_at=NOW,
        )
    assert exc.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "secret" not in str(exc.value).lower()
