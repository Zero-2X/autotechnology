"""Tenant-scoped capability matrix and adapter-only platform field mapping."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker

from .service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid


_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITY_VALIDATOR = Draft202012Validator(
    json.loads((_ROOT / "packages/contracts/jsonschema/publisher-capability.schema.json").read_text(encoding="utf-8")),
    format_checker=FormatChecker(),
)
_CANONICAL_FIELDS = {"title", "body", "tags", "disclosure", "media"}


class CapabilityMatrixError(DistributionError):
    pass


class CapabilityMatrix:
    """Immutable capability and mapping snapshot owned by an adapter boundary."""

    def __init__(self, *, capability: Mapping[str, Any], field_mapping: Mapping[str, str]) -> None:
        self.capability = deepcopy(dict(capability))
        errors = list(_CAPABILITY_VALIDATOR.iter_errors(self.capability))
        if errors:
            raise CapabilityMatrixError("INVALID_CAPABILITY", errors[0].message)
        mapping = dict(field_mapping)
        if not mapping or any(source not in _CANONICAL_FIELDS for source in mapping):
            raise CapabilityMatrixError("INVALID_FIELD_MAPPING", "mapping keys must be canonical content fields")
        if any(not isinstance(target, str) or not target.strip() for target in mapping.values()) or len(set(mapping.values())) != len(mapping):
            raise CapabilityMatrixError("INVALID_FIELD_MAPPING", "platform field names must be unique nonempty text")
        self.field_mapping = {str(source): str(target) for source, target in mapping.items()}
        self.snapshot_hash = _hash({"capability": self.capability, "field_mapping": self.field_mapping})

    @property
    def platform_id(self) -> str:
        return self.capability["platform_id"]

    @property
    def version(self) -> int:
        return self.capability["version"]

    def supports(self, action: str) -> bool:
        return action in self.capability["actions"]

    def require(self, action: str) -> None:
        if not self.supports(action):
            raise CapabilityMatrixError("CAPABILITY_UNSUPPORTED", f"capability does not support {action}")

    def map_payload(self, payload: Mapping[str, Any], *, action: str = "publish") -> dict[str, Any]:
        self.require(action)
        if not isinstance(payload, Mapping) or any(key not in _CANONICAL_FIELDS for key in payload):
            raise CapabilityMatrixError("INVALID_CANONICAL_PAYLOAD", "payload contains fields outside the canonical content boundary")
        missing = sorted(set(self.field_mapping) - set(payload))
        if missing:
            raise CapabilityMatrixError("INVALID_CANONICAL_PAYLOAD", f"payload is missing mapped fields: {missing}")
        return {self.field_mapping[key]: deepcopy(payload[key]) for key in sorted(self.field_mapping)}


class CapabilityMatrixRegistry:
    """Immutable, tenant-scoped matrix versions with auditable registration."""

    def __init__(self) -> None:
        self.matrices: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def register(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
                 capability: Mapping[str, Any], field_mapping: Mapping[str, str], registered_at: str | None = None) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        matrix = CapabilityMatrix(capability=capability, field_mapping=field_mapping)
        when = _time(registered_at, "registered_at") or _time(matrix.capability["created_at"], "capability.created_at", required=True)
        value = {"capability": deepcopy(matrix.capability), "field_mapping": deepcopy(matrix.field_mapping),
                 "snapshot_hash": matrix.snapshot_hash, "registered_at": _stamp(when)}
        digest = _hash(value)
        identity = (tenant, matrix.platform_id, matrix.version)
        with self._lock:
            prior = self._commands.get((tenant, key))
            if prior is not None:
                if prior[0] != digest:
                    raise CapabilityMatrixError("IDEMPOTENCY_KEY_REUSED", "matrix registration differs from prior request")
                return deepcopy(prior[1])
            existing = self.matrices.get(identity)
            if existing is not None:
                if existing["snapshot_hash"] != matrix.snapshot_hash:
                    raise CapabilityMatrixError("MATRIX_IMMUTABLE", "capability matrix version cannot be overwritten")
                self._commands[(tenant, key)] = (digest, deepcopy(existing))
                return deepcopy(existing)
            self.matrices[identity] = deepcopy(value)
            self._commands[(tenant, key)] = (digest, deepcopy(value))
            payload = {"platform_id": matrix.platform_id, "version": matrix.version, "snapshot_hash": matrix.snapshot_hash}
            event = {"event_id": str(uuid4()), "event_type": "distribution.capability_matrix.registered", "event_schema_version": 1,
                     "occurred_at": value["registered_at"], "org_id": tenant, "trace_id": trace,
                     "aggregate_type": "publisher_capability", "aggregate_id": matrix.capability["id"], "aggregate_version": matrix.version,
                     "actor_type": "service", "actor_id": actor, "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
            errors = list(_EVENT_VALIDATOR.iter_errors(event))
            if errors:
                raise CapabilityMatrixError("INVALID_MATRIX_EVENT", errors[0].message)
            self.events.append(event)
            self.audit.append({"event_type": event["event_type"], "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                               "output_hash": _hash(value), "snapshot_hash": matrix.snapshot_hash})
            return deepcopy(value)

    def get(self, *, org_id: UUID | str, platform_id: UUID | str, version: int) -> CapabilityMatrix:
        tenant, platform = _uuid(org_id, "org_id"), _uuid(platform_id, "platform_id")
        value = self.matrices.get((tenant, platform, version))
        if value is None:
            raise CapabilityMatrixError("TENANT_SCOPE_VIOLATION", "capability matrix is not available in organization")
        return CapabilityMatrix(capability=value["capability"], field_mapping=value["field_mapping"])


__all__ = ["CapabilityMatrix", "CapabilityMatrixError", "CapabilityMatrixRegistry"]
