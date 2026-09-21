"""Versioned graph registry with explicit compatibility rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .errors import GraphError


GraphEntrypoint = Callable[..., Mapping[str, Any]]


@dataclass(frozen=True)
class GraphVersionPolicy:
    graph_key: str
    current_version: int
    compatible_versions: tuple[int, ...] = ()
    deprecated_versions: tuple[int, ...] = ()

    def accepts(self, version: int) -> bool:
        return version == self.current_version or version in self.compatible_versions


@dataclass(frozen=True)
class GraphDefinition:
    graph_key: str
    workflow_version: int
    entrypoint: GraphEntrypoint | None = None
    nodes: tuple[GraphEntrypoint, ...] = ()
    input_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    output_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None
    state_version: int = 1
    policy: GraphVersionPolicy | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate_input(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise GraphError("GRAPH_INPUT_INVALID", "graph input must be an object")
        result = dict(value)
        if self.input_validator:
            result = dict(self.input_validator(result))
        return result

    def validate_output(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise GraphError("GRAPH_OUTPUT_INVALID", "graph output must be an object")
        result = dict(value)
        if self.output_validator:
            result = dict(self.output_validator(result))
        return result


class GraphRegistry:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], GraphDefinition] = {}
        self._policies: dict[str, GraphVersionPolicy] = {}

    def register(self, definition: GraphDefinition) -> GraphDefinition:
        key = (definition.graph_key.strip(), int(definition.workflow_version))
        if not key[0] or key[1] < 1 or (not callable(definition.entrypoint) and not definition.nodes):
            raise GraphError("GRAPH_DEFINITION_INVALID", "graph key, positive version and entrypoint are required")
        if key in self._definitions:
            raise GraphError("GRAPH_VERSION_CONFLICT", "graph version is already registered")
        policy = definition.policy or self._policies.get(key[0])
        if policy and policy.graph_key != key[0]:
            raise GraphError("GRAPH_POLICY_INVALID", "graph policy key does not match definition")
        self._definitions[key] = definition
        if policy:
            self._policies[key[0]] = policy
        return definition

    def register_policy(self, policy: GraphVersionPolicy) -> GraphVersionPolicy:
        if policy.current_version < 1 or not policy.graph_key.strip():
            raise GraphError("GRAPH_POLICY_INVALID", "graph policy is invalid")
        if policy.graph_key in self._policies:
            old = self._policies[policy.graph_key]
            if old != policy:
                raise GraphError("GRAPH_POLICY_CONFLICT", "graph policy is immutable")
        self._policies[policy.graph_key] = policy
        return policy

    def resolve(self, graph_key: str, workflow_version: int | None = None) -> GraphDefinition:
        key = graph_key.strip()
        if workflow_version is not None:
            exact = self._definitions.get((key, int(workflow_version)))
            if exact:
                return exact
            policy = self._policies.get(key)
            if policy and policy.accepts(int(workflow_version)):
                compatible = self._definitions.get((key, policy.current_version))
                if compatible:
                    return compatible
            raise GraphError("GRAPH_VERSION_UNAVAILABLE", "requested graph version is unavailable")
        candidates = [definition for (name, _), definition in self._definitions.items() if name == key]
        if not candidates:
            raise GraphError("GRAPH_NOT_FOUND", "graph is not registered")
        return max(candidates, key=lambda item: item.workflow_version)

    def list(self, graph_key: str | None = None) -> tuple[GraphDefinition, ...]:
        values = tuple(self._definitions.values())
        if graph_key is not None:
            values = tuple(item for item in values if item.graph_key == graph_key)
        return tuple(sorted(values, key=lambda item: (item.graph_key, item.workflow_version)))

    register_graph = register
    get = resolve


__all__ = ["GraphDefinition", "GraphRegistry", "GraphVersionPolicy"]
