from uuid import uuid4

import pytest

from modules.agent import AgentError, AgentRegistry


SCHEMAS = {
    "input/v1": {"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}}},
    "output/v1": {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
}


def register(registry: AgentRegistry, org_id: object, **extra: object):
    values: dict[str, object] = {"org_id": org_id, "key": "writer", "input_schema_ref": "input/v1", "output_schema_ref": "output/v1", "tool_allowlist": ["model.generate"], "permissions": ["content:write"], "cost_limit_cents": 100, "timeout_ms": 1000, "human_escalation_conditions": ["low_confidence"]}
    values.update(extra)
    return registry.register(**values)  # type: ignore[arg-type]


def test_registry_versions_are_immutable_and_tenant_scoped() -> None:
    registry = AgentRegistry(SCHEMAS)
    org_id = uuid4()
    first = register(registry, org_id)
    second = register(registry, org_id)
    assert (first.version, second.version) == (1, 2)
    assert registry.get(org_id=org_id, key="writer").version == 2
    with pytest.raises(AgentError) as error:
        registry.get(org_id=uuid4(), key="writer")
    assert error.value.code == "AGENT_NOT_FOUND"


def test_schema_and_safety_constraints_are_enforced() -> None:
    registry = AgentRegistry(SCHEMAS)
    org_id = uuid4()
    definition = register(registry, org_id)
    registry.validate_input(definition, {"topic": "ok"})
    registry.validate_output(definition, {"answer": "ok"})
    with pytest.raises(AgentError) as error:
        registry.validate_input(definition, {"topic": 3})
    assert error.value.code == "AGENT_INPUT_SCHEMA_INVALID"
    with pytest.raises(AgentError) as error:
        register(registry, org_id, cost_limit_cents=-1)
    assert error.value.code == "AGENT_DEFINITION_INVALID"


def test_unknown_schema_and_non_incrementing_version_are_rejected() -> None:
    registry = AgentRegistry(SCHEMAS)
    org_id = uuid4()
    with pytest.raises(AgentError) as error:
        register(registry, org_id, input_schema_ref="missing")
    assert error.value.code == "AGENT_SCHEMA_NOT_FOUND"
    register(registry, org_id)
    with pytest.raises(AgentError) as error:
        register(registry, org_id, version=1)
    assert error.value.code == "AGENT_VERSION_CONFLICT"
