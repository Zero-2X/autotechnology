"""Account-free content graph topology assembled from injected ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .nodes import (
    UseCasePort, approval_interrupt, fake_official_adapter, manual_export,
    source_rights_knowledge_canonical, topic_signal_to_brief, variant_qa_geo,
)
from .registry import GraphDefinition, GraphRegistry


@dataclass(frozen=True)
class ContentGraphPorts:
    topic: UseCasePort
    provenance: UseCasePort
    quality: UseCasePort
    approval: UseCasePort
    manual_export: UseCasePort
    fake_adapter: UseCasePort


def build_content_graph(*, registry: GraphRegistry, ports: ContentGraphPorts,
                        graph_key: str = "content_pipeline", workflow_version: int = 1) -> GraphDefinition:
    """Register the M1 account-free vertical slice.

    Each closure receives only bounded state and context; domain writes stay in
    the injected application ports.  The final two nodes are explicit
    simulation/manual paths and never call a real platform.
    """
    def topic(state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return topic_signal_to_brief(port=ports.topic, state=state, context=context)

    def provenance(state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return source_rights_knowledge_canonical(port=ports.provenance, state=state, context=context)

    def quality(state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return variant_qa_geo(port=ports.quality, state=state, context=context)

    def approval(state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return approval_interrupt(port=ports.approval, state=state, context=context)

    def export(state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return manual_export(port=ports.manual_export, state=state, context=context)

    def fake(state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return fake_official_adapter(port=ports.fake_adapter, state=state, context=context)

    definition = GraphDefinition(graph_key, workflow_version, nodes=(topic, provenance, quality, approval, export, fake),
                                 state_version=1, metadata={"mode": "account_free", "side_effects": "simulation_only"})
    return registry.register(definition)


__all__ = ["ContentGraphPorts", "build_content_graph"]
