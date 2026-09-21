from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

import pytest

from modules.canonical_content import CanonicalContentError, CanonicalContentService


def _service() -> tuple[CanonicalContentService, str, str, str, str]:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "CREATE TABLE topic_briefs (id TEXT, org_id TEXT, status TEXT, input_snapshot_hash TEXT, payload TEXT)"
    )
    org_id, actor_id, brief_id = str(uuid4()), str(uuid4()), str(uuid4())
    snapshot_hash = "a" * 64
    connection.execute(
        "INSERT INTO topic_briefs VALUES (?, ?, 'locked', ?, ?)",
        (brief_id, org_id, snapshot_hash, json.dumps({
            "id": brief_id, "org_id": org_id, "status": "locked", "input_snapshot_hash": snapshot_hash,
        })),
    )
    return CanonicalContentService(connection=connection), org_id, actor_id, brief_id, snapshot_hash


def test_create_version_is_stable_and_review_is_tenant_scoped() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    created = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id, stable_key="rag-guide",
    )
    content_id = created["content"]["id"]
    payload = {
        "title": "RAG guide", "abstract": "A short guide", "input_snapshot_hash": snapshot_hash,
        "sections": [{"key": "intro", "position": 2, "content": "Intro"}, {"key": "why", "position": 1}],
        "claims": [{"key": "claim-a", "position": 1, "statement": "A claim"}],
    }
    first = service.create_version(
        org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="version-1", content=payload,
    )
    assert first["version"]["topic_brief_status"] == "locked"
    replay = service.create_version(
        org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="version-1", content=payload,
    )
    assert replay == first
    assert [item["key"] for item in first["version"]["sections"]] == ["why", "intro"]
    assert service.submit_review(
        org_id=org_id, canonical_content_id=content_id, actor_id=actor_id,
        trace_id="trace", idempotency_key="review", expected_version=1,
    )["content"]["status"] == "in_review"
    with pytest.raises(CanonicalContentError) as error:
        service.get(org_id=str(uuid4()), canonical_content_id=content_id)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_locked_brief_and_hash_mismatch_never_write_a_version() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    root = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id,
    )["content"]
    with pytest.raises(CanonicalContentError) as error:
        service.create_version(
            org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="bad-hash", content={
                "title": "Bad", "input_snapshot_hash": "b" * 64,
            },
        )
    assert error.value.code == "INPUT_SNAPSHOT_MISMATCH"
    assert service.connection.execute("SELECT COUNT(*) FROM canonical_content_versions").fetchone()[0] == 0


def test_duplicate_content_hash_returns_existing_version_without_new_row() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    root = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id,
    )["content"]
    payload = {"title": "Same", "input_snapshot_hash": snapshot_hash}
    first = service.create_version(
        org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="v1", content=payload,
    )
    second = service.create_version(
        org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="v2", content=payload,
    )
    assert second["version"]["id"] == first["version"]["id"]
    assert service.connection.execute("SELECT COUNT(*) FROM canonical_content_versions").fetchone()[0] == 1


def test_missing_or_unlocked_topic_brief_returns_required_without_writing() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    root = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id,
    )["content"]
    service.connection.execute("UPDATE topic_briefs SET status = 'draft', payload = ? WHERE id = ?", (
        json.dumps({"id": brief_id, "org_id": org_id, "status": "draft", "input_snapshot_hash": snapshot_hash}), brief_id,
    ))
    service.connection.commit()
    with pytest.raises(CanonicalContentError) as error:
        service.create_version(
            org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="draft-brief", content={
                "title": "Blocked", "input_snapshot_hash": snapshot_hash,
            },
        )
    assert error.value.code == "TOPIC_BRIEF_REQUIRED"
    assert service.connection.execute("SELECT COUNT(*) FROM canonical_content_versions").fetchone()[0] == 0


def test_version_diff_uses_stable_keys_and_versions_are_append_only() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    root = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id,
    )["content"]
    first = service.create_version(
        org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="v1", content={
            "title": "First", "abstract": "A", "input_snapshot_hash": snapshot_hash,
            "sections": [{"key": "intro", "position": 1, "content": "old"}],
        },
    )["version"]
    second = service.create_version(
        org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="v2", content={
            "title": "Second", "abstract": "A", "input_snapshot_hash": snapshot_hash,
            "sections": [{"key": "intro", "position": 1, "content": "new"}, {"key": "end", "position": 2}],
        },
    )["version"]
    diff = service.diff_versions(
        org_id=org_id, canonical_content_id=root["id"],
        from_version_id=first["id"], to_version_id=second["id"], actor_id=actor_id,
    )
    assert diff["changed_fields"] == ["sections", "title"]
    assert {operation["op"] for operation in diff["operations"]} == {"add", "replace"}
    assert service.diff_versions(
        org_id=org_id, canonical_content_id=root["id"],
        from_version_id=first["id"], to_version_id=second["id"], actor_id=actor_id,
    ) == diff
    with pytest.raises(CanonicalContentError) as error:
        service.update_version(second["id"], title="mutate")
    assert error.value.code == "IMMUTABLE_VERSION"
    with pytest.raises(Exception):
        service.connection.execute("UPDATE canonical_content_versions SET title = 'tampered' WHERE id = ?", (first["id"],))


