from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from infra.foundation.storage import StorageAccessError, StorageConflictError
from packages.testkit import create_synthetic_fixture


START = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)


def test_fixture_reproduces_private_storage_and_idempotent_audit_snapshot() -> None:
    first = create_synthetic_fixture("render-case", started_at=START)
    second = create_synthetic_fixture("render-case", started_at=START)

    left = first.put_object("inputs/article.json", b'{"title":"fixture"}', content_type="application/json")
    replay = first.put_object("inputs/article.json", b'{"title":"fixture"}', content_type="application/json")
    right = second.put_object("inputs/article.json", b'{"title":"fixture"}', content_type="application/json")

    assert left == replay == right
    assert first.storage.get(first.identity.org_id, left.storage_object_ref) == b'{"title":"fixture"}'
    assert len(first.audit_events()) == 1
    assert first.as_contract() == second.as_contract()
    assert first.as_contract()["network_access"] is False


def test_fixture_storage_is_tenant_isolated_and_immutable() -> None:
    fixture = create_synthetic_fixture("isolation-case", started_at=START)
    record = fixture.put_object("inputs/a.txt", b"first")

    with pytest.raises(StorageAccessError):
        fixture.storage.get(str(uuid4()), record.storage_object_ref)
    with pytest.raises(StorageConflictError):
        fixture.put_object("inputs/a.txt", b"changed")
    assert fixture.storage.get(fixture.identity.org_id, record.storage_object_ref) == b"first"


def test_audit_uses_refs_and_hashes_without_payload_or_seed() -> None:
    secret_seed = "api-token-do-not-persist"
    secret_payload = b"provider-secret-do-not-persist"
    fixture = create_synthetic_fixture(secret_seed, started_at=START)
    record = fixture.put_object("private/input.bin", secret_payload)
    fixture.clock.advance(timedelta(seconds=5))
    fixture.delete_object(record.storage_object_ref)

    snapshot = json.dumps(fixture.as_contract(), sort_keys=True)
    assert secret_seed not in snapshot
    assert secret_payload.decode() not in snapshot
    assert fixture.as_contract()["storage_objects"] == []
    assert [event.sequence for event in fixture.audit_events()] == [1, 2]
    assert [event.occurred_at for event in fixture.audit_events()] == [
        "2026-09-18T10:00:00.000000Z",
        "2026-09-18T10:00:05.000000Z",
    ]
    assert all(event.subject_ref.startswith("private://") for event in fixture.audit_events())


def test_different_seeds_have_isolated_storage_and_audit_state() -> None:
    first = create_synthetic_fixture("one", started_at=START)
    second = create_synthetic_fixture("two", started_at=START)
    stored = first.put_object("item.txt", b"one")

    assert second.storage.list(second.identity.org_id) == ()
    assert second.audit_events() == ()
    with pytest.raises(StorageAccessError):
        second.storage.get(second.identity.org_id, stored.storage_object_ref)
