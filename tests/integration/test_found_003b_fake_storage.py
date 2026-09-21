from __future__ import annotations

from infra.foundation.storage import FakeStorage


def test_fake_storage_round_trip_is_private_and_tenant_scoped() -> None:
    storage = FakeStorage()
    record = storage.put("org-integration", "fixtures/input.txt", b"fixture")
    assert record.storage_object_ref.startswith("private://")
    assert storage.get("org-integration", record.storage_object_ref) == b"fixture"
    assert [item.storage_object_ref for item in storage.list("org-integration")] == [
        record.storage_object_ref
    ]
