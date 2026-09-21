"""Transactional FOUND-008 feature flags and global side-effect kill switch."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID, uuid4

from .observability import TenantContext
from .outbox import EventEnvelope, OutboxStore


GLOBAL_KILL_SWITCH_ID = "00000000-0000-4000-8000-000000000008"
_FLAG_KEY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class DeliveryMode(StrEnum):
    MANUAL_EXPORT = "manual_export"
    SIMULATION = "simulation"
    DRAFT_ONLY = "draft_only"
    AUTHORIZED_API = "authorized_api"


DEFAULT_DELIVERY_FLAGS = {
    DeliveryMode.MANUAL_EXPORT: True,
    DeliveryMode.SIMULATION: True,
    DeliveryMode.DRAFT_ONLY: False,
    DeliveryMode.AUTHORIZED_API: False,
}


class ControlPlaneError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = False


class SideEffectRejected(ControlPlaneError):
    pass


class DBAPIConnection(Protocol):
    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


def _required(value: object, name: str, *, limit: int = 512) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or len(text) > limit or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ControlPlaneError("INVALID_CONTROL_COMMAND", f"{name} is invalid")
    return text


def _uuid(value: object, name: str) -> str:
    try:
        return str(UUID(_required(value, name, limit=64)))
    except ValueError as exc:
        raise ControlPlaneError("INVALID_CONTROL_COMMAND", f"{name} must be a UUID") from exc


def _timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ControlPlaneError("INVALID_CONTROL_COMMAND", "now must include a timezone")
    return current.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _json_hash(value: Mapping[str, Any]) -> tuple[str, str]:
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ControlPlaneError("INVALID_CONTROL_COMMAND", "command must be JSON serializable") from exc
    return encoded, sha256(encoded.encode("utf-8")).hexdigest()


def _identity(context: TenantContext) -> tuple[str, str, str]:
    if context.org_id is None or context.actor_id is None:
        raise ControlPlaneError("IDENTITY_REQUIRED", "org_id and actor_id are required")
    return _uuid(context.org_id, "org_id"), _uuid(context.actor_id, "actor_id"), _required(context.trace_id, "trace_id", limit=256)


@dataclass(frozen=True)
class FeatureFlag:
    org_id: str
    flag_key: str
    enabled: bool
    version: int
    reason: str
    changed_by: str
    changed_at: str


@dataclass(frozen=True)
class KillSwitch:
    id: str
    status: str
    version: int
    reason: str
    changed_by: str
    changed_at: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": self.id, "org_id": None, "scope": "global", "scope_id": None,
            "status": self.status, "version": self.version, "reason": self.reason,
            "changed_by": self.changed_by, "changed_at": self.changed_at,
            "blocked_delivery_modes": [mode.value for mode in DeliveryMode] if self.status == "paused" else [],
        }


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    code: str
    delivery_mode: str
    kill_switch_status: str
    feature_enabled: bool
    audit_id: str
    replayed: bool = False


class ControlPlaneStore:
    def __init__(
        self, connection: DBAPIConnection, *, dialect: str = "sqlite",
        global_authorizer: Callable[[TenantContext], bool] | None = None,
    ) -> None:
        if dialect not in {"sqlite", "postgresql"}:
            raise ValueError("dialect must be sqlite or postgresql")
        self.connection = connection
        self.dialect = dialect
        self.global_authorizer = global_authorizer

    def _execute(self, sql: str, parameters: tuple[object, ...] = ()) -> Any:
        return self.connection.execute(sql.replace("?", "%s") if self.dialect == "postgresql" else sql, parameters)

    def _begin(self) -> None:
        if self.dialect == "sqlite" and not getattr(self.connection, "in_transaction", False):
            self._execute("BEGIN IMMEDIATE")

    def _command(self, org_id: str, key: str, command_type: str, payload_hash: str) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT command_type, payload_hash, response_json FROM foundation_control_commands WHERE org_id = ? AND idempotency_key = ?",
            (org_id, key),
        ).fetchone()
        if row is None:
            return None
        if row[0] != command_type or row[1] != payload_hash:
            raise ControlPlaneError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with a different command")
        return json.loads(row[2])

    def _save_command(self, org_id: str, key: str, command_type: str, payload_hash: str, response: Mapping[str, Any], now: str) -> None:
        self._execute(
            "INSERT INTO foundation_control_commands VALUES (?, ?, ?, ?, ?, ?)",
            (org_id, key, command_type, payload_hash, json.dumps(dict(response), sort_keys=True, separators=(",", ":")), now),
        )

    def _audit(
        self, *, org_id: str, trace_id: str, actor_id: str, action: str,
        subject_type: str, subject_id: str, decision: str, reason: str,
        input_version: int | None, output_version: int | None,
        policy_snapshot: Mapping[str, Any], payload_hash: str,
        idempotency_key: str, occurred_at: str,
    ) -> str:
        audit_id = str(uuid4())
        self._execute(
            "INSERT INTO foundation_control_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (audit_id, org_id, trace_id, actor_id, action, subject_type, subject_id, decision, reason,
             input_version, output_version, json.dumps(dict(policy_snapshot), sort_keys=True, separators=(",", ":")),
             payload_hash, idempotency_key, 0, "0", occurred_at),
        )
        return audit_id

    def get_feature_flag(self, org_id: str, flag_key: str) -> FeatureFlag | None:
        tenant, key = _uuid(org_id, "org_id"), _required(flag_key, "flag_key", limit=128)
        if not _FLAG_KEY_RE.fullmatch(key):
            raise ControlPlaneError("INVALID_CONTROL_COMMAND", "flag_key is invalid")
        row = self._execute(
            "SELECT org_id, flag_key, enabled, version, reason, changed_by, changed_at FROM foundation_feature_flags WHERE org_id = ? AND flag_key = ?",
            (tenant, key),
        ).fetchone()
        return FeatureFlag(str(row[0]), str(row[1]), bool(row[2]), int(row[3]), str(row[4]), str(row[5]), str(row[6])) if row else None

    def set_feature_flag(
        self, *, context: TenantContext, flag_key: str, enabled: bool, reason: str,
        expected_version: int, idempotency_key: str, now: datetime | None = None,
    ) -> FeatureFlag:
        org_id, actor_id, trace_id = _identity(context)
        key = _required(flag_key, "flag_key", limit=128)
        if not _FLAG_KEY_RE.fullmatch(key) or type(enabled) is not bool or type(expected_version) is not int or expected_version < 0:
            raise ControlPlaneError("INVALID_CONTROL_COMMAND", "feature flag command is invalid")
        why, idem, at = _required(reason, "reason"), _required(idempotency_key, "idempotency_key", limit=256), _timestamp(now)
        _, payload_hash = _json_hash({"flag_key": key, "enabled": enabled, "reason": why, "expected_version": expected_version})
        try:
            self._begin()
            replay = self._command(org_id, idem, "set_feature_flag", payload_hash)
            if replay is not None:
                self.connection.commit()
                return FeatureFlag(**replay)
            current = self.get_feature_flag(org_id, key)
            version = current.version if current else 0
            if version != expected_version:
                raise ControlPlaneError("CONTROL_VERSION_CONFLICT", "feature flag version does not match")
            updated = FeatureFlag(org_id, key, enabled, version + 1, why, actor_id, at)
            self._execute(
                "INSERT INTO foundation_feature_flags VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(org_id, flag_key) DO UPDATE SET enabled = excluded.enabled, version = excluded.version, reason = excluded.reason, changed_by = excluded.changed_by, changed_at = excluded.changed_at",
                (org_id, key, enabled, updated.version, why, actor_id, at),
            )
            self._audit(org_id=org_id, trace_id=trace_id, actor_id=actor_id, action="feature_flag.changed",
                        subject_type="FeatureFlag", subject_id=key, decision="changed", reason=why,
                        input_version=version or None, output_version=updated.version,
                        policy_snapshot={"flag_key": key, "enabled": enabled}, payload_hash=payload_hash,
                        idempotency_key=idem, occurred_at=at)
            self._save_command(org_id, idem, "set_feature_flag", payload_hash, asdict(updated), at)
            self.connection.commit()
            return updated
        except Exception:
            self.connection.rollback()
            raise

    def get_kill_switch(self) -> KillSwitch:
        row = self._execute(
            "SELECT id, status, version, reason, changed_by, changed_at FROM foundation_kill_switch WHERE id = ?",
            (GLOBAL_KILL_SWITCH_ID,),
        ).fetchone()
        return KillSwitch(*(str(value) if index != 2 else int(value) for index, value in enumerate(row))) if row else KillSwitch(GLOBAL_KILL_SWITCH_ID, "active", 0, "default active", GLOBAL_KILL_SWITCH_ID, "1970-01-01T00:00:00+00:00")

    def set_global_kill_switch(
        self, *, context: TenantContext, paused: bool, reason: str,
        expected_version: int, idempotency_key: str, now: datetime | None = None,
    ) -> KillSwitch:
        org_id, actor_id, trace_id = _identity(context)
        if self.global_authorizer is None or self.global_authorizer(context) is not True:
            raise ControlPlaneError("GLOBAL_CONTROL_FORBIDDEN", "actor is not authorized for global controls")
        if type(paused) is not bool or type(expected_version) is not int or expected_version < 0:
            raise ControlPlaneError("INVALID_CONTROL_COMMAND", "kill switch command is invalid")
        why, idem, at = _required(reason, "reason"), _required(idempotency_key, "idempotency_key", limit=256), _timestamp(now)
        target = "paused" if paused else "active"
        _, payload_hash = _json_hash({"paused": paused, "reason": why, "expected_version": expected_version})
        try:
            self._begin()
            replay = self._command(org_id, idem, "set_global_kill_switch", payload_hash)
            if replay is not None:
                self.connection.commit()
                return KillSwitch(**replay)
            current = self.get_kill_switch()
            if current.version != expected_version:
                raise ControlPlaneError("CONTROL_VERSION_CONFLICT", "kill switch version does not match")
            if current.status == target:
                raise ControlPlaneError("INVALID_KILL_SWITCH_TRANSITION", "kill switch already has the requested status")
            updated = KillSwitch(GLOBAL_KILL_SWITCH_ID, target, current.version + 1, why, actor_id, at)
            self._execute(
                "INSERT INTO foundation_kill_switch VALUES (?, 'global', ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET status = excluded.status, version = excluded.version, reason = excluded.reason, changed_by = excluded.changed_by, changed_at = excluded.changed_at",
                (updated.id, updated.status, updated.version, why, actor_id, at),
            )
            audit_id = self._audit(
                org_id=org_id, trace_id=trace_id, actor_id=actor_id,
                action=f"kill_switch.{target}", subject_type="KillSwitch", subject_id=updated.id,
                decision="changed", reason=why, input_version=current.version or None,
                output_version=updated.version, policy_snapshot={"scope": "global", "status": target},
                payload_hash=payload_hash, idempotency_key=idem, occurred_at=at,
            )
            event_payload = {
                "aggregate_id": updated.id, "aggregate_version": updated.version,
                "from_state": current.status, "to_state": target,
                "command": "pause" if paused else "resume", "reason": why, "audit_id": audit_id,
            }
            envelope = EventEnvelope.create(
                event_type=f"kill_switch.{'paused' if paused else 'resumed'}", event_schema_version=1,
                occurred_at=datetime.fromisoformat(at), org_id=org_id, trace_id=trace_id,
                aggregate_type="KillSwitch", aggregate_id=updated.id, aggregate_version=updated.version,
                actor_type="user", actor_id=actor_id,
                idempotency_key=f"found-008:{sha256(idem.encode('utf-8')).hexdigest()}", payload=event_payload,
            )
            OutboxStore(self.connection, dialect=self.dialect).append(envelope, available_at=datetime.fromisoformat(at))
            self._save_command(org_id, idem, "set_global_kill_switch", payload_hash, asdict(updated), at)
            self.connection.commit()
            return updated
        except Exception:
            self.connection.rollback()
            raise

    def guard_new_task(
        self, *, context: TenantContext, delivery_mode: str, requires_side_effect: bool,
        task_kind: str, payload_hash: str, idempotency_key: str,
        now: datetime | None = None,
    ) -> GateDecision:
        org_id, actor_id, trace_id = _identity(context)
        try:
            mode = DeliveryMode(delivery_mode)
        except (ValueError, TypeError):
            raise ControlPlaneError("INVALID_DELIVERY_MODE", "delivery mode is unsupported") from None
        if type(requires_side_effect) is not bool or not _HASH_RE.fullmatch(payload_hash):
            raise ControlPlaneError("INVALID_CONTROL_COMMAND", "side-effect gate input is invalid")
        kind, idem, at = _required(task_kind, "task_kind", limit=128), _required(idempotency_key, "idempotency_key", limit=256), _timestamp(now)
        try:
            self._begin()
            row = self._execute(
                "SELECT decision, reason, policy_snapshot, audit_id, payload_hash, subject_id FROM foundation_control_audit WHERE org_id = ? AND action = 'side_effect.gate' AND idempotency_key = ?",
                (org_id, idem),
            ).fetchone()
            if row is not None:
                if row[4] != payload_hash:
                    raise ControlPlaneError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with a different payload")
                policy = json.loads(row[2])
                if (policy.get("delivery_mode") != mode.value
                        or policy.get("requires_side_effect") is not requires_side_effect
                        or kind != str(row[5])):
                    raise ControlPlaneError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with different gate metadata")
                decision = GateDecision(row[0] == "allow", str(row[1]), str(policy["delivery_mode"]), str(policy["kill_switch_status"]), bool(policy["feature_enabled"]), str(row[3]), True)
                self.connection.commit()
                if not decision.allowed:
                    raise SideEffectRejected(decision.code, "new side-effect task was rejected")
                return decision
            flag_key = f"delivery_mode.{mode.value}"
            flag = self.get_feature_flag(org_id, flag_key)
            feature_enabled = flag.enabled if flag else DEFAULT_DELIVERY_FLAGS[mode]
            switch = self.get_kill_switch()
            code = "ALLOWED"
            if not feature_enabled:
                code = "FEATURE_FLAG_DISABLED"
            elif requires_side_effect and switch.status == "paused":
                code = "GLOBAL_KILL_SWITCH_PAUSED"
            allowed = code == "ALLOWED"
            policy = {"delivery_mode": mode.value, "feature_flag": flag_key, "feature_enabled": feature_enabled,
                      "feature_version": flag.version if flag else 0, "kill_switch_status": switch.status,
                      "kill_switch_version": switch.version, "requires_side_effect": requires_side_effect}
            audit_id = self._audit(
                org_id=org_id, trace_id=trace_id, actor_id=actor_id, action="side_effect.gate",
                subject_type="TaskJob", subject_id=kind, decision="allow" if allowed else "reject",
                reason=code, input_version=None, output_version=None, policy_snapshot=policy,
                payload_hash=payload_hash, idempotency_key=idem, occurred_at=at,
            )
            self.connection.commit()
            decision = GateDecision(allowed, code, mode.value, switch.status, feature_enabled, audit_id)
            if not allowed:
                raise SideEffectRejected(code, "new side-effect task was rejected")
            return decision
        except SideEffectRejected:
            # Rejection facts are deliberately committed before surfacing.
            raise
        except Exception:
            self.connection.rollback()
            raise
