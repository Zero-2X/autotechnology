from __future__ import annotations

import pytest

from modules.distribution import CapabilityMatrix, CapabilityMatrixError, CapabilityMatrixRegistry


ORG = "00000000-0000-4000-8000-000000000001"
OTHER_ORG = "00000000-0000-4000-8000-000000000009"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
CAPABILITY = "00000000-0000-4000-8000-000000000004"
STAMP = "2026-09-19T00:00:00Z"


def _capability(**changes):
    value = {"id": CAPABILITY, "platform_id": PLATFORM, "version": 1,
             "actions": ["draft", "publish"], "limits": {}, "policy_version": "fake-v1",
             "status": "active", "created_at": STAMP}
    return {**value, **changes}


def _mapping():
    return {"title": "headline", "body": "text", "tags": "labels", "disclosure": "sponsor_notice", "media": "attachments"}


def test_matrix_maps_only_canonical_fields_and_preserves_platform_mapping_at_adapter_boundary() -> None:
    matrix = CapabilityMatrix(capability=_capability(), field_mapping=_mapping())
    payload = {"title": "Hello", "body": {"p": "text"}, "tags": ["one"], "disclosure": None, "media": []}
    mapped = matrix.map_payload(payload)
    assert mapped == {"headline": "Hello", "text": {"p": "text"}, "labels": ["one"], "sponsor_notice": None, "attachments": []}
    with pytest.raises(CapabilityMatrixError) as error:
        matrix.map_payload({**payload, "platform_title": "leak"})
    assert error.value.code == "INVALID_CANONICAL_PAYLOAD"
    with pytest.raises(CapabilityMatrixError) as error:
        matrix.require("schedule")
    assert error.value.code == "CAPABILITY_UNSUPPORTED"


def test_matrix_registry_is_immutable_tenant_scoped_and_idempotent() -> None:
    registry = CapabilityMatrixRegistry()
    first = registry.register(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="matrix",
                              capability=_capability(), field_mapping=_mapping(), registered_at=STAMP)
    replay = registry.register(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="matrix",
                               capability=_capability(), field_mapping=_mapping(), registered_at=STAMP)
    assert first == replay
    assert registry.get(org_id=ORG, platform_id=PLATFORM, version=1).snapshot_hash == first["snapshot_hash"]
    with pytest.raises(CapabilityMatrixError) as error:
        registry.register(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="changed",
                          capability=_capability(actions=["draft", "publish", "schedule"]), field_mapping=_mapping(), registered_at=STAMP)
    assert error.value.code == "MATRIX_IMMUTABLE"
    with pytest.raises(CapabilityMatrixError) as error:
        registry.get(org_id=OTHER_ORG, platform_id=PLATFORM, version=1)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
    assert registry.events[-1]["event_type"] == "distribution.capability_matrix.registered"
