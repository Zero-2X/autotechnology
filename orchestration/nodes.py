"""Thin graph nodes that call injected application ports only."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping, Protocol

from .errors import GraphError


class UseCasePort(Protocol):
    def __call__(self, **kwargs: Any) -> Mapping[str, Any]: ...


def _refs(value: Mapping[str, Any]) -> dict[str, str]:
    result = value.get("refs", value.get("result_refs", {}))
    if not isinstance(result, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in result.items()):
        raise GraphError("NODE_OUTPUT_INVALID", "application port must return string references")
    return dict(result)


def _call_port(port: UseCasePort, *, state: Mapping[str, Any], operation: str, context: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = port(state=deepcopy(dict(state)), operation=operation, context=deepcopy(dict(context)))
    except TypeError:
        result = port(deepcopy(dict(state)))
    if not isinstance(result, Mapping):
        raise GraphError("NODE_OUTPUT_INVALID", f"{operation} port returned a non-object")
    refs = _refs(result)
    return {"artifact_refs": {**dict(state.get("artifact_refs", {})), **refs},
            "result_refs": {**dict(state.get("result_refs", {})), **refs}}


def topic_signal_to_brief(*, port: UseCasePort, state: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _call_port(port, state=state, operation="topic_signal_to_brief", context=context or {})


def source_rights_knowledge_canonical(*, port: UseCasePort, state: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _call_port(port, state=state, operation="source_rights_knowledge_canonical", context=context or {})


def variant_qa_geo(*, port: UseCasePort, state: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _call_port(port, state=state, operation="variant_qa_geo", context=context or {})


def approval_interrupt(*, port: UseCasePort, state: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _call_port(port, state=state, operation="approval", context=context or {})


def manual_export(*, port: UseCasePort, state: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _call_port(port, state=state, operation="manual_export", context=context or {})


def fake_official_adapter(*, port: UseCasePort, state: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return _call_port(port, state=state, operation="fake_official_adapter", context=context or {})


__all__ = [
    "UseCasePort", "approval_interrupt", "fake_official_adapter", "manual_export",
    "source_rights_knowledge_canonical", "topic_signal_to_brief", "variant_qa_geo",
]
