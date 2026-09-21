"""Credential-free distribution projections for DIST-001.

The service owns only deterministic, tenant-scoped projections.  Manual export
creates a private package reference and simulation uses a fake publisher.  No
platform adapter or network client is reachable from this module.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Protocol, Sequence
from uuid import UUID, uuid4
from hashlib import sha256

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIR = _ROOT / "packages/contracts/jsonschema"
_EVENT_SCHEMA = json.loads((_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8"))


def _schema_registry() -> Registry:
    registry = Registry()
    for path in _SCHEMA_DIR.glob("*.schema.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    return registry


_REGISTRY = _schema_registry()


def _validator(path: Path) -> Draft202012Validator:
    document = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(document, registry=_REGISTRY, format_checker=FormatChecker())


_VALIDATORS = {
    name: _validator(_SCHEMA_DIR / f"{name}.schema.json")
    for name in (
        "distribution-target",
        "distribution-target-version",
        "publication-intent",
        "export-package",
        "delivery-attempt",
        "publication-record",
    )
}
_EVENT_VALIDATOR = Draft202012Validator(_EVENT_SCHEMA, format_checker=FormatChecker())


class DistributionError(ValueError):
    """Stable machine-readable distribution error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FakePublisherPort(Protocol):
    """Port used by simulation; implementations must not perform HTTP."""

    def publish(self, *, intent: Mapping[str, Any], attempt_no: int) -> Mapping[str, Any]: ...


