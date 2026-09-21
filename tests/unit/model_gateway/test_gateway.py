import pytest

from modules.model_gateway import FakeModelProvider, ModelError, ModelGateway, ModelRequest


def req() -> ModelRequest:
    return ModelRequest("fake-model", "prompt/v1", {"x": 1}, None, 100, 10, "trace-1")


def test_gateway_records_calls_events_and_replays_idempotency() -> None:
    gateway = ModelGateway({"fake": FakeModelProvider()})
    config = gateway.register_config(org_id="org-a", provider="fake", model="fake-model", data_region="local", retention_policy="synthetic")
    first = gateway.call(org_id="org-a", config_id=config.id, request=req(), idempotency_key="call-key-1234")
    second = gateway.call(org_id="org-a", config_id=config.id, request=req(), idempotency_key="call-key-1234")
    assert first.id == second.id
    assert [event["type"] for event in gateway.events] == ["model.call.started", "model.call.succeeded"]
    with pytest.raises(ModelError) as error:
        gateway.call(org_id="org-a", config_id=config.id, request=ModelRequest("fake-model", "prompt/v1", {"x": 2}, None, 100, 10, "trace-1"), idempotency_key="call-key-1234")
    assert error.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_gateway_rejects_provider_and_cross_tenant_access() -> None:
    gateway = ModelGateway()
    with pytest.raises(ModelError, match="fake provider") as error:
        gateway.register_config(org_id="org-a", provider="openai", model="x", data_region="local", retention_policy="none")
    assert error.value.code == "PROVIDER_NOT_ALLOWED_IN_MVP"
    config = gateway.register_config(org_id="org-a", provider="fake", model="x", data_region="local", retention_policy="none")
    with pytest.raises(ModelError) as error:
        gateway.call(org_id="org-b", config_id=config.id, request=req(), idempotency_key="cross-tenant-1234")
    assert error.value.code == "TENANT_SCOPE_VIOLATION"
