from __future__ import annotations

from uuid import uuid4

import pytest

from modules.distribution import (
    DistributionPortError,
    DistributionPortSet,
    PublisherCapabilityRegistry,
)


ORG = "00000000-0000-4000-8000-000000000001"
ACTOR = "00000000-0000-4000-8000-000000000002"
PLATFORM = "00000000-0000-4000-8000-000000000003"
CAPABILITY = "00000000-0000-4000-8000-000000000004"
STAMP = "2026-09-19T00:00:00Z"


class Connection:
    def inspect(self, *, context, connection_id):
        return {"connection_id": connection_id}


class Publisher:
    def publish(self, *, context, publication_intent, idempotency_key):
        return {"accepted": True}


class Inbox:
    def receive(self, *, context, cursor=None):
        return ()


class Metrics:
    def emit(self, *, context, name, value, labels):
        return None


class Mixed:
    def inspect(self, *, context, connection_id):
        return {}

    def publish(self, *, context, publication_intent, idempotency_key):
        return {}

    def receive(self, *, context, cursor=None):
        return ()

    def emit(self, *, context, name, value, labels):
        return None


def _capability(**changes):
    value = {
        "id": CAPABILITY, "platform_id": PLATFORM, "version": 1,
        "actions": ["publish", "draft"], "limits": {}, "policy_version": "publisher-policy-v1",
        "status": "active", "created_at": STAMP,
    }
    return {**value, **changes}


def test_port_set_keeps_responsibilities_separate() -> None:
    ports = DistributionPortSet(connection=Connection(), publisher=Publisher(), inbox=Inbox(), metrics=Metrics())
    assert callable(ports.connection.inspect)
    assert callable(ports.publisher.publish)
    with pytest.raises(DistributionPortError) as error:
        mixed = Mixed()
        DistributionPortSet(connection=mixed, publisher=mixed, inbox=Inbox(), metrics=Metrics())
    assert error.value.code == "PORT_RESPONSIBILITIES_MIXED"


def test_capability_registry_validates_immutable_tenant_scoped_versions_and_replay() -> None:
    registry = PublisherCapabilityRegistry()
    first = registry.register(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="capability",
                              capability=_capability())
    replay = registry.register(org_id=ORG, actor_id=ACTOR, trace_id="replay", idempotency_key="capability",
                               capability=_capability())
    assert first == replay
    assert registry.get(org_id=ORG, capability_id=CAPABILITY, version=1) == first
    assert registry.events[-1]["event_type"] == "publisher.capability.registered"
    with pytest.raises(DistributionPortError) as error:
        registry.register(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="changed",
                          capability=_capability(actions=["publish"]))
    assert error.value.code == "CAPABILITY_IMMUTABLE"
    with pytest.raises(DistributionPortError) as error:
        registry.get(org_id=str(uuid4()), capability_id=CAPABILITY, version=1)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_invalid_capability_is_rejected_before_event() -> None:
    registry = PublisherCapabilityRegistry()
    with pytest.raises(DistributionPortError) as error:
        registry.register(org_id=ORG, actor_id=ACTOR, trace_id="trace", idempotency_key="invalid",
                          capability=_capability(status="unknown"))
    assert error.value.code == "INVALID_CAPABILITY"
    assert registry.events == []
