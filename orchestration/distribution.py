"""Account-gated distribution graph ports and draft-only policy."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .errors import GraphError


class DistributionPort(Protocol):
    def __call__(self, **kwargs: Any) -> Mapping[str, Any]: ...


def draft_only_distribution(*, port: DistributionPort, state: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    if context.get("real_account_evidence") is not True:
        raise GraphError("EXT_ACCOUNT_UNAVAILABLE", "distribution graph requires verified account evidence")
    if context.get("mode", "draft_only") not in {"draft_only", "simulation"}:
        raise GraphError("DISTRIBUTION_MODE_BLOCKED", "only draft_only or simulation is available in this graph")
    result = port(operation="draft_only", state=dict(state), context=dict(context))
    if not isinstance(result, Mapping):
        raise GraphError("DISTRIBUTION_RESULT_INVALID", "distribution port returned a non-object")
    return {"result_refs": {str(k): str(v) for k, v in result.items()}}


__all__ = ["DistributionPort", "draft_only_distribution"]