def test_high_priority_claim_requires_evidence_and_verified_rights_version() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    claim_id, evidence_id, rights_id, source_id = (str(uuid4()) for _ in range(4))
    service.connection.executescript("""
        CREATE TABLE claims (id TEXT, org_id TEXT, status TEXT);
        CREATE TABLE evidences (id TEXT, org_id TEXT, claim_id TEXT, rights_record_version_id TEXT, status TEXT);
        CREATE TABLE rights_record_versions (id TEXT, org_id TEXT, status TEXT);
    """)
    service.connection.execute("INSERT INTO claims VALUES (?, ?, 'verified')", (claim_id, org_id))
    service.connection.execute("INSERT INTO rights_record_versions VALUES (?, ?, 'verified')", (rights_id, org_id))
    service.connection.execute("INSERT INTO evidences VALUES (?, ?, ?, ?, 'captured')", (evidence_id, org_id, claim_id, rights_id))
    service.connection.commit()
    root = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id,
    )["content"]
    good = service.create_version(
        org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="high-good", content={
            "title": "Evidence backed", "input_snapshot_hash": snapshot_hash,
            "claims": [{"key": "claim", "position": 1, "claim_id": claim_id, "priority": "high"}],
        },
    )
    assert good["version"]["claims"][0]["evidence_ids"] == [evidence_id]
    assert good["version"]["claims"][0]["rights_snapshot_ids"] == [rights_id]

    service.connection.execute("DELETE FROM evidences")
    service.connection.commit()
    with pytest.raises(CanonicalContentError) as error:
        service.create_version(
            org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="high-bad", content={
                "title": "Blocked", "input_snapshot_hash": snapshot_hash,
                "claims": [{"key": "claim-2", "position": 1, "claim_id": claim_id, "priority": "high"}],
            },
        )
    assert error.value.code == "CANONICAL_EVIDENCE_REQUIRED"


def test_freshness_expiry_is_append_only_and_refresh_queue_is_leased() -> None:
    service, org_id, actor_id, brief_id, snapshot_hash = _service()
    root = service.create(
        org_id=org_id, actor_id=actor_id, trace_id="trace", idempotency_key="root",
        topic_brief_id=brief_id,
    )["content"]
    version = service.create_version(
        org_id=org_id, canonical_content_id=root["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="version", content={
            "title": "Freshness", "input_snapshot_hash": snapshot_hash, "freshness_ttl_days": 1,
        },
    )["version"]
    checked = service.assess_freshness(
        org_id=org_id, canonical_content_id=root["id"], version_id=version["id"],
        actor_id=actor_id, trace_id="trace", idempotency_key="check",
        now="2030-01-01T00:00:00Z",
    )
    assert checked["check"]["freshness_status"] == "expired"
    queue = checked["refresh_queue"]
    assert queue["status"] == "queued"
    claimed = service.claim_refresh(
        org_id=org_id, queue_id=queue["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="claim", now="2030-01-01T00:00:00Z",
    )
    assert claimed["refresh_queue"]["attempts"] == 1
    completed = service.complete_refresh(
        org_id=org_id, queue_id=queue["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="complete", expected_attempts=1,
    )
    assert completed["refresh_queue"]["status"] == "completed"
    assert service.get_version(org_id=org_id, version_id=version["id"])["freshness_status"] == "expired"
    manual = service.enqueue_refresh(
        org_id=org_id, canonical_content_id=root["id"], version_id=version["id"],
        actor_id=actor_id, trace_id="trace", idempotency_key="manual-refresh", reason="manual",
        available_at="2030-01-01T00:00:00Z",
    )["refresh_queue"]
    service.claim_refresh(
        org_id=org_id, queue_id=manual["id"], actor_id=actor_id,
        trace_id="trace", idempotency_key="claim-manual", now="2030-01-01T00:00:00Z",
        lease_seconds=60,
    )
    with pytest.raises(CanonicalContentError) as expired_lease:
        service.complete_refresh(
            org_id=org_id, queue_id=manual["id"], actor_id=actor_id,
            trace_id="trace", idempotency_key="complete-expired", now="2030-01-01T00:02:00Z",
        )
    assert expired_lease.value.code == "REFRESH_QUEUE_NOT_CLAIMABLE"
    assert service.list_refresh_queue(org_id=str(uuid4())) == ()
