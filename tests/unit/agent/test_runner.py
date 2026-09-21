from uuid import uuid4

import pytest

from modules.agent import AgentError, AgentRegistry, AgentRunner
from modules.model_gateway import FakeModelProvider, ModelRequest


SCHEMAS = {
    "input/v1": {"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}, "tool_calls": {"type": "array", "items": {"type": "string"}}}},
    "output/v1": {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}}},
}


def setup():
    registry = AgentRegistry(SCHEMAS)
    org_id = uuid4()
    definition = registry.register(org_id=org_id, key="writer", input_schema_ref="input/v1", output_schema_ref="output/v1", tool_allowlist=["model.generate"], permissions=[], cost_limit_cents=10, timeout_ms=100, human_escalation_conditions=["low_confidence"])
    return registry, org_id, definition


def request() -> ModelRequest:
    return ModelRequest("fake", "prompt/v1", {"topic": "x"}, "output/v1", 100, 10, "trace")


def test_runner_validates_output_and_emits_completion() -> None:
    registry, org_id, definition = setup()
    provider = FakeModelProvider(fixtures={request().request_hash: {"answer": "ok", "confidence": 0.9}}, schema_registry={"output/v1": SCHEMAS["output/v1"]})
    run = AgentRunner(registry).run(org_id=org_id, definition=definition, input={"topic": "x"}, model_port=provider, model_request=request())
    assert run.status == "succeeded"


def test_runner_rejects_unauthorized_tool_and_bad_output() -> None:
    registry, org_id, definition = setup()
    runner = AgentRunner(registry)
    with pytest.raises(AgentError) as error:
        runner.run(org_id=org_id, definition=definition, input={"topic": "x", "tool_calls": ["filesystem.write"]}, model_port=FakeModelProvider(), model_request=request())
    assert error.value.code == "AGENT_TOOL_NOT_ALLOWED"
    bad_request = ModelRequest("fake", "prompt/v1", {"topic": "x"}, None, 100, 10, "trace")
    provider = FakeModelProvider(fixtures={bad_request.request_hash: {"wrong": True}})
    with pytest.raises(AgentError) as error:
        runner.run(org_id=org_id, definition=definition, input={"topic": "x"}, model_port=provider, model_request=bad_request)
    assert error.value.code == "AGENT_OUTPUT_SCHEMA_INVALID"
