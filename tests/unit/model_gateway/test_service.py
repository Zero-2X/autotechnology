import pytest

from modules.model_gateway import FakeModelProvider, ModelError, ModelRequest


def request(**overrides: object) -> ModelRequest:
    values: dict[str, object] = {
        "model_id": "fake-model",
        "prompt_version": "prompt/v1",
        "input": {"topic": "synthetic"},
        "response_schema_ref": None,
        "timeout_ms": 100,
        "budget_cents": 10,
        "trace_id": "trace-1",
    }
    values.update(overrides)
    return ModelRequest(**values)  # type: ignore[arg-type]


def test_same_request_hash_returns_deterministic_fixture() -> None:
    provider = FakeModelProvider()
    first = provider.generate(request())
    second = provider.generate(request())
    assert first.as_contract() == second.as_contract()
    assert provider.call_count == 2


def test_timeout_and_budget_fail_before_provider_call() -> None:
    provider = FakeModelProvider(latency_ms=20, cost_cents=5)
    with pytest.raises(ModelError) as timeout:
        provider.generate(request(timeout_ms=10))
    assert timeout.value.code == "MODEL_TIMEOUT"
    with pytest.raises(ModelError) as budget:
        provider.generate(request(budget_cents=4))
    assert budget.value.code == "MODEL_BUDGET_EXCEEDED"
    assert provider.call_count == 0


def test_response_schema_failure_is_explicit_and_not_retried() -> None:
    provider = FakeModelProvider(schema_registry={"schema/output": {"type": "string"}})
    with pytest.raises(ModelError) as error:
        provider.generate(request(response_schema_ref="schema/output"))
    assert error.value.code == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert provider.call_count == 0


def test_fixture_can_be_bound_to_request_hash_and_does_not_log_input() -> None:
    probe = request()
    provider = FakeModelProvider(fixtures={probe.request_hash: {"answer": "ok"}})
    result = provider.generate(probe)
    assert result.output == {"answer": "ok"}
    assert "synthetic" not in result.as_contract().__repr__()