class DeterministicFakePublisher:
    """A pure fake publisher that returns a reproducible acknowledgement."""

    def publish(self, *, intent: Mapping[str, Any], attempt_no: int) -> Mapping[str, Any]:
        replay_hash = _hash({"intent": intent, "attempt_no": attempt_no})
        return {"simulated": True, "replay_input_hash": replay_hash, "attempt_no": attempt_no}


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _uuid(value: UUID | str, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise DistributionError("INVALID_DISTRIBUTION_INPUT", f"{name} must be a UUID") from exc


def _text(value: object, name: str, limit: int = 2048) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise DistributionError("INVALID_DISTRIBUTION_INPUT", f"{name} must be nonempty text")
    return value.strip()


def _time(value: datetime | str | None, name: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise DistributionError("INVALID_DISTRIBUTION_INPUT", f"{name} is required")
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise DistributionError("INVALID_DISTRIBUTION_INPUT", f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise DistributionError("INVALID_DISTRIBUTION_INPUT", f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate(name: str, value: Mapping[str, Any]) -> None:
    errors = sorted(_VALIDATORS[name].iter_errors(dict(value)), key=lambda error: list(error.path))
    if errors:
        raise DistributionError(f"INVALID_{name.replace('-', '_').upper()}", errors[0].message)


class DistributionService:
    """Create immutable distribution projections and safe local executions."""

    rule_version = "dist-001/v1"

    def __init__(self, *, fake_publisher: FakePublisherPort | None = None, kill_switch: Any | None = None) -> None:
        self.fake_publisher = fake_publisher or DeterministicFakePublisher()
        if kill_switch is None:
            from .killswitch import DistributionKillSwitchService
            kill_switch = DistributionKillSwitchService()
        self.kill_switch = kill_switch
        self.targets: dict[tuple[str, str], dict[str, Any]] = {}
        self.target_versions: dict[tuple[str, str], dict[str, Any]] = {}
        self.intents: dict[tuple[str, str], dict[str, Any]] = {}
        self.attempts: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.export_packages: dict[tuple[str, str], dict[str, Any]] = {}
        self.publication_records: dict[tuple[str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._commands: dict[tuple[str, str], tuple[str, Any]] = {}
        self._intent_meta: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def set_kill_switch(self, **kwargs: Any) -> dict[str, Any]:
        return self.kill_switch.set_kill_switch(**kwargs)

    def view_kill_switch(self, *, org_id: UUID | str, scope: str = "global",
                         scope_id: UUID | str | None = None) -> dict[str, Any]:
        return self.kill_switch.get_kill_switch(org_id=org_id, scope=scope, scope_id=scope_id)

    def create_target(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        platform_id: UUID | str, market: str, locale: str, channel: str, environment: str,
        status: str = "planned", created_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        platform, market_text, locale_text = _uuid(platform_id, "platform_id"), _text(market, "market"), _text(locale, "locale")
        if channel not in {"article", "short_post", "video"} or environment not in {"dev", "staging", "prod"}:
            raise DistributionError("INVALID_DISTRIBUTION_INPUT", "channel or environment is invalid")
        if status not in {"planned", "active", "retired"}:
            raise DistributionError("INVALID_DISTRIBUTION_INPUT", "status is invalid")
        now = _time(created_at, "created_at") or datetime.now(timezone.utc)
        target = {
            "id": str(uuid4()), "org_id": tenant, "platform_id": platform, "market": market_text,
            "locale": locale_text, "channel": channel, "environment": environment, "status": status,
            "created_by": actor, "created_at": _stamp(now), "retired_at": _stamp(now) if status == "retired" else None,
        }
        digest = _hash({"operation": "create_target", "org_id": tenant, "platform_id": platform,
                        "market": market_text, "locale": locale_text, "channel": channel, "environment": environment,
                        "status": status, "created_at": _stamp(now)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            _validate("distribution-target", target)
            self.targets[(tenant, target["id"])] = deepcopy(target)
            self._commands[(tenant, key)] = (digest, deepcopy(target))
            self._audit("distribution.target.created", tenant, actor, trace, key, digest, target)
            return deepcopy(target)

    def create_target_version(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        distribution_target_id: UUID | str, platform_id: UUID | str, market: str, locale: str,
        channel: str, environment: str, region_profile_version_id: UUID | str,
        account_profile_id: UUID | str | None = None, account_profile_snapshot: Mapping[str, Any] | None = None,
        account_connection_id: UUID | str | None = None, account_connection_snapshot: Mapping[str, Any] | None = None,
        synthetic_target_id: str | None = None, capability_snapshot: Mapping[str, Any] | None = None,
        policy_snapshot_id: UUID | str | None = None, eligible_delivery_modes: Sequence[str] = ("manual_export",),
        status: str = "draft", snapshot_hash: str | None = None, etag: str | None = None,
        created_at: datetime | str | None = None, retired_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        target_id = _uuid(distribution_target_id, "distribution_target_id")
        target = self._get_target(tenant, target_id)
        if target["status"] == "retired":
            raise DistributionError("TARGET_RETIRED", "retired target cannot receive a new version")
        platform, region = _uuid(platform_id, "platform_id"), _uuid(region_profile_version_id, "region_profile_version_id")
        market_text, locale_text = _text(market, "market"), _text(locale, "locale")
        if channel not in {"article", "short_post", "video"} or environment not in {"dev", "staging", "prod"}:
            raise DistributionError("INVALID_DISTRIBUTION_INPUT", "channel or environment is invalid")
        if (platform, market_text, locale_text, channel, environment) != (
            target["platform_id"], target["market"], target["locale"], target["channel"], target["environment"]
        ):
            raise DistributionError("TARGET_SNAPSHOT_MISMATCH", "TargetVersion must preserve immutable Target fields")
        modes = list(eligible_delivery_modes)
        if not modes or len(set(modes)) != len(modes) or any(mode not in {"manual_export", "simulation", "draft_only", "authorized_api"} for mode in modes):
            raise DistributionError("INVALID_DISTRIBUTION_INPUT", "eligible_delivery_modes is invalid")
        connection = None if account_connection_id is None else _uuid(account_connection_id, "account_connection_id")
        profile = None if account_profile_id is None else _uuid(account_profile_id, "account_profile_id")
        policy = None if policy_snapshot_id is None else _uuid(policy_snapshot_id, "policy_snapshot_id")
        if connection is None:
            if synthetic_target_id is None:
                if modes != ["manual_export"]:
                    raise DistributionError("ACCOUNT_CONNECTION_REQUIRED", "non-manual delivery requires a synthetic target or account connection")
            else:
                synthetic_target_id = _text(synthetic_target_id, "synthetic_target_id", 200)
                if environment == "prod" or "simulation" not in modes or any(mode not in {"manual_export", "simulation"} for mode in modes) or policy is None:
                    raise DistributionError("INVALID_TARGET_VERSION", "synthetic simulation target requires non-prod environment, policy and simulation mode")
        else:
            if profile is None or synthetic_target_id is not None or any(mode not in {"draft_only", "authorized_api"} for mode in modes):
                raise DistributionError("INVALID_TARGET_VERSION", "connected target requires account profile and draft_only/authorized_api modes")
        if status not in {"draft", "active", "retired"}:
            raise DistributionError("INVALID_DISTRIBUTION_INPUT", "status is invalid")
        if status == "active" and policy is None:
            raise DistributionError("INVALID_TARGET_VERSION", "active target version requires policy_snapshot_id")
        now = _time(created_at, "created_at") or datetime.now(timezone.utc)
        retired = _time(retired_at, "retired_at")
        version_no = max((item["version_no"] for (org, _), item in self.target_versions.items() if org == tenant and item["distribution_target_id"] == target_id), default=0) + 1
        capability = deepcopy(dict(capability_snapshot or {}))
        account_profile_snapshot_value = deepcopy(dict(account_profile_snapshot or {}))
        account_connection_snapshot_value = deepcopy(dict(account_connection_snapshot or {}))
        immutable_payload = {
            "distribution_target_id": target_id, "version_no": version_no, "platform_id": platform,
            "market": market_text, "locale": locale_text, "channel": channel, "environment": environment,
            "region_profile_version_id": region, "account_profile_id": profile,
            "account_profile_snapshot": account_profile_snapshot_value, "account_connection_id": connection,
            "account_connection_snapshot": account_connection_snapshot_value, "synthetic_target_id": synthetic_target_id,
            "capability_snapshot": capability, "policy_snapshot_id": policy, "eligible_delivery_modes": modes,
            "status": status,
        }
        computed_hash = _hash(immutable_payload)
        version = {
            "id": str(uuid4()), "org_id": tenant, **immutable_payload,
            "snapshot_hash": computed_hash if snapshot_hash is None else _text(snapshot_hash, "snapshot_hash", 64),
            "etag": etag or f"v{version_no}-{computed_hash[:12]}", "created_by": actor,
            "created_at": _stamp(now), "retired_at": _stamp(retired) if retired else None,
        }
        if len(version["snapshot_hash"]) != 64 or any(char not in "0123456789abcdefABCDEF" for char in version["snapshot_hash"]):
            raise DistributionError("INVALID_TARGET_VERSION", "snapshot_hash must be a SHA-256 hex digest")
        if snapshot_hash is not None and version["snapshot_hash"].lower() != computed_hash.lower():
            raise DistributionError("SNAPSHOT_HASH_MISMATCH", "snapshot_hash does not match immutable target version fields")
        digest = _hash({"operation": "create_target_version", "org_id": tenant,
                        "distribution_target_id": target_id, "version_no": version_no, "platform_id": platform,
                        "market": market_text, "locale": locale_text, "channel": channel, "environment": environment,
                        "region_profile_version_id": region, "account_profile_id": profile,
                        "account_profile_snapshot": account_profile_snapshot_value, "account_connection_id": connection,
                        "account_connection_snapshot": account_connection_snapshot_value, "synthetic_target_id": synthetic_target_id,
                        "capability_snapshot": capability, "policy_snapshot_id": policy, "eligible_delivery_modes": modes,
                        "status": status, "snapshot_hash": version["snapshot_hash"], "etag": version["etag"],
                        "created_at": version["created_at"], "retired_at": version["retired_at"]})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            _validate("distribution-target-version", version)
            self.target_versions[(tenant, version["id"])] = deepcopy(version)
            self._commands[(tenant, key)] = (digest, deepcopy(version))
            self._audit("distribution.target_version.created", tenant, actor, trace, key, digest, version)
            return deepcopy(version)

    def update_target(self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
                      idempotency_key: str, target_id: UUID | str, expected_version: int | None = None,
                      **changes: Any) -> dict[str, Any]:
        """Reject in-place Target edits; callers must create a new snapshot/version."""

        tenant, _actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        _text(trace_id, "trace_id")
        _text(idempotency_key, "idempotency_key", 200)
        target = self._get_target(tenant, _uuid(target_id, "target_id"))
        if expected_version is not None and (type(expected_version) is not int or expected_version < 1):
            raise DistributionError("INVALID_EXPECTED_VERSION", "expected_version must be a positive integer")
        if changes:
            raise DistributionError("TARGET_IMMUTABLE", "Target fields are immutable; create a new TargetVersion")
        return deepcopy(target)

    def retire_target(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        target_id: UUID | str, reason: str, expected_status: str | None = None,
        retired_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Retire a Target lifecycle record without changing its identity fields."""

        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        identity = _uuid(target_id, "target_id")
        reason_text = _text(reason, "reason", 512)
        target = self._get_target(tenant, identity)
        if expected_status is not None and expected_status != target["status"]:
            raise DistributionError("VERSION_CONFLICT", "Target status does not match expected_status")
        at = _time(retired_at, "retired_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "retire_target", "target": target, "reason": reason_text, "retired_at": _stamp(at),
                        "expected_status": expected_status})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if target["status"] == "retired":
                self._commands[(tenant, key)] = (digest, deepcopy(target))
                return deepcopy(target)
            retired = deepcopy(target)
            retired.update({"status": "retired", "retired_at": _stamp(at)})
            _validate("distribution-target", retired)
            self.targets[(tenant, identity)] = deepcopy(retired)
            self._commands[(tenant, key)] = (digest, deepcopy(retired))
            self._audit("distribution.target.retired", tenant, actor, trace, key, digest, retired, reason=reason_text)
            self._event("distribution.target.retired", tenant, actor, trace, key, identity,
                        {"from_state": target["status"], "to_state": "retired", "command": "retire",
                         "reason": reason_text}, at, aggregate_type="DistributionTarget")
            return deepcopy(retired)

    def activate_target_version(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        target_version_id: UUID | str, expected_etag: str, activated_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Activate a draft TargetVersion with an If-Match style guard."""

        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        identity, etag = _uuid(target_version_id, "target_version_id"), _text(expected_etag, "expected_etag", 200)
        version = self._get_target_version(tenant, identity)
        if version["etag"] != etag:
            raise DistributionError("ETAG_MISMATCH", "TargetVersion etag does not match expected_etag")
        if version["status"] != "draft":
            raise DistributionError("INVALID_TARGET_VERSION_STATE", "only draft TargetVersions can be activated")
        if version["policy_snapshot_id"] is None:
            raise DistributionError("POLICY_REQUIRED", "active TargetVersion requires policy_snapshot_id")
        at = _time(activated_at, "activated_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "activate_target_version", "target_version": version, "expected_etag": etag,
                        "activated_at": _stamp(at)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            active = deepcopy(version)
            active.update({"status": "active", "etag": f"{version['etag']}-active", "retired_at": None})
            _validate("distribution-target-version", active)
            self.target_versions[(tenant, identity)] = deepcopy(active)
            self._commands[(tenant, key)] = (digest, deepcopy(active))
            self._audit("distribution.target_version.activated", tenant, actor, trace, key, digest, active)
            self._event("distribution.target_version.activated", tenant, actor, trace, key, identity,
                        {"from_state": "draft", "to_state": "active", "command": "activate",
                         "snapshot_hash": active["snapshot_hash"]}, at, aggregate_type="DistributionTargetVersion")
            return deepcopy(active)

    def retire_target_version(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        target_version_id: UUID | str, expected_etag: str, replacement_version_id: UUID | str | None = None,
        retired_at: datetime | str | None = None, reason: str = "replaced",
    ) -> dict[str, Any]:
        """Retire only lifecycle fields; the TargetVersion snapshot stays immutable."""

        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        identity, etag = _uuid(target_version_id, "target_version_id"), _text(expected_etag, "expected_etag", 200)
        version = self._get_target_version(tenant, identity)
        if version["etag"] != etag:
            raise DistributionError("ETAG_MISMATCH", "TargetVersion etag does not match expected_etag")
        replacement = None if replacement_version_id is None else _uuid(replacement_version_id, "replacement_version_id")
        target = self._get_target(tenant, version["distribution_target_id"])
        if replacement is None and target["status"] != "retired":
            raise DistributionError("REPLACEMENT_VERSION_REQUIRED", "retiring an active TargetVersion requires a replacement or retired Target")
        if replacement is not None:
            replacement_value = self._get_target_version(tenant, replacement)
            if replacement_value["distribution_target_id"] != version["distribution_target_id"] or replacement == identity:
                raise DistributionError("INVALID_REPLACEMENT_VERSION", "replacement must be another version of the same Target")
        reason_text = _text(reason, "reason", 512)
        at = _time(retired_at, "retired_at") or datetime.now(timezone.utc)
        digest = _hash({"operation": "retire_target_version", "target_version": version, "expected_etag": etag,
                        "replacement_version_id": replacement, "reason": reason_text, "retired_at": _stamp(at)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if version["status"] == "retired":
                self._commands[(tenant, key)] = (digest, deepcopy(version))
                return deepcopy(version)
            retired = deepcopy(version)
            retired.update({"status": "retired", "retired_at": _stamp(at), "etag": f"{version['etag']}-retired"})
            _validate("distribution-target-version", retired)
            self.target_versions[(tenant, identity)] = deepcopy(retired)
            self._commands[(tenant, key)] = (digest, deepcopy(retired))
            self._audit("distribution.target_version.retired", tenant, actor, trace, key, digest, retired,
                        reason=reason_text, replacement_version_id=replacement)
            self._event("distribution.target_version.retired", tenant, actor, trace, key, identity,
                        {"from_state": version["status"], "to_state": "retired", "command": "retire",
                         "snapshot_hash": version["snapshot_hash"], "reason": reason_text}, at,
                        aggregate_type="DistributionTargetVersion")
            return deepcopy(retired)

    def create_publication_intent(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        variant_version_id: UUID | str, asset_version_ids: Sequence[UUID | str], target_version_id: UUID | str,
        delivery_mode: str, region_profile_version_id: UUID | str, payload_snapshot: Mapping[str, Any],
        capability_snapshot_hash: str, intent_key: str, policy_snapshot_id: UUID | str | None = None,
        approval_id: UUID | str | None = None, scheduled_at: datetime | str | None = None,
        derived_from_intent_id: UUID | str | None = None, created_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        variant = _uuid(variant_version_id, "variant_version_id")
        assets = [_uuid(item, "asset_version_id") for item in asset_version_ids]
        target_version = self._get_target_version(tenant, _uuid(target_version_id, "target_version_id"))
        if delivery_mode not in target_version["eligible_delivery_modes"]:
            raise DistributionError("DELIVERY_MODE_NOT_ALLOWED", "delivery mode is not eligible for target version")
        if not isinstance(payload_snapshot, Mapping):
            raise DistributionError("INVALID_PUBLICATION_INTENT", "payload_snapshot must be an object")
        payload = deepcopy(dict(payload_snapshot))
        policy = None if policy_snapshot_id is None else _uuid(policy_snapshot_id, "policy_snapshot_id")
        if policy is None:
            policy = target_version["policy_snapshot_id"]
        cap_hash = _text(capability_snapshot_hash, "capability_snapshot_hash", 64)
        if len(cap_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in cap_hash):
            raise DistributionError("INVALID_PUBLICATION_INTENT", "capability_snapshot_hash must be SHA-256")
        created = _time(created_at, "created_at") or datetime.now(timezone.utc)
        scheduled = _time(scheduled_at, "scheduled_at")
        derived = None if derived_from_intent_id is None else _uuid(derived_from_intent_id, "derived_from_intent_id")
        approval = None if approval_id is None else _uuid(approval_id, "approval_id")
        intent = {
            "id": str(uuid4()), "org_id": tenant, "variant_version_id": variant, "asset_version_ids": assets,
            "distribution_target_version_id": target_version["id"], "delivery_mode": delivery_mode,
            "region_profile_version_id": _uuid(region_profile_version_id, "region_profile_version_id"),
            "payload_snapshot": payload, "payload_snapshot_hash": _hash(payload), "scheduled_at": _stamp(scheduled) if scheduled else None,
            "policy_snapshot_id": policy, "capability_snapshot_hash": cap_hash, "intent_key": _text(intent_key, "intent_key", 200),
            "derived_from_intent_id": derived, "status": "planned", "created_by": actor,
            "created_at": _stamp(created), "updated_at": _stamp(created), "resolved_at": None,
        }
        digest = _hash({"operation": "create_publication_intent", "org_id": tenant,
                        "variant_version_id": variant, "asset_version_ids": assets,
                        "distribution_target_version_id": target_version["id"], "delivery_mode": delivery_mode,
                        "region_profile_version_id": intent["region_profile_version_id"], "payload_snapshot": payload,
                        "payload_snapshot_hash": intent["payload_snapshot_hash"], "scheduled_at": intent["scheduled_at"],
                        "policy_snapshot_id": policy, "capability_snapshot_hash": cap_hash, "intent_key": intent["intent_key"],
                        "derived_from_intent_id": derived, "approval_id": approval, "created_at": intent["created_at"]})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            if any(item["intent_key"] == intent["intent_key"] for (org, _), item in self.intents.items() if org == tenant):
                raise DistributionError("DUPLICATE_INTENT_KEY", "intent_key already exists in organization")
            _validate("publication-intent", intent)
            self.intents[(tenant, intent["id"])] = deepcopy(intent)
            self._intent_meta[(tenant, intent["id"])] = {"approval_id": approval, "target_version_id": target_version["id"]}
            self._commands[(tenant, key)] = (digest, deepcopy(intent))
            self._audit("publication.intent.created", tenant, actor, trace, key, digest, intent)
            return deepcopy(intent)

    def execute(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
        intent_id: UUID | str, policy_decision: Mapping[str, Any], approval: Mapping[str, Any] | None = None,
        executed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        tenant, actor = _uuid(org_id, "org_id"), _uuid(actor_id, "actor_id")
        trace, key = _text(trace_id, "trace_id"), _text(idempotency_key, "idempotency_key", 200)
        identity = _uuid(intent_id, "intent_id")
        at = _time(executed_at, "executed_at") or datetime.now(timezone.utc)
        if not isinstance(policy_decision, Mapping):
            raise DistributionError("PUBLICATION_BLOCKED", "policy decision is required")
        if policy_decision.get("org_id") != tenant:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "policy decision is outside this organization")
        if policy_decision.get("final_decision") != "allow":
            raise DistributionError("PUBLICATION_BLOCKED", "policy gate did not allow publication")
        decision_id = _uuid(policy_decision.get("id"), "policy_decision.id")
        intent = self._get_intent(tenant, identity)
        metadata = self._intent_meta[(tenant, identity)]
        approval_id = metadata.get("approval_id")
        if approval_id is not None:
            if approval is None or approval.get("org_id") != tenant or approval.get("id") != approval_id or approval.get("status") != "approved":
                raise DistributionError("PUBLICATION_BLOCKED", "approved distribution approval is required")
        target_version = self._get_target_version(tenant, intent["distribution_target_version_id"])
        if intent["policy_snapshot_id"] is None:
            raise DistributionError("PUBLICATION_BLOCKED", "policy snapshot is required before execution")
        self.kill_switch.guard(
            org_id=tenant, actor_id=actor, trace_id=trace, idempotency_key=f"execute-gate:{key}",
            delivery_mode=intent["delivery_mode"], requires_side_effect=intent["delivery_mode"] != "manual_export",
            platform_id=target_version["platform_id"], account_connection_id=target_version["account_connection_id"],
            target_id=target_version["distribution_target_id"],
        )
        if intent["delivery_mode"] in {"draft_only", "authorized_api"} and target_version["account_connection_id"] is None:
            raise DistributionError("ACCOUNT_CONNECTION_REQUIRED", f"{intent['delivery_mode']} requires an account connection")
        digest = _hash({"operation": "execute", "intent_id": identity, "policy_decision": policy_decision,
                        "approval": approval, "executed_at": _stamp(at)})
        with self._lock:
            prior = self._prior(tenant, key, digest)
            if prior is not None:
                return prior
            attempt_no = max((number for (org, intent_key, number) in self.attempts if org == tenant and intent_key == identity), default=0) + 1
            connected_mode = intent["delivery_mode"] in {"draft_only", "authorized_api"}
            provider_mode = (
                "manual" if intent["delivery_mode"] == "manual_export" else
                "fake" if intent["delivery_mode"] == "simulation" else
                "authorized" if intent["delivery_mode"] == "authorized_api" and target_version["environment"] == "prod" else
                "sandbox"
            )
            adapter_ref = "manual:export" if provider_mode == "manual" else "fake:official@v1" if provider_mode == "fake" else "platform:official@v1"
            started = _stamp(at)
            attempt = {
                "id": str(uuid4()), "org_id": tenant, "publication_intent_id": identity,
                "account_connection_id": target_version["account_connection_id"], "adapter_ref": adapter_ref,
                "provider_mode": provider_mode, "environment": target_version["environment"],
                "policy_snapshot_id": intent["policy_snapshot_id"], "execution_policy_decision_id": decision_id,
                "adapter_version": "v1", "capability_snapshot": deepcopy(target_version["capability_snapshot"]),
                "idempotency_key": key, "provider_idempotency_key": f"{identity}:{attempt_no}:{key}",
                "attempt_no": attempt_no, "parent_attempt_id": None,
                "status": "created" if connected_mode else "succeeded", "retryable": False,
                "next_attempt_at": intent["scheduled_at"] if connected_mode else None,
                "max_attempts": 3 if connected_mode else 1,
                "started_at": None if connected_mode else started,
                "completed_at": None if connected_mode else started,
                "external_request_id": None, "external_object_id": None,
                "account_connection_snapshot": deepcopy(target_version["account_connection_snapshot"]),
                "error_class": None, "last_error_code": None, "last_error_at": None,
                "resolution_reason": None, "resolved_by": None, "resolved_at": None, "created_at": started,
            }
            result: dict[str, Any] = {"intent": None, "attempt": None, "export_package": None, "publication_record": None, "queue": None}
            if intent["delivery_mode"] == "manual_export":
                manifest = {"intent": intent, "target_version": target_version, "approval_id": approval_id,
                            "policy_decision_id": decision_id, "generated_at": started}
                package_hash = _hash(manifest)
                package = {
                    "id": str(uuid4()), "org_id": tenant, "publication_intent_id": identity,
                    "storage_object_ref": f"private://distribution/{tenant}/{identity}/{package_hash}.json",
                    "package_hash": package_hash, "content_version_refs": [intent["variant_version_id"], *intent["asset_version_ids"]],
                    "approval_refs": [approval_id] if approval_id else [],
                    "expires_at": _stamp(at + timedelta(days=7)), "revoked_at": None, "download_count": 0, "status": "available",
                }
                _validate("export-package", package)
                self.export_packages[(tenant, identity)] = deepcopy(package)
                intent["status"] = "exported"
                result["export_package"] = deepcopy(package)
            elif intent["delivery_mode"] == "simulation":
                simulated = dict(self.fake_publisher.publish(intent=deepcopy(intent), attempt_no=attempt_no))
                simulated["simulated"] = True
                simulated.setdefault("replay_input_hash", _hash({"intent": intent, "attempt_no": attempt_no}))
                simulated.setdefault("attempt_no", attempt_no)
                record = {
                    "id": str(uuid4()), "org_id": tenant, "publication_intent_id": identity, "delivery_attempt_id": attempt["id"],
                    "provider_mode": "fake", "external_request_id": None, "external_object_id": None, "external_url": None,
                    "status": "published", "result_snapshot": simulated, "observed_at": started, "last_observed_at": started,
                    "observation_source": "adapter", "unknown_reason": None, "resolution_reason": None,
                    "resolved_by": None, "resolved_at": None, "resolution_evidence_ref": None,
                }
                _validate("publication-record", record)
                self.publication_records[(tenant, identity)] = deepcopy(record)
                intent["status"] = "simulated"
                result["publication_record"] = deepcopy(record)
                self._event("publication.simulated", tenant, actor, trace, key, identity, {"simulated": True, "replay_input_hash": simulated["replay_input_hash"]}, at)
            else:
                # Connected modes are deliberately queued in this credential-free
                # slice.  A later authorized worker owns the external side effect.
                intent["status"] = "queued"
                result["queue"] = {
                    "delivery_mode": intent["delivery_mode"], "requires_dispatch": True,
                    "side_effect_triggered": False, "account_connection_id": target_version["account_connection_id"],
                }
                self._event("publication.queued", tenant, actor, trace, key, identity,
                            {"delivery_mode": intent["delivery_mode"], "requires_dispatch": True,
                             "side_effect_triggered": False}, at)
            _validate("delivery-attempt", attempt)
            self.attempts[(tenant, identity, attempt_no)] = deepcopy(attempt)
            intent["updated_at"] = started
            intent["resolved_at"] = None if connected_mode else started
            _validate("publication-intent", intent)
            self.intents[(tenant, identity)] = deepcopy(intent)
            result["intent"], result["attempt"] = deepcopy(intent), deepcopy(attempt)
            self._commands[(tenant, key)] = (digest, deepcopy(result))
            self._audit("publication.executed", tenant, actor, trace, key, digest, intent,
                        attempt_id=attempt["id"], delivery_mode=intent["delivery_mode"], simulated=intent["delivery_mode"] == "simulation")
            return deepcopy(result)

    def view_intent(self, *, org_id: UUID | str, intent_id: UUID | str) -> dict[str, Any]:
        return deepcopy(self._get_intent(_uuid(org_id, "org_id"), _uuid(intent_id, "intent_id")))

    def view_target(self, *, org_id: UUID | str, target_id: UUID | str) -> dict[str, Any]:
        return deepcopy(self._get_target(_uuid(org_id, "org_id"), _uuid(target_id, "target_id")))

    def view_target_version(self, *, org_id: UUID | str, target_version_id: UUID | str) -> dict[str, Any]:
        return deepcopy(self._get_target_version(_uuid(org_id, "org_id"), _uuid(target_version_id, "target_version_id")))

    def _get_target(self, tenant: str, identity: str) -> dict[str, Any]:
        value = self.targets.get((tenant, identity))
        if value is None:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "distribution target does not belong to organization")
        return value

    def _get_target_version(self, tenant: str, identity: str) -> dict[str, Any]:
        value = self.target_versions.get((tenant, identity))
        if value is None:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "distribution target version does not belong to organization")
        return value

    def _get_intent(self, tenant: str, identity: str) -> dict[str, Any]:
        value = self.intents.get((tenant, identity))
        if value is None:
            raise DistributionError("TENANT_SCOPE_VIOLATION", "publication intent does not belong to organization")
        return value

    def _prior(self, tenant: str, key: str, digest: str) -> Any | None:
        prior = self._commands.get((tenant, key))
        if prior is None:
            return None
        if prior[0] != digest:
            raise DistributionError("IDEMPOTENCY_KEY_REUSED", "command differs from prior request")
        return deepcopy(prior[1])

    def _audit(self, event_type: str, tenant: str, actor: str, trace: str, key: str, digest: str,
               output: Mapping[str, Any], **extra: Any) -> None:
        self.audit.append({"event_type": event_type, "org_id": tenant, "actor_id": actor, "trace_id": trace,
                           "idempotency_key": key, "input_hash": digest, "output_hash": _hash(output), **extra})

    def _event(self, event_type: str, tenant: str, actor: str, trace: str, key: str, aggregate_id: str,
               payload: Mapping[str, Any], occurred_at: datetime, *, aggregate_type: str = "publication_intent",
               aggregate_version: int = 1) -> None:
        event = {"event_id": str(uuid4()), "event_type": event_type, "event_schema_version": 1,
                 "occurred_at": _stamp(occurred_at), "org_id": tenant, "trace_id": trace,
                 "aggregate_type": aggregate_type, "aggregate_id": aggregate_id, "aggregate_version": aggregate_version,
                 "actor_type": "service", "actor_id": actor, "idempotency_key": key,
                 "payload": dict(payload), "payload_hash": _hash(payload)}
        errors = list(_EVENT_VALIDATOR.iter_errors(event))
        if errors:
            raise DistributionError("INVALID_DISTRIBUTION_EVENT", errors[0].message)
        self.events.append(event)


__all__ = ["DeterministicFakePublisher", "DistributionError", "DistributionService", "FakePublisherPort"]
