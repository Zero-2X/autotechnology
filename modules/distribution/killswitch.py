"""Credential-free Distribution kill switches for DIST-008B.

The foundation control plane owns durable global controls.  This module keeps
the Distribution boundary independently testable and adds platform/account/
target scope matching before an Intent can create a delivery attempt.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .service import DistributionError, _EVENT_VALIDATOR, _hash, _stamp, _text, _time, _uuid


_ROOT = Path(__file__).resolve().parents[2]
_KILL_SWITCH_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/kill-switch.schema.json").read_text(encoding="utf-8"))
_DELIVERY_MODE_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/delivery-mode.schema.json").read_text(encoding="utf-8"))
_KILL_SWITCH_REGISTRY = Registry().with_resource(_KILL_SWITCH_SCHEMA["$id"], Resource.from_contents(_KILL_SWITCH_SCHEMA)).with_resource(
    _DELIVERY_MODE_SCHEMA["$id"], Resource.from_contents(_DELIVERY_MODE_SCHEMA)
)
_KILL_SWITCH_VALIDATOR = Draft202012Validator(_KILL_SWITCH_SCHEMA, registry=_KILL_SWITCH_REGISTRY, format_checker=FormatChecker())
_MODES = ("manual_export", "simulation", "draft_only", "authorized_api")


class KillSwitchError(DistributionError):
    """Stable errors for Distribution side-effect gates."""


class DistributionKillSwitchService:
    """Manage immutable, idempotent kill-switch lifecycle projections."""

    rule_version = "dist-008b/v1"

    def __init__(self) -> None:
        self.switches: dict[tuple[str, str, str | None], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = RLock()

    def set_kill_switch(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        scope: str, paused: bool, reason: str, expected_version: int,
        scope_id: UUID | str | None = None, blocked_delivery_modes: Sequence[str] | None = None,
        changed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if scope not in {"global", "platform", "account", "target"}:
            raise KillSwitchError("INVALID_KILL_SWITCH_SCOPE", "scope must be global, platform, account or target")
        if type(paused) is not bool or type(expected_version) is not int or expected_version < 0:
            raise KillSwitchError("INVALID_KILL_SWITCH_INPUT", "paused and expected_version are invalid")
        why = _text(reason, "reason", 512)
        identity = None if scope == "global" else _uuid(scope_id, "scope_id")
        modes = list(_MODES if blocked_delivery_modes is None and paused else blocked_delivery_modes or [])
        if len(set(modes)) != len(modes) or any(mode not in _MODES for mode in modes):
            raise KillSwitchError("INVALID_KILL_SWITCH_INPUT", "blocked_delivery_modes contains an unsupported mode")
        at = _time(changed_at, "changed_at") or datetime.now(timezone.utc)
        lookup = ("*" if scope == "global" else tenant, scope, identity)
        current = self.switches.get(lookup)
        current_version = current["version"] if current else 0
        status = "paused" if paused else "active"
        digest = _hash({"operation": "set_kill_switch", "scope": scope, "scope_id": identity,
                        "paused": paused, "reason": why, "expected_version": expected_version,
                        "blocked_delivery_modes": modes, "changed_at": _stamp(at)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if expected_version != current_version:
                raise KillSwitchError("VERSION_CONFLICT", "kill switch version does not match expected_version")
            switch_id = current["id"] if current else str(uuid5(NAMESPACE_URL, f"distribution-kill-switch:{scope}:{identity or 'global'}"))
            value = {"id": switch_id, "org_id": None if scope == "global" else tenant, "scope": scope,
                     "scope_id": identity, "status": status, "reason": why, "changed_by": actor,
                     "changed_at": _stamp(at), "version": current_version + 1,
                     "blocked_delivery_modes": modes if paused else []}
            errors = sorted(_KILL_SWITCH_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
            if errors:
                raise KillSwitchError("INVALID_KILL_SWITCH", errors[0].message)
            self.switches[lookup] = deepcopy(value)
            self._commands[(tenant, key)] = (digest, deepcopy(value))
            self.audit.append({"event_type": f"distribution.kill_switch.{status}", "org_id": tenant,
                               "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                               "input_hash": digest, "output_hash": _hash(value), "scope": scope,
                               "scope_id": identity, "version": value["version"]})
            self._event(f"kill_switch.{'paused' if paused else 'resumed'}", tenant, actor, trace, key,
                        value, at)
            return deepcopy(value)

    def get_kill_switch(self, *, org_id: UUID | str, scope: str = "global",
                        scope_id: UUID | str | None = None) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        if scope not in {"global", "platform", "account", "target"}:
            raise KillSwitchError("INVALID_KILL_SWITCH_SCOPE", "scope is invalid")
        identity = None if scope == "global" else _uuid(scope_id, "scope_id")
        current = self.switches.get(("*" if scope == "global" else tenant, scope, identity))
        if current is not None:
            return deepcopy(current)
        return {
            "id": str(uuid5(NAMESPACE_URL, f"distribution-kill-switch:{scope}:{identity or 'global'}")),
            "org_id": None if scope == "global" else tenant, "scope": scope, "scope_id": identity,
            "status": "active", "reason": "default active", "changed_by": "00000000-0000-4000-8000-000000000008",
            "changed_at": "1970-01-01T00:00:00Z", "version": 0, "blocked_delivery_modes": [],
        }

    def guard(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        delivery_mode: str, requires_side_effect: bool, platform_id: UUID | str | None = None,
        account_connection_id: UUID | str | None = None, target_id: UUID | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        if delivery_mode not in _MODES or type(requires_side_effect) is not bool:
            raise KillSwitchError("INVALID_DELIVERY_MODE", "delivery_mode or requires_side_effect is invalid")
        platform = None if platform_id is None else _uuid(platform_id, "platform_id")
        account = None if account_connection_id is None else _uuid(account_connection_id, "account_connection_id")
        target = None if target_id is None else _uuid(target_id, "target_id")
        matches = [("global", None, self.get_kill_switch(org_id=tenant))]
        if platform is not None:
            matches.append(("platform", platform, self.get_kill_switch(org_id=tenant, scope="platform", scope_id=platform)))
        if account is not None:
            matches.append(("account", account, self.get_kill_switch(org_id=tenant, scope="account", scope_id=account)))
        if target is not None:
            matches.append(("target", target, self.get_kill_switch(org_id=tenant, scope="target", scope_id=target)))
        paused = [(scope, identity, switch) for scope, identity, switch in matches
                  if switch["status"] == "paused" and delivery_mode in switch["blocked_delivery_modes"]]
        digest = _hash({"operation": "guard", "delivery_mode": delivery_mode, "requires_side_effect": requires_side_effect,
                        "platform_id": platform, "account_connection_id": account, "target_id": target,
                        "paused": [(scope, identity, item["version"]) for scope, identity, item in paused]})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                if not prior["allowed"]:
                    raise KillSwitchError(prior["code"], "delivery mode is blocked by a kill switch")
                return prior
            blocked = bool(paused) and requires_side_effect
            result = {"allowed": not blocked, "code": "KILL_SWITCH_PAUSED" if blocked else "ALLOWED",
                      "delivery_mode": delivery_mode, "matched_scopes": [scope for scope, _, _ in paused],
                      "side_effect_blocked": blocked, "trace_id": trace}
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self.audit.append({"event_type": "distribution.kill_switch.guard", "org_id": tenant, "actor_id": actor,
                               "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                               "output_hash": _hash(result), "decision": result["code"],
                               "delivery_mode": delivery_mode})
            if blocked:
                raise KillSwitchError("KILL_SWITCH_PAUSED", "delivery mode is blocked by a kill switch")
            return result

    def _prior(self, tenant: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise KillSwitchError("IDEMPOTENCY_KEY_REUSED", "kill-switch command differs from prior request")
        return deepcopy(prior[1])

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str,
               switch: Mapping[str, Any], occurred_at: datetime) -> None:
        payload = {"aggregate_id": switch["id"], "aggregate_version": switch["version"],
                   "from_state": "active" if switch["status"] == "paused" else "paused",
                   "to_state": switch["status"], "command": "pause" if switch["status"] == "paused" else "resume",
                   "reason": switch["reason"]}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": "KillSwitch", "aggregate_id": switch["id"],
                 "aggregate_version": switch["version"], "actor_type": "service", "actor_id": actor,
                 "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise KillSwitchError("INVALID_KILL_SWITCH_EVENT", errors[0].message)
        self.events.append(deepcopy(event))


__all__ = ["DistributionKillSwitchService", "KillSwitchError"]
