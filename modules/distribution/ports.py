"""Separated distribution ports and immutable publisher capability snapshots."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4
from hashlib import sha256

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITY_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/publisher-capability.schema.json").read_text(encoding="utf-8"))
_EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))
_CAPABILITY_VALIDATOR = Draft202012Validator(_CAPABILITY_SCHEMA, format_checker=FormatChecker())
_EVENT_VALIDATOR = Draft202012Validator(_EVENT_SCHEMA, format_checker=FormatChecker())


class DistributionPortError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConnectionPort(Protocol):
    def inspect(self, *, context: Any, connection_id: str) -> Mapping[str, Any]: ...


class PublisherPort(Protocol):
    def publish(self, *, context: Any, publication_intent: Mapping[str, Any], idempotency_key: str) -> Mapping[str, Any]: ...


class InboxPort(Protocol):
    def receive(self, *, context: Any, cursor: str | None = None) -> tuple[Mapping[str, Any], ...]: ...


class WebhookPort(Protocol):
    def receive(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, platform_id: UUID | str, external_event_id: str,
        raw_payload: Mapping[str, Any], signature: str, received_at: str | None = None,
        handler: Callable[[Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
    ) -> Mapping[str, Any]: ...


class MetricsPort(Protocol):
    def emit(self, *, context: Any, name: str, value: float, labels: Mapping[str, str]) -> None: ...


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise DistributionPortError("INVALID_PORT_INPUT", f"{name} must be a UUID") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DistributionPortError("INVALID_PORT_INPUT", f"{name} must be nonempty text")
    return value.strip()


class DistributionPortSet:
    """Bind four independently owned ports and reject a mixed responsibility adapter."""

    def __init__(self, *, connection: ConnectionPort, publisher: PublisherPort,
                 inbox: InboxPort, metrics: MetricsPort) -> None:
        values = {"connection": connection, "publisher": publisher, "inbox": inbox, "metrics": metrics}
        required = {"connection": "inspect", "publisher": "publish", "inbox": "receive", "metrics": "emit"}
        for role, method in required.items():
            if not callable(getattr(values[role], method, None)):
                raise DistributionPortError("PORT_METHOD_MISSING", f"{role} must expose {method}()")
        if len({id(value) for value in values.values()}) != len(values):
            raise DistributionPortError("PORT_RESPONSIBILITIES_MIXED", "connection, publisher, inbox and metrics require separate adapters")
        self.connection, self.publisher, self.inbox, self.metrics = connection, publisher, inbox, metrics


class PublisherCapabilityRegistry:
    """Store schema-validated, immutable publisher capability versions per tenant."""

    def __init__(self) -> None:
        self.capabilities: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def register(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        capability: Mapping[str, Any], registered_at: str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key")
        if not isinstance(capability, Mapping):
            raise DistributionPortError("INVALID_CAPABILITY", "capability must be an object")
        value = deepcopy(dict(capability))
        value.setdefault("created_at", registered_at)
        if value["created_at"] is None:
            raise DistributionPortError("INVALID_CAPABILITY", "created_at is required")
        errors = sorted(_CAPABILITY_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            raise DistributionPortError("INVALID_CAPABILITY", errors[0].message)
        digest = _hash(value)
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise DistributionPortError("IDEMPOTENCY_KEY_REUSED", "capability command differs from prior request")
                return deepcopy(prior[1])
            identity = (tenant, value["id"], value["version"])
            existing = self.capabilities.get(identity)
            if existing is not None:
                if _hash(existing) != digest:
                    raise DistributionPortError("CAPABILITY_IMMUTABLE", "capability version cannot be overwritten")
                self._commands[(tenant, key)] = (digest, deepcopy(existing))
                return deepcopy(existing)
            self.capabilities[identity] = deepcopy(value)
            self._commands[(tenant, key)] = (digest, deepcopy(value))
            event = {
                "event_id": str(uuid4()), "event_type": "publisher.capability.registered", "event_schema_version": 1,
                "occurred_at": value["created_at"], "org_id": tenant, "trace_id": trace,
                "aggregate_type": "publisher_capability", "aggregate_id": value["id"], "aggregate_version": value["version"],
                "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                "payload": {"capability_id": value["id"], "version": value["version"], "policy_version": value["policy_version"]},
                "payload_hash": _hash({"capability_id": value["id"], "version": value["version"], "policy_version": value["policy_version"]}),
            }
            event_errors = list(_EVENT_VALIDATOR.iter_errors(event))
            if event_errors:
                raise DistributionPortError("INVALID_CAPABILITY_EVENT", event_errors[0].message)
            self.events.append(event)
            self.audit.append({"event_type": "publisher.capability.registered", "org_id": tenant,
                               "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                               "input_hash": digest, "output_hash": _hash(value), "capability_id": value["id"],
                               "version": value["version"]})
            return deepcopy(value)

    def get(self, *, org_id: UUID | str, capability_id: UUID | str, version: int) -> dict[str, Any]:
        tenant, identity = _uuid(org_id, "org_id"), _uuid(capability_id, "capability_id")
        if type(version) is not int or version < 1:
            raise DistributionPortError("INVALID_PORT_INPUT", "version must be positive")
        value = self.capabilities.get((tenant, identity, version))
        if value is None:
            raise DistributionPortError("TENANT_SCOPE_VIOLATION", "publisher capability is not available in organization")
        return deepcopy(value)


__all__ = [
    "ConnectionPort", "DistributionPortError", "DistributionPortSet", "InboxPort", "MetricsPort", "WebhookPort",
    "PublisherCapabilityRegistry", "PublisherPort",
]
