"""Graph topology validation and regression fingerprinting."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from .errors import GraphError


def validate_topology(edges: Mapping[str, Iterable[str]], *, required_nodes: Iterable[str] = ()) -> dict[str, Any]:
    graph = {str(node): tuple(str(child) for child in children) for node, children in edges.items()}
    nodes = set(graph) | {child for children in graph.values() for child in children}
    missing = set(required_nodes) - nodes
    if missing: raise GraphError("TOPOLOGY_INVALID", f"required nodes are missing: {sorted(missing)}")
    visiting: set[str] = set(); visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting: raise GraphError("TOPOLOGY_CYCLE", "graph topology contains a cycle")
        if node in visited: return
        visiting.add(node)
        for child in graph.get(node, ()): visit(child)
        visiting.remove(node); visited.add(node)
    for node in sorted(nodes): visit(node)
    canonical = {key: sorted(value) for key, value in sorted(graph.items())}
    return {"nodes": sorted(nodes), "edges": canonical,
            "fingerprint": sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


__all__ = ["validate_topology"]
