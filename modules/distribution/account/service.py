"""Credential-free account and distribution target references."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from copy import deepcopy
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from modules.distribution.service import _EVENT_VALIDATOR, _hash, _stamp, _time, _uuid


class AccountError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_ROOT = Path(__file__).resolve().parents[3]
_CONNECTION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/account-connection.schema.json").read_text(encoding="utf-8")
)
_EVIDENCE_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/authorization-evidence.schema.json").read_text(encoding="utf-8")
)
_TARGET_VERSION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/distribution-target-version.schema.json").read_text(encoding="utf-8")
)
_SCHEMA_REGISTRY = Registry()
for _schema_path in (_ROOT / "packages/contracts/jsonschema").glob("*.schema.json"):
    _schema_document = json.loads(_schema_path.read_text(encoding="utf-8"))
    _SCHEMA_REGISTRY = _SCHEMA_REGISTRY.with_resource(_schema_document["$id"], Resource.from_contents(_schema_document))
_CONNECTION_VALIDATOR = Draft202012Validator(_CONNECTION_SCHEMA, format_checker=FormatChecker())
_EVIDENCE_VALIDATOR = Draft202012Validator(_EVIDENCE_SCHEMA, format_checker=FormatChecker())
_TARGET_VERSION_VALIDATOR = Draft202012Validator(_TARGET_VERSION_SCHEMA, registry=_SCHEMA_REGISTRY, format_checker=FormatChecker())


@dataclass(frozen=True)
class AccountProfile:
    id: UUID
    org_id: UUID
    platform_id: UUID
    profile_kind: str
    display_name: str
    status: str

    def as_contract(self) -> dict[str, Any]:
        return {**asdict(self), "id": str(self.id), "org_id": str(self.org_id), "platform_id": str(self.platform_id)}


@dataclass(frozen=True)
class DistributionTarget:
    id: UUID
    org_id: UUID
    account_profile_id: UUID
    channel: str
    status: str = "planned"

    def as_contract(self) -> dict[str, Any]:
        return {**asdict(self), "id": str(self.id), "org_id": str(self.org_id), "account_profile_id": str(self.account_profile_id)}


@dataclass(frozen=True)
class DistributionTargetVersion:
    id: UUID
    org_id: UUID
    target_id: UUID
    version_no: int
    delivery_mode: str
    account_connection_id: UUID | None
    policy_snapshot_ref: str
    config_json: dict[str, Any]
    created_by: UUID
    created_at: datetime

    def as_contract(self) -> dict[str, Any]:
        value = {**asdict(self), "id": str(self.id), "org_id": str(self.org_id), "target_id": str(self.target_id), "created_by": str(self.created_by), "created_at": self.created_at.isoformat()}
        return value


@dataclass(frozen=True)
class AccountConnection:
    id: UUID
    org_id: UUID
    account_profile_id: UUID
    platform_id: UUID
    external_account_id: str
    environment: str
    connection_status: str
    authorization_status: str
    health_status: str
    scope_snapshot: dict[str, Any]
    secret_reference: str | None
    token_lease_id: UUID | None
    token_version: int
    token_expires_at: datetime | None
    last_health_check_at: datetime | None
    last_refresh_error: str | None
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime
    updated_at: datetime

    def as_contract(self) -> dict[str, Any]:
        value = asdict(self)
        for field in ("id", "org_id", "account_profile_id", "platform_id", "token_lease_id"):
            if value[field] is not None:
                value[field] = str(value[field])
        for field in ("token_expires_at", "last_health_check_at", "revoked_at", "created_at", "updated_at"):
            value[field] = _stamp(value[field]) if value[field] is not None else None
        return value


@dataclass(frozen=True)
class AuthorizationEvidence:
    id: UUID
    org_id: UUID
    account_connection_id: UUID
    evidence_type: str
    external_reference: str | None
    scope_snapshot: dict[str, Any]
    captured_at: datetime
    valid_until: datetime | None
    status: str

    def as_contract(self) -> dict[str, Any]:
        value = asdict(self)
        for field in ("id", "org_id", "account_connection_id"):
            value[field] = str(value[field])
        value["captured_at"] = _stamp(self.captured_at)
        value["valid_until"] = _stamp(self.valid_until) if self.valid_until else None
        return value


class InMemoryAccountService:
    def __init__(self) -> None:
        self.profiles: dict[UUID, AccountProfile] = {}
        self.targets: dict[UUID, DistributionTarget] = {}
        self.versions: dict[tuple[UUID, int], DistributionTargetVersion] = {}
        self.connections: dict[tuple[UUID, UUID], AccountConnection] = {}
        self.evidence: dict[tuple[UUID, UUID], AuthorizationEvidence] = {}
        self.connected_target_versions: dict[tuple[UUID, int], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._commands: dict[tuple[UUID, str], tuple[str, Any]] = {}
        self._lock = RLock()

    def create_profile(self, *, org_id: UUID, platform_id: UUID, profile_kind: str, display_name: str, status: str = "planned") -> AccountProfile:
        if profile_kind not in {"planned", "synthetic", "real"}:
            raise AccountError("INVALID_PROFILE_KIND", "profile kind must be planned, synthetic or real")
        if any(p.org_id == org_id and p.display_name == display_name for p in self.profiles.values()):
            raise AccountError("DUPLICATE_PROFILE", "display name already exists in organization")
        profile = AccountProfile(uuid4(), org_id, platform_id, profile_kind, display_name, status)
        self.profiles[profile.id] = profile
        return profile

    def create_target(self, *, org_id: UUID, account_profile_id: UUID, channel: str) -> DistributionTarget:
        profile = self.profiles.get(account_profile_id)
        if profile is None or profile.org_id != org_id:
            raise AccountError("TENANT_SCOPE_VIOLATION", "profile does not belong to organization")
        target = DistributionTarget(uuid4(), org_id, account_profile_id, channel)
        self.targets[target.id] = target
        return target

    def create_version(self, *, org_id: UUID, target_id: UUID, delivery_mode: str, policy_snapshot_ref: str, config_json: dict[str, Any], created_by: UUID) -> DistributionTargetVersion:
        target = self.targets.get(target_id)
        if target is None or target.org_id != org_id:
            raise AccountError("TENANT_SCOPE_VIOLATION", "target does not belong to organization")
        profile = self.profiles[target.account_profile_id]
        allowed = {"manual_export"} if profile.profile_kind == "planned" else {"manual_export", "simulation"}
        if delivery_mode not in allowed:
            if delivery_mode == "authorized_api":
                raise AccountError("ACCOUNT_CONNECTION_REQUIRED", "authorized_api requires an account connection")
            raise AccountError("INVALID_DELIVERY_MODE", "delivery mode is not allowed for profile kind")
        version_no = max((number for target_key, number in self.versions if target_key == target_id), default=0) + 1
        canonical = json.dumps(config_json, sort_keys=True, separators=(",", ":"))
        version = DistributionTargetVersion(uuid4(), org_id, target_id, version_no, delivery_mode, None, policy_snapshot_ref, config_json, created_by, datetime.now(timezone.utc))
        self.versions[(target_id, version_no)] = version
        _ = hashlib.sha256(canonical.encode()).hexdigest()
        return version

    def create_connection(
        self, *, org_id: UUID | str, account_profile_id: UUID | str, platform_id: UUID | str,
        external_account_id: str, environment: str, scope_snapshot: dict[str, Any] | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "account.connection",
        idempotency_key: str | None = None, now: datetime | str | None = None,
    ) -> AccountConnection:
        """Register a redacted connection shell without accepting any token.

        A connection is intentionally ``pending`` until authorization evidence
        is attached.  This lets development and sandbox fixtures exercise the
        full state machine without treating a synthetic account as real.
        """

        tenant_text = _uuid(org_id, "org_id")
        tenant, profile_id, platform = UUID(tenant_text), UUID(_uuid(account_profile_id, "account_profile_id")), UUID(_uuid(platform_id, "platform_id"))
        external = str(external_account_id).strip() if isinstance(external_account_id, str) else ""
        if not external or len(external) > 512:
            raise AccountError("INVALID_EXTERNAL_ACCOUNT_ID", "external_account_id must be non-empty text")
        if environment not in {"sandbox", "prod"}:
            raise AccountError("INVALID_ENVIRONMENT", "environment must be sandbox or prod")
        profile = self.profiles.get(profile_id)
        if profile is None or profile.org_id != tenant:
            raise AccountError("TENANT_SCOPE_VIOLATION", "account profile does not belong to organization")
        if profile.profile_kind != "real":
            raise AccountError("REAL_ACCOUNT_REQUIRED", "a real profile is required for AccountConnection")
        snapshot = deepcopy(scope_snapshot or {})
        if not isinstance(snapshot, dict):
            raise AccountError("INVALID_SCOPE_SNAPSHOT", "scope_snapshot must be an object")
        at = _time(now, "now") or datetime.now(timezone.utc)
        actor = UUID(_uuid(actor_id, "actor_id")) if actor_id is not None else tenant
        key = str(idempotency_key).strip() if idempotency_key is not None else None
        digest = _hash({"operation": "create_connection", "account_profile_id": str(profile_id),
                        "platform_id": str(platform), "external_account_id": external,
                        "environment": environment, "scope_snapshot": snapshot})
        with self._lock:
            if key:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    return prior if isinstance(prior, AccountConnection) else self._connection_from_contract(prior)
            for existing in self.connections.values():
                if (existing.org_id, existing.platform_id, existing.external_account_id) == (tenant, platform, external):
                    raise AccountError("DUPLICATE_CONNECTION", "platform and external account are already connected")
            connection = AccountConnection(
                id=uuid4(), org_id=tenant, account_profile_id=profile_id, platform_id=platform,
                external_account_id=external, environment=environment, connection_status="pending",
                authorization_status="unknown", health_status="unknown", scope_snapshot=snapshot,
                secret_reference=None, token_lease_id=None, token_version=0, token_expires_at=None,
                last_health_check_at=None, last_refresh_error=None, revoked_at=None,
                revocation_reason=None, created_at=at, updated_at=at,
            )
            self._validate_connection(connection.as_contract())
            self.connections[(tenant, connection.id)] = connection
            if key:
                self._commands[(tenant, key)] = (digest, deepcopy(connection))
            self._audit("account.connection.created", tenant, actor, trace_id, key, digest, connection.as_contract())
            self._event("account.connection.created", tenant, actor, trace_id, key, connection.as_contract(), at)
            return connection

    def attach_authorization_evidence(
        self, *, org_id: UUID | str, connection_id: UUID | str, evidence_type: str,
        external_reference: str | None, scope_snapshot: dict[str, Any] | None = None,
        status: str = "verified", valid_until: datetime | str | None = None,
        actor_id: UUID | str | None = None, trace_id: str = "account.evidence",
        idempotency_key: str | None = None, now: datetime | str | None = None,
    ) -> AuthorizationEvidence:
        tenant_text = _uuid(org_id, "org_id")
        tenant, identity = UUID(tenant_text), UUID(_uuid(connection_id, "connection_id"))
        connection = self.connections.get((tenant, identity))
        if connection is None:
            raise AccountError("CONNECTION_NOT_FOUND", "account connection is not available")
        if evidence_type not in {"oauth_consent", "sandbox_membership", "owner_confirmation", "policy_acceptance"}:
            raise AccountError("INVALID_EVIDENCE_TYPE", "unsupported authorization evidence type")
        if status not in {"pending", "verified", "expired", "revoked"}:
            raise AccountError("INVALID_EVIDENCE_STATUS", "unsupported authorization evidence status")
        reference = None if external_reference is None else str(external_reference).strip()
        if status == "verified" and not reference:
            raise AccountError("EVIDENCE_REFERENCE_REQUIRED", "verified evidence requires an external reference")
        snapshot = deepcopy(scope_snapshot or {})
        if not isinstance(snapshot, dict):
            raise AccountError("INVALID_SCOPE_SNAPSHOT", "scope_snapshot must be an object")
        connection_scopes = set(connection.scope_snapshot.get("scopes", []))
        evidence_scopes = set(snapshot.get("scopes", []))
        if connection_scopes and evidence_scopes and not evidence_scopes.issubset(connection_scopes):
            raise AccountError("SCOPE_ESCALATION", "authorization evidence grants an unrequested scope")
        at = _time(now, "now") or datetime.now(timezone.utc)
        valid = _time(valid_until, "valid_until") if valid_until is not None else None
        actor = UUID(_uuid(actor_id, "actor_id")) if actor_id is not None else tenant
        key = str(idempotency_key).strip() if idempotency_key is not None else None
        digest = _hash({"operation": "attach_evidence", "connection_id": str(identity),
                        "evidence_type": evidence_type, "external_reference": reference,
                        "scope_snapshot": snapshot, "status": status,
                        "valid_until": _stamp(valid) if valid else None})
        with self._lock:
            if key:
                prior = self._prior(tenant, key, digest)
                if prior is not None:
                    return prior if isinstance(prior, AuthorizationEvidence) else self._evidence_from_contract(prior)
            evidence = AuthorizationEvidence(
                id=uuid4(), org_id=tenant, account_connection_id=identity,
                evidence_type=evidence_type, external_reference=reference,
                scope_snapshot=snapshot, captured_at=at, valid_until=valid, status=status,
            )
            self._validate_evidence(evidence.as_contract())
            self.evidence[(tenant, evidence.id)] = evidence
            updated = self._refresh_connection_state(connection, at)
            self.connections[(tenant, identity)] = updated
            if key:
                self._commands[(tenant, key)] = (digest, deepcopy(evidence))
            self._audit("account.authorization_evidence.attached", tenant, actor, trace_id, key, digest, evidence.as_contract())
            self._event("account.authorization_evidence.attached", tenant, actor, trace_id, key, evidence.as_contract(), at)
            return evidence

    def account_passport(self, *, org_id: UUID | str, connection_id: UUID | str) -> dict[str, Any]:
        """Return a read-only, secret-free readiness summary."""

        tenant, identity = UUID(_uuid(org_id, "org_id")), UUID(_uuid(connection_id, "connection_id"))
        connection = self.connections.get((tenant, identity))
        if connection is None:
            raise AccountError("CONNECTION_NOT_FOUND", "account connection is not available")
        profile = self.profiles.get(connection.account_profile_id)
        related = [item for (scope, _), item in self.evidence.items()
                   if scope == tenant and item.account_connection_id == identity]
        required = {"oauth_consent", "sandbox_membership"} if connection.environment == "sandbox" else {
            "oauth_consent", "owner_confirmation", "policy_acceptance"
        }
        verified = {item.evidence_type for item in related if item.status == "verified"}
        missing = sorted(required - verified)
        completeness = round((len(required) - len(missing)) / len(required) * 100, 2)
        return {
            "org_id": str(tenant), "connection_id": str(identity),
            "profile_id": str(profile.id) if profile else None,
            "connection": connection.as_contract(),
            "evidence": [item.as_contract() for item in sorted(related, key=lambda item: str(item.id))],
            "required_evidence": sorted(required), "missing_evidence": missing,
            "evidence_completeness_percent": completeness,
            "ready_for_side_effects": not missing and connection.connection_status == "connected"
            and connection.authorization_status == "authorized" and connection.health_status != "restricted",
        }

    def create_connected_target_version(
        self, *, org_id: UUID | str, target_id: UUID | str, connection_id: UUID | str,
        market: str, locale: str, region_profile_version_id: UUID | str,
        created_by: UUID | str, policy_snapshot_id: UUID | str | None,
        capability_snapshot: dict[str, Any], eligible_delivery_modes: list[str] | tuple[str, ...] = ("draft_only",),
        environment: str = "staging", now: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, target_identity = UUID(_uuid(org_id, "org_id")), UUID(_uuid(target_id, "target_id"))
        connection_identity = UUID(_uuid(connection_id, "connection_id"))
        target = self.targets.get(target_identity)
        connection = self.connections.get((tenant, connection_identity))
        if target is None or target.org_id != tenant or connection is None:
            raise AccountError("TENANT_SCOPE_VIOLATION", "target or connection does not belong to organization")
        passport = self.account_passport(org_id=tenant, connection_id=connection_identity)
        if not passport["ready_for_side_effects"]:
            raise AccountError("ACCOUNT_NOT_READY", "authorization evidence and healthy connection are required")
        if environment not in {"dev", "staging", "prod"}:
            raise AccountError("INVALID_ENVIRONMENT", "target version environment is invalid")
        modes = list(dict.fromkeys(eligible_delivery_modes))
        if not modes or any(mode not in {"draft_only", "authorized_api"} for mode in modes):
            raise AccountError("INVALID_DELIVERY_MODES", "real target versions require draft_only or authorized_api")
        at = _time(now, "now") or datetime.now(timezone.utc)
        profile = self.profiles[target.account_profile_id]
        next_version = max((number for (target_key, number) in self.connected_target_versions if target_key == target_identity), default=0) + 1
        account_snapshot = {
            "connection_id": str(connection.id), "platform_id": str(connection.platform_id),
            "external_account_id": connection.external_account_id, "environment": connection.environment,
            "authorization_status": connection.authorization_status, "health_status": connection.health_status,
            "scope_snapshot": deepcopy(connection.scope_snapshot), "token_version": connection.token_version,
        }
        value = {
            "id": str(uuid4()), "org_id": str(tenant), "distribution_target_id": str(target.id),
            "version_no": next_version, "platform_id": str(profile.platform_id), "market": str(market),
            "locale": str(locale), "channel": target.channel, "environment": environment,
            "region_profile_version_id": str(UUID(_uuid(region_profile_version_id, "region_profile_version_id"))),
            "account_profile_id": str(profile.id), "account_profile_snapshot": {"id": str(profile.id), "profile_kind": profile.profile_kind, "display_name": profile.display_name},
            "account_connection_id": str(connection.id), "account_connection_snapshot": account_snapshot,
            "synthetic_target_id": None, "capability_snapshot": deepcopy(capability_snapshot),
            "policy_snapshot_id": str(UUID(_uuid(policy_snapshot_id, "policy_snapshot_id"))) if policy_snapshot_id else None,
            "eligible_delivery_modes": modes, "status": "draft", "snapshot_hash": "0" * 64,
            "etag": "pending", "created_by": str(UUID(_uuid(created_by, "created_by"))), "created_at": _stamp(at), "retired_at": None,
        }
        value["snapshot_hash"] = _hash({key: item for key, item in value.items() if key not in {"snapshot_hash", "etag"}})
        value["etag"] = f'W/"{value["snapshot_hash"]}"'
        self._validate_target_version(value)
        self.connected_target_versions[(target_identity, next_version)] = deepcopy(value)
        return deepcopy(value)

    def check_health(
        self, *, org_id: UUID | str, connection_id: UUID | str, actor_id: UUID | str | None = None,
        provider_status: str = "healthy", owner_present: bool = True, policy_allowed: bool = True,
        token_expires_at: datetime | str | None = None, now: datetime | str | None = None,
    ) -> AccountConnection:
        tenant, identity = UUID(_uuid(org_id, "org_id")), UUID(_uuid(connection_id, "connection_id"))
        current = self.connections.get((tenant, identity))
        if current is None:
            raise AccountError("CONNECTION_NOT_FOUND", "account connection is not available")
        if provider_status not in {"healthy", "degraded", "restricted", "unknown"}:
            raise AccountError("INVALID_PROVIDER_STATUS", "provider health status is invalid")
        if type(owner_present) is not bool or type(policy_allowed) is not bool:
            raise AccountError("INVALID_HEALTH_INPUT", "owner_present and policy_allowed must be booleans")
        at = _time(now, "now") or datetime.now(timezone.utc)
        expiry = _time(token_expires_at, "token_expires_at") if token_expires_at is not None else current.token_expires_at
        restricted_reason = None
        if current.authorization_status in {"expired", "revoked"}:
            restricted_reason = "AUTHORIZATION_INVALID"
        elif expiry is not None and expiry <= at:
            restricted_reason = "TOKEN_EXPIRED"
        elif not owner_present:
            restricted_reason = "OWNER_UNAVAILABLE"
        elif not policy_allowed:
            restricted_reason = "POLICY_CHANGED"
        elif provider_status in {"restricted", "degraded"}:
            restricted_reason = "PROVIDER_HEALTH"
        status = "restricted" if restricted_reason else ("connected" if current.authorization_status == "authorized" else "pending")
        health = "restricted" if restricted_reason else provider_status
        updated = replace(current, connection_status=status, health_status=health,
                          token_expires_at=expiry, last_health_check_at=at,
                          last_refresh_error=restricted_reason, updated_at=at)
        self._validate_connection(updated.as_contract())
        self.connections[(tenant, identity)] = updated
        actor = UUID(_uuid(actor_id, "actor_id")) if actor_id is not None else tenant
        self._audit("account.connection.health_checked", str(tenant), str(actor), "account.health", None,
                    _hash(updated.as_contract()), {"connection_id": str(identity), "status": status, "health_status": health, "reason": restricted_reason})
        return updated

    def guard_delivery_phase(self, *, kill_switch: Any, org_id: UUID | str, connection_id: UUID | str,
                             actor_id: UUID | str, trace_id: str, idempotency_key: str,
                             phase: str, delivery_mode: str = "authorized_api") -> dict[str, Any]:
        if phase not in {"queue_claim", "platform_call", "reconcile"}:
            raise AccountError("INVALID_GUARD_PHASE", "phase must be queue_claim, platform_call or reconcile")
        tenant, connection = _uuid(org_id, "org_id"), _uuid(connection_id, "connection_id")
        record = self.connections.get((UUID(tenant), UUID(connection)))
        if record is None:
            raise AccountError("CONNECTION_NOT_FOUND", "account connection is not available")
        if record.connection_status != "connected" or record.health_status == "restricted":
            raise AccountError("ACCOUNT_RESTRICTED", "restricted account cannot pass delivery guard")
        result = kill_switch.guard(
            org_id=tenant, actor_id=actor_id, trace_id=trace_id,
            idempotency_key=f"{idempotency_key}:{phase}", delivery_mode=delivery_mode,
            requires_side_effect=phase == "platform_call", account_connection_id=connection,
            platform_id=record.platform_id,
        )
        return {"phase": phase, "guard": result, "side_effect_triggered": False}

    def _refresh_connection_state(self, current: AccountConnection, at: datetime) -> AccountConnection:
        evidence = [item for (tenant, _), item in self.evidence.items()
                    if tenant == current.org_id and item.account_connection_id == current.id]
        required = {"oauth_consent", "sandbox_membership"} if current.environment == "sandbox" else {
            "oauth_consent", "owner_confirmation", "policy_acceptance"
        }
        verified = {item.evidence_type for item in evidence if item.status == "verified"}
        ready = required.issubset(verified)
        return replace(current,
                       connection_status="connected" if ready else "pending",
                       authorization_status="authorized" if "oauth_consent" in verified else current.authorization_status,
                       health_status="healthy" if ready else "unknown", updated_at=at)

    @staticmethod
    def _validate_connection(value: dict[str, Any]) -> None:
        errors = sorted(_CONNECTION_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            raise AccountError("INVALID_ACCOUNT_CONNECTION", errors[0].message)

    @staticmethod
    def _connection_from_contract(value: dict[str, Any]) -> AccountConnection:
        parsed = dict(value)
        for field in ("id", "org_id", "account_profile_id", "platform_id", "token_lease_id"):
            if parsed[field] is not None:
                parsed[field] = UUID(parsed[field])
        for field in ("token_expires_at", "last_health_check_at", "revoked_at", "created_at", "updated_at"):
            if parsed[field] is not None:
                parsed[field] = _time(parsed[field], field, required=True)
        return AccountConnection(**parsed)

    @staticmethod
    def _validate_evidence(value: dict[str, Any]) -> None:
        errors = sorted(_EVIDENCE_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            raise AccountError("INVALID_AUTHORIZATION_EVIDENCE", errors[0].message)

    @staticmethod
    def _evidence_from_contract(value: dict[str, Any]) -> AuthorizationEvidence:
        parsed = dict(value)
        for field in ("id", "org_id", "account_connection_id"):
            parsed[field] = UUID(parsed[field])
        parsed["captured_at"] = _time(parsed["captured_at"], "captured_at", required=True)
        parsed["valid_until"] = _time(parsed["valid_until"], "valid_until") if parsed["valid_until"] else None
        return AuthorizationEvidence(**parsed)

    @staticmethod
    def _validate_target_version(value: dict[str, Any]) -> None:
        errors = sorted(_TARGET_VERSION_VALIDATOR.iter_errors(value), key=lambda error: list(error.path))
        if errors:
            raise AccountError("INVALID_TARGET_VERSION", errors[0].message)

    def _prior(self, tenant: UUID, key: str, digest: str) -> Any | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise AccountError("IDEMPOTENCY_KEY_REUSED", "account command differs from the prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str | None,
               digest: str, output: dict[str, Any]) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor,
                           "trace_id": trace, "idempotency_key": key, "input_hash": digest,
                           "output_hash": _hash(output)})

    def _event(self, event_type: str, tenant: UUID, actor: UUID, trace: str, key: str | None,
               aggregate: dict[str, Any], occurred_at: datetime) -> None:
        aggregate_id = _uuid(aggregate.get("id"), "aggregate.id")
        payload = {"aggregate_id": aggregate_id, "aggregate_version": 1,
                   "from_state": None, "to_state": aggregate.get("connection_status", aggregate.get("status")),
                   "command": event_type, "snapshot_hash": _hash(aggregate), "reason": None}
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": str(tenant), "trace_id": trace,
                 "aggregate_type": "AccountConnection", "aggregate_id": aggregate_id,
                 "aggregate_version": 1, "actor_type": "service", "actor_id": str(actor),
                 "idempotency_key": key or f"event-{aggregate_id}", "payload": payload, "payload_hash": _hash(payload)}
        errors = sorted(_EVENT_VALIDATOR.iter_errors(event), key=lambda error: list(error.path))
        if errors:
            raise AccountError("INVALID_ACCOUNT_EVENT", errors[0].message)
        self.events.append(deepcopy(event))
