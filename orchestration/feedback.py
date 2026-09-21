"""Account-free Observation to Feedback Recommendation graph port."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .errors import GraphError


class FeedbackPort(Protocol):
    def __call__(self, **kwargs: Any) -> Mapping[str, Any]: ...


def observation_to_feedback(*, observation_port: FeedbackPort, recommendation_port: FeedbackPort,
                            state: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    observation_ref = state.get("artifact_refs", {}).get("observation")
    if not isinstance(observation_ref, str):
        raise GraphError("OBSERVATION_REF_REQUIRED", "feedback graph requires an observation reference")
    observation = observation_port(org_id=context.get("org_id"), observation_ref=observation_ref, context=dict(context))
    if not isinstance(observation, Mapping) or str(observation.get("source")) == "platform" and context.get("real_account_evidence") is not True:
        raise GraphError("EXT_ACCOUNT_UNAVAILABLE", "platform feedback requires verified account evidence")
    recommendation = recommendation_port(observation=dict(observation), context=dict(context))
    if not isinstance(recommendation, Mapping):
        raise GraphError("FEEDBACK_RESULT_INVALID", "recommendation port returned an invalid result")
    refs = {str(k): str(v) for k, v in recommendation.items() if isinstance(v, str)}
    return {"result_refs": refs, "artifact_refs": {**dict(state.get("artifact_refs", {})), **refs}}


__all__ = ["FeedbackPort", "observation_to_feedback"]
