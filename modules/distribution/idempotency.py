"""Intent and delivery idempotency with duplicate event consumption protection."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _hash, _text, _uuid, _validate


_ROOT = Path(__file__).resolve().parents[2]
_EVENT_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)


class DeliveryIdempotencyError(DistributionError):
    pass


class DeliveryIdempotencyService:
    """Accept immutable projections and invoke each delivery event at most once."""

    def __init__(self) -> None:
        self.intents: dict[tuple[str, str], dict[str, Any]] = {}
        self.attempts: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.events: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._event_ids: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def accept_intent(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                      intent: Mapping[str, Any]) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(intent, Mapping) or intent.get("org_id") != tenant:
            raise DeliveryIdempotencyError("TENANT_SCOPE_VIOLATION", "publication intent is outside this organization")
        value = deepcopy(dict(intent))
        _validate("publication-intent", value)
        identity = value["id"]
        digest = _hash(value)
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            existing = self.intents.get((tenant, identity))
            if existing is not None:
                if _hash(existing) != digest:
                    raise DeliveryIdempotencyError("INTENT_IMMUTABLE", "publication intent cannot be overwritten")
                result = deepcopy(existing)
            else:
                self.intents[(tenant, identity)] = deepcopy(value)
                result = deepcopy(value)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("publication.intent.accepted", tenant, actor, trace, key, digest, result)
            return result

    def accept_attempt(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                       attempt: Mapping[str, Any]) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if not isinstance(attempt, Mapping) or attempt.get("org_id") != tenant:
            raise DeliveryIdempotencyError("TENANT_SCOPE_VIOLATION", "delivery attempt is outside this organization")
        value = deepcopy(dict(attempt))
        _validate("delivery-attempt", value)
        intent_id = value["publication_intent_id"]
        if (tenant, intent_id) not in self.intents:
            raise DeliveryIdempotencyError("INTENT_NOT_FOUND", "delivery attempt requires an accepted publication intent")
        identity = (tenant, intent_id, value["attempt_no"])
        digest = _hash(value)
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            existing = self.attempts.get(identity)
            if existing is not None:
                if _hash(existing) != digest:
                    raise DeliveryIdempotencyError("DUPLICATE_DELIVERY_ATTEMPT", "intent and attempt number already contain another payload")
                result = deepcopy(existing)
            else:
                self.attempts[identity] = deepcopy(value)
                result = deepcopy(value)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("delivery.attempt.accepted", tenant, actor, trace, key, digest, result)
            return result

    def consume_event(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                      envelope: Mapping[str, Any], handler: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id")
        if not isinstance(envelope, Mapping) or envelope.get("org_id") != tenant:
            raise DeliveryIdempotencyError("TENANT_SCOPE_VIOLATION", "event is outside this organization")
        value = deepcopy(dict(envelope))
        errors = list(_EVENT_VALIDATOR.iter_errors(value))
        if errors:
            raise DeliveryIdempotencyError("INVALID_DELIVERY_EVENT", errors[0].message)
        event_id, key = value["event_id"], value["idempotency_key"]
        digest = _hash(value)
        with self._lock:
            prior_event_digest = self._event_ids.get((tenant, event_id))
            if prior_event_digest is not None:
                if prior_event_digest != digest:
                    raise DeliveryIdempotencyError("EVENT_ID_REUSED", "event_id was reused with a different payload")
                return deepcopy(self.events[(tenant, event_id)])
            prior_key = self._commands.get((tenant, key))
            if prior_key is not None:
                if prior_key[0] != digest:
                    raise DeliveryIdempotencyError("IDEMPOTENCY_KEY_REUSED", "event idempotency key was reused with a different payload")
                return deepcopy(prior_key[1])
            handler_result = deepcopy(dict(handler(value) or {})) if handler is not None else {}
            result = {"event_id": event_id, "accepted": True, "handler_result": handler_result,
                      "event_type": value["event_type"], "aggregate_id": value["aggregate_id"]}
            self.events[(tenant, event_id)] = deepcopy(result)
            self._event_ids[(tenant, event_id)] = digest
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("delivery.event.consumed", tenant, actor, trace, key, digest, result)
            return result

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise DeliveryIdempotencyError("IDEMPOTENCY_KEY_REUSED", "command differs from prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str, digest: str, output: Mapping[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                           "idempotency_key": key, "input_hash": digest, "output_hash": _hash(output)})


__all__ = ["DeliveryIdempotencyError", "DeliveryIdempotencyService"]
