"""Optional real LangGraph composition root for the V3 port boundary.

The domain-facing runner remains dependency-free and owns the business
contract.  This module is the only place that constructs a real
``StateGraph``.  It receives already validated nodes and keeps all provider,
database, and platform work behind the injected ports used by those nodes.
"""

from __future__ import annotations

import inspect
from typing import Any, Mapping

from .errors import GraphError
from .registry import GraphDefinition
from .state import ContentGraphState, StateViolation, validate_state


try:  # Keep importing the dependency explicit and fail with a useful message.
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
except ImportError as exc:  # pragma: no cover - exercised in dependency-free installs
    raise ImportError(
        "real LangGraph composition requires requirements-v3.lock; "
        "the dependency-free GraphRunner remains available for CI"
    ) from exc


def _call_node(node: Any, state: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any] | None:
    try:
        parameters = inspect.signature(node).parameters
    except (TypeError, ValueError):
        return node(state, context)
    return node(state, context) if len(parameters) >= 2 else node(state)


def _node_name(node: Any, index: int) -> str:
    base = getattr(node, "__name__", "node") or "node"
    return f"{index:02d}_{base}"


class LangGraphExecutable:
    """Compiled StateGraph with optional in-memory checkpoint persistence."""

    def __init__(self, definition: GraphDefinition, compiled: Any, *, context: Mapping[str, Any]) -> None:
        self.definition = definition
        self.compiled = compiled
        self.context = dict(context)

    def invoke(self, state: Mapping[str, Any], *, thread_id: str | None = None) -> dict[str, Any]:
        validated = validate_state(state)
        _prepare_langchain_debug_compat()
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = self.compiled.invoke(validated, config=config) if config else self.compiled.invoke(validated)
        if not isinstance(result, Mapping):
            raise GraphError("GRAPH_OUTPUT_INVALID", "LangGraph returned a non-object state")
        try:
            return validate_state(result)
        except StateViolation as exc:
            raise GraphError("STATE_INVALID", str(exc)) from exc


def _prepare_langchain_debug_compat() -> None:
    """Bridge LangChain Core's legacy debug lookup across partial installs.

    LangChain Core imports an optional top-level ``langchain`` module while
    configuring callbacks.  In a provider-profile install that module may be
    absent; under pytest, a namespace package named ``langchain`` can also be
    supplied by the test directory.  Core 0.3.x expects that module to expose
    ``debug`` in either case.  Supplying the documented false default keeps the
    adapter deterministic without importing or requiring the full LangChain
    distribution.
    """
    try:
        import langchain
    except ImportError:
        return
    if not hasattr(langchain, "debug"):
        langchain.debug = False


def compile_langgraph(
    definition: GraphDefinition,
    *,
    context: Mapping[str, Any] | None = None,
    checkpointer: Any | None = None,
) -> LangGraphExecutable:
    """Compile a registered definition into an actual LangGraph StateGraph."""
    nodes = definition.nodes or ((definition.entrypoint,) if definition.entrypoint else ())
    if not nodes:
        raise GraphError("GRAPH_DEFINITION_INVALID", "a LangGraph definition requires nodes or an entrypoint")
    graph = StateGraph(ContentGraphState)
    names: list[str] = []
    bound_context = dict(context or {})
    for index, node in enumerate(nodes, start=1):
        if not callable(node):
            raise GraphError("GRAPH_DEFINITION_INVALID", "graph nodes must be callable")
        name = _node_name(node, index)
        names.append(name)

        def invoke_node(state: Mapping[str, Any], _node: Any = node) -> Mapping[str, Any] | None:
            current = validate_state(state)
            output = _call_node(_node, current, bound_context)
            if output is None:
                return None
            if not isinstance(output, Mapping):
                raise GraphError("NODE_OUTPUT_INVALID", "node output must be an object")
            merged = dict(current)
            for key, value in output.items():
                if key in {"artifact_refs", "result_refs"} and isinstance(value, Mapping):
                    merged[key] = {**dict(merged.get(key, {})), **dict(value)}
                elif key in {"evidence_refs", "qa_refs"} and isinstance(value, (list, tuple)):
                    merged[key] = list(dict.fromkeys([*merged.get(key, []), *value]))
                else:
                    merged[key] = value
            return validate_state(merged)

        graph.add_node(name, invoke_node)
    graph.add_edge(START, names[0])
    for previous, current in zip(names, names[1:]):
        graph.add_edge(previous, current)
    graph.add_edge(names[-1], END)
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    compiled = graph.compile(checkpointer=saver)
    return LangGraphExecutable(definition, compiled, context=bound_context)


__all__ = ["LangGraphExecutable", "compile_langgraph"]
