"""Replay guards for external side effects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import GraphError


@dataclass(frozen=True)
class PublicationIntent:
    intent_key: str
    org_id: str
    target_version_ref: str
    policy_ref: str
    status: str = "planned"


class ReplayGuard:
    def __init__(self) -> None:
        self.intents: dict[tuple[str, str], PublicationIntent] = {}
        self.provider_requests: dict[tuple[str, str], dict[str, Any]] = {}

    def create_intent(self, *, org_id: str, intent_key: str, target_version_ref: str,
                      policy_ref: str) -> PublicationIntent:
        key = (str(org_id), str(intent_key))
        existing = self.intents.get(key)
        candidate = PublicationIntent(str(intent_key), str(org_id), str(target_version_ref), str(policy_ref))
        if existing is not None:
            if existing != candidate:
                raise GraphError("INTENT_KEY_REUSED", "publication intent differs from existing intent")
            return existing
        self.intents[key] = candidate
        return candidate

    def provider_call(self, *, org_id: str, provider_key: str, intent_key: str,
                      payload_hash: str, call: Any) -> dict[str, Any]:
        key = (str(org_id), str(provider_key) + ":" + str(intent_key))
        prior = self.provider_requests.get(key)
        if prior is not None:
            if prior["payload_hash"] != payload_hash:
                raise GraphError("PROVIDER_IDEMPOTENCY_CONFLICT", "provider request payload differs")
            return dict(prior["result"])
        result = call()
        if not isinstance(result, Mapping):
            raise GraphError("PROVIDER_RESULT_INVALID", "provider result must be an object")
        saved = {"payload_hash": payload_hash, "result": dict(result), "side_effect_count": 1}
        self.provider_requests[key] = saved
        return dict(result)

    def replay(self, *, org_id: str, intent_key: str) -> dict[str, Any]:
        intent = self.intents.get((str(org_id), str(intent_key)))
        if intent is None:
            raise GraphError("INTENT_NOT_FOUND", "publication intent is not available")
        requests = [value for (tenant, key), value in self.provider_requests.items() if tenant == str(org_id) and key.endswith(":" + str(intent_key))]
        return {"intent": intent, "provider_calls": len(requests), "side_effect_replayed": False}


__all__ = ["PublicationIntent", "ReplayGuard"]
