"""Tenant-scoped, versioned locale and market configuration.

GEO_REGION-001 is an offline domain/application slice.  It owns deterministic
RegionProfile identities, immutable configuration snapshots, controlled
draft/active/retired transitions, idempotent commands, and audit/event
evidence.  It performs no network or platform I/O.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_PROFILE_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/region-profile.schema.json").read_text(encoding="utf-8")
)
_VERSION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/region-profile-version.schema.json").read_text(encoding="utf-8")
)
_PROFILE_VALIDATOR = Draft202012Validator(_PROFILE_SCHEMA, format_checker=FormatChecker())
_VERSION_VALIDATOR = Draft202012Validator(_VERSION_SCHEMA, format_checker=FormatChecker())
_PROFILE_NAMESPACE = UUID("790a92e7-6239-5d43-a904-e74eb7149a2c")
_VERSION_NAMESPACE = UUID("48334989-e5a4-5222-9c6a-cd4011171844")
_EVENT_NAMESPACE = UUID("ee04a926-fbb0-55dc-b788-a53c975b8948")
_SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
_MISSING = object()
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_REGION_RE = re.compile(r"^[A-Z]{2,8}(?:-[A-Z0-9]{2,8})*$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_READY_STATES = frozenset({
    "active", "approved", "complete", "completed", "done", "published",
    "ready", "succeeded", "valid", "verified",
})
_BAD_STATES = frozenset({
    "blocked", "cancelled", "draft", "expired", "failed", "invalid",
    "manual_review", "pending", "rejected", "retired", "review", "stale",
    "unknown", "withdrawn",
})


class RegionError(ValueError):
    """Stable machine-readable GEO_REGION failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    except (TypeError, ValueError) as exc:
        raise RegionError("REGION_PROFILE_INVALID", "value must be finite JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must be text")
    result = value.strip()
    if not result:
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must be non-empty")
    if len(result) > maximum:
        raise RegionError("REGION_PROFILE_INVALID", f"{field} exceeds {maximum} characters")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise RegionError("REGION_PROFILE_INVALID", f"{field} contains a control character")
    return result


def _uuid(value: Any, field: str, *, required: bool = True) -> UUID | None:
    if value is None and not required:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must be a UUID") from exc


def _time(value: Any, field: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise RegionError("REGION_PROFILE_INVALID", f"{field} is required")
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise RegionError("REGION_PROFILE_INVALID", f"{field} must be ISO-8601") from exc
    else:
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RegionError("REGION_PROFILE_INVALID", "timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _resolve_tenant(
    org_id: Any = None,
    tenant_context: Mapping[str, Any] | None = None,
    actor_id: Any = None,
    trace_id: Any = None,
) -> tuple[UUID, UUID, str]:
    context = tenant_context if tenant_context is not None else {}
    if not isinstance(context, Mapping):
        raise RegionError("INVALID_TENANT_CONTEXT", "tenant_context must be an object")
    markers = [
        value
        for value in (org_id, context.get("org_id"), context.get("tenant_id"))
        if value is not None
    ]
    if not markers:
        raise RegionError("INVALID_TENANT_CONTEXT", "org_id is required")
    try:
        tenant = markers[0] if isinstance(markers[0], UUID) else UUID(str(markers[0]))
        for marker in markers[1:]:
            if (marker if isinstance(marker, UUID) else UUID(str(marker))) != tenant:
                raise RegionError("TENANT_SCOPE_VIOLATION", "tenant context markers disagree")
    except RegionError:
        raise
    except (TypeError, ValueError, AttributeError) as exc:
        raise RegionError("INVALID_TENANT_CONTEXT", "org_id must be a UUID") from exc
    actor_value = actor_id if actor_id is not None else context.get("actor_id", context.get("actor"))
    if actor_value is None:
        actor = _SYSTEM_ACTOR
    else:
        try:
            actor = actor_value if isinstance(actor_value, UUID) else UUID(str(actor_value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise RegionError("INVALID_TENANT_CONTEXT", "actor_id must be a UUID") from exc
    trace_value = trace_id if trace_id is not None else context.get("trace_id", "geo-region-001")
    trace = _text(trace_value, "trace_id", maximum=256)
    return tenant, actor, trace


def _safe_tenant(org_id: Any, tenant_context: Mapping[str, Any] | None) -> str:
    candidates = [org_id]
    if isinstance(tenant_context, Mapping):
        candidates.extend([tenant_context.get("org_id"), tenant_context.get("tenant_id")])
    for value in candidates:
        if value is None:
            continue
        try:
            return str(value if isinstance(value, UUID) else UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return "unknown"


def _guard_nested_tenant(value: Any, tenant: UUID, field: str) -> None:
    if isinstance(value, Mapping):
        for marker_name in ("org_id", "tenant_id"):
            if marker_name in value:
                marker = _uuid(value[marker_name], f"{field}.{marker_name}")
                if marker != tenant:
                    raise RegionError("TENANT_SCOPE_VIOLATION", f"{field} is outside this organization")
        for name, item in value.items():
            if isinstance(item, Mapping) or (
                isinstance(item, Sequence) and not isinstance(item, (str, bytes))
            ):
                _guard_nested_tenant(item, tenant, f"{field}.{name}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            if isinstance(item, Mapping) or (
                isinstance(item, Sequence) and not isinstance(item, (str, bytes))
            ):
                _guard_nested_tenant(item, tenant, f"{field}[{index}]")


def _validate_predecessors(value: Mapping[str, Any] | None, *, tenant: UUID) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise RegionError("REGION_PROFILE_INVALID", "predecessor_artifacts must be an object")
    _guard_nested_tenant(value, tenant, "predecessor_artifacts")
    for name, item in value.items():
        records = item if isinstance(item, Sequence) and not isinstance(item, (str, bytes, Mapping)) else [item]
        for record in records:
            if not isinstance(record, Mapping):
                continue
            status = record.get("status", record.get("state"))
            if isinstance(status, str):
                normalized = status.strip().lower()
                if normalized in _BAD_STATES or normalized not in _READY_STATES:
                    raise RegionError(
                        "PREDECESSOR_NOT_READY",
                        f"predecessor {name} is not ready",
                        details={"predecessor": name, "status": status},
                    )
            for marker in ("ready", "is_ready", "eligible"):
                if marker in record and record[marker] is False:
                    raise RegionError("PREDECESSOR_NOT_READY", f"predecessor {name} is not ready")


def _policy_hash(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and _HASH_RE.fullmatch(value.strip()):
        return value.strip().lower()
    return _hash(value)


def _if_match(expected_version: Any, if_match: Any) -> int:
    def parse(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise RegionError("VERSION_CONFLICT", "version must be a positive integer")
        raw = str(value).strip()
        if raw.startswith("W/"):
            raw = raw[2:].strip()
        raw = raw.strip('"')
        try:
            result = int(raw)
        except ValueError as exc:
            raise RegionError("VERSION_CONFLICT", "version must be a positive integer") from exc
        if result < 1:
            raise RegionError("VERSION_CONFLICT", "version must be a positive integer")
        return result

    expected = parse(expected_version)
    matched = parse(if_match)
    if expected is None and matched is None:
        raise RegionError("VERSION_PRECONDITION_REQUIRED", "expected_version or If-Match is required")
    if expected is not None and matched is not None and expected != matched:
        raise RegionError("VERSION_CONFLICT", "expected_version and If-Match disagree")
    return expected if expected is not None else matched  # type: ignore[return-value]


def _region_code(value: Any) -> str:
    code = _text(value, "region_code", maximum=32).upper()
    if _REGION_RE.fullmatch(code) is None:
        raise RegionError("REGION_PROFILE_INVALID", "region_code is invalid")
    return code


def _locale(value: Any) -> str:
    raw = _text(value, "locales[]", maximum=64)
    if _LOCALE_RE.fullmatch(raw) is None:
        raise RegionError("REGION_PROFILE_INVALID", "locale is not a supported BCP-47 form")
    parts = raw.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        else:
            normalized.append(part.lower())
    return "-".join(normalized)


def _locales(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise RegionError("REGION_PROFILE_INVALID", "locales must be an array")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _locale(item)
        key = normalized.casefold()
        if key in seen:
            raise RegionError("REGION_PROFILE_INVALID", "locales must be unique")
        seen.add(key)
        result.append(normalized)
    if not result:
        raise RegionError("REGION_PROFILE_INVALID", "locales must not be empty")
    return tuple(result)


def _integer(value: Any, field: str, *, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > maximum:
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must be an integer from 0 to {maximum}")
    return value


def _json_rule_name(value: Mapping[str, Any]) -> str | None:
    for name in ("term", "topic", "text", "disclosure", "id", "name"):
        raw = value.get(name)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _rules(value: Any, field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise RegionError("REGION_PROFILE_INVALID", f"{field} must be an array")
    result: list[Any] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if isinstance(item, str):
            normalized: Any = _text(item, f"{field}[{index}]", maximum=512)
        elif isinstance(item, Mapping):
            normalized = deepcopy(dict(item))
            if _json_rule_name(normalized) is None:
                raise RegionError(
                    "REGION_PROFILE_INVALID",
                    f"{field}[{index}] must have a rule name",
                )
            _canonical(normalized)
        else:
            raise RegionError("REGION_PROFILE_INVALID", f"{field}[{index}] is invalid")
        digest = _hash(normalized)
        if digest in seen:
            raise RegionError("REGION_PROFILE_INVALID", f"{field} must be unique")
        seen.add(digest)
        result.append(normalized)
    return tuple(result)


def _platforms(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise RegionError("REGION_PROFILE_INVALID", "platform_eligibility must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        name = _text(item, f"platform_eligibility[{index}]", maximum=128)
        if name in result:
            raise RegionError("REGION_PROFILE_INVALID", "platform_eligibility must be unique")
        result.append(name)
    return tuple(result)


def _validate_interval(
    valid_from: datetime | None,
    valid_to: datetime | None,
    review_due_at: datetime | None,
) -> None:
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise RegionError("REGION_PROFILE_INVALID", "valid_to must be later than valid_from")
    if review_due_at is not None and valid_from is not None and review_due_at < valid_from:
        raise RegionError("REGION_PROFILE_INVALID", "review_due_at cannot precede valid_from")


@dataclass(frozen=True)
class RegionProfile:
    id: UUID
    org_id: UUID
    region_code: str
    status: str
    current_version_id: UUID | None
    created_at: datetime

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "region_code": self.region_code,
            "current_version_id": str(self.current_version_id) if self.current_version_id else None,
            "status": self.status,
            "created_at": _stamp(self.created_at),
        }

    def __getitem__(self, name: str) -> Any:
        return self.as_contract()[name]

    def get(self, name: str, default: Any = None) -> Any:
        return self.as_contract().get(name, default)


@dataclass(frozen=True)
class RegionProfileVersion:
    id: UUID
    org_id: UUID
    region_profile_id: UUID
    version_no: int
    region_code: str
    locales: tuple[str, ...]
    timezone: str
    date_number_format: str
    units: str
    currency: str
    terminology_version: str
    disclosure_rules: tuple[Any, ...]
    restricted_topics: tuple[Any, ...]
    data_residency: str
    retention_days: int
    deletion_sla_hours: int
    platform_eligibility: tuple[str, ...]
    policy_snapshot_id: UUID | None
    valid_from: datetime | None
    valid_to: datetime | None
    review_due_at: datetime | None
    status: str
    snapshot_hash: str
    created_by: UUID
    created_at: datetime

    @property
    def profile_id(self) -> UUID:
        return self.region_profile_id

    @property
    def policy_snapshot_ref(self) -> str | None:
        return str(self.policy_snapshot_id) if self.policy_snapshot_id else None

    @property
    def content_hash(self) -> str:
        return self.snapshot_hash

    def as_contract(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "region_profile_id": str(self.region_profile_id),
            "version_no": self.version_no,
            "region_code": self.region_code,
            "locales": list(self.locales),
            "timezone": self.timezone,
            "date_number_format": self.date_number_format,
            "units": self.units,
            "currency": self.currency,
            "terminology_version": self.terminology_version,
            "disclosure_rules": deepcopy(list(self.disclosure_rules)),
            "restricted_topics": deepcopy(list(self.restricted_topics)),
            "data_residency": self.data_residency,
            "retention_days": self.retention_days,
            "deletion_sla_hours": self.deletion_sla_hours,
            "platform_eligibility": list(self.platform_eligibility),
            "policy_snapshot_id": str(self.policy_snapshot_id) if self.policy_snapshot_id else None,
            "valid_from": _stamp(self.valid_from) if self.valid_from else None,
            "valid_to": _stamp(self.valid_to) if self.valid_to else None,
            "review_due_at": _stamp(self.review_due_at) if self.review_due_at else None,
            "status": self.status,
            "snapshot_hash": self.snapshot_hash,
            "created_by": str(self.created_by),
            "created_at": _stamp(self.created_at),
        }

    def as_compatibility_projection(self) -> dict[str, Any]:
        value = self.as_contract()
        value["profile_id"] = value["region_profile_id"]
        value["policy_snapshot_ref"] = value["policy_snapshot_id"]
        value["content_hash"] = value["snapshot_hash"]
        # PROD-004 still consumes the pre-GEO_REGION-001 names.  Keep these
        # aliases in the explicitly opt-in projection; the closed contract
        # returned by ``as_contract`` remains unchanged.
        value["date_format"] = value["date_number_format"]
        value["number_format"] = value["date_number_format"]
        value["data_region"] = value["data_residency"]
        return value

    def __getitem__(self, name: str) -> Any:
        if name in {"profile_id", "policy_snapshot_ref", "content_hash", "date_format", "number_format", "data_region"}:
            return self.as_compatibility_projection()[name]
        return self.as_contract()[name]

    def get(self, name: str, default: Any = None) -> Any:
        if name in {"profile_id", "policy_snapshot_ref", "content_hash", "date_format", "number_format", "data_region"}:
            return self.as_compatibility_projection().get(name, default)
        return self.as_contract().get(name, default)


def _validate_profile(profile: RegionProfile) -> None:
    errors = sorted(_PROFILE_VALIDATOR.iter_errors(profile.as_contract()), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "profile"
        raise RegionError("REGION_PROFILE_INVALID", f"{location}: {errors[0].message}")


def _version_material(version: RegionProfileVersion) -> dict[str, Any]:
    value = version.as_contract()
    for name in ("id", "status", "snapshot_hash", "created_by", "created_at"):
        value.pop(name)
    return value


def _validate_version(version: RegionProfileVersion) -> None:
    errors = sorted(_VERSION_VALIDATOR.iter_errors(version.as_contract()), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "version"
        raise RegionError("REGION_PROFILE_INVALID", f"{location}: {errors[0].message}")
    if version.snapshot_hash != _hash(_version_material(version)):
        raise RegionError("REGION_SNAPSHOT_HASH_MISMATCH", "snapshot hash does not match version configuration")


class InMemoryRegionStore:
    """Thread-safe store with append-only version/profile history."""

    def __init__(self) -> None:
        self.profiles: dict[UUID, RegionProfile] = {}
        self.profile_history: dict[UUID, list[RegionProfile]] = {}
        self.profile_index: dict[tuple[UUID, str], UUID] = {}
        self.versions: dict[UUID, RegionProfileVersion] = {}
        self.version_history: dict[UUID, list[RegionProfileVersion]] = {}
        self.commands: dict[tuple[UUID, str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def get_command(self, tenant: UUID, namespace: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.commands.get((tenant, namespace, key))
            return deepcopy(value) if value is not None else None

    def save_command(
        self,
        tenant: UUID,
        namespace: str,
        key: str,
        request_hash: str,
        response: Any,
    ) -> None:
        with self._lock:
            identity = (tenant, namespace, key)
            prior = self.commands.get(identity)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise RegionError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return
            self.commands[identity] = {
                "request_hash": request_hash,
                "response": deepcopy(response),
            }

    def save_profile(self, value: RegionProfile) -> None:
        with self._lock:
            existing = self.profiles.get(value.id)
            if existing is not None and (
                existing.org_id != value.org_id or existing.region_code != value.region_code
                or existing.created_at != value.created_at
            ):
                raise RegionError("REGION_PROFILE_ID_CONFLICT", "profile identity is immutable")
            self.profiles[value.id] = deepcopy(value)
            self.profile_index[(value.org_id, value.region_code)] = value.id
            self.profile_history.setdefault(value.id, []).append(deepcopy(value))

    def save_version(self, value: RegionProfileVersion) -> None:
        with self._lock:
            existing = self.versions.get(value.id)
            if existing is not None and (
                existing.org_id != value.org_id
                or existing.region_profile_id != value.region_profile_id
                or existing.version_no != value.version_no
                or existing.created_at != value.created_at
            ):
                raise RegionError("REGION_VERSION_ID_CONFLICT", "version identity is immutable")
            self.versions[value.id] = deepcopy(value)
            self.version_history.setdefault(value.id, []).append(deepcopy(value))


class InMemoryRegionService:
    """Public GEO_REGION-001 application service."""

    task_id = "GEO_REGION-001"
    rule_version = "geo-region-001.v1"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        store: InMemoryRegionStore | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = store or InMemoryRegionStore()
        # Preserve the original skeleton's public collections.
        self.profiles = self.store.profiles
        self.versions = self.store.versions
        self.profile_history = self.store.profile_history
        self.version_history = self.store.version_history
        self.events = self.store.events
        self.audit = self.store.audit
        self._lock = RLock()

    def _audit(
        self,
        *,
        event_type: str,
        tenant: str,
        actor: str,
        trace: str,
        key: str | None,
        aggregate_id: str | None,
        input_hash: str | None,
        output_hash: str | None,
        input_version: int | None,
        output_version: int | None,
        policy_hash: str | None,
        status: str,
        reason: str | None = None,
    ) -> None:
        self.store.audit.append({
            "event_type": event_type,
            "task_id": self.task_id,
            "org_id": tenant,
            "actor_id": actor,
            "trace_id": trace,
            "idempotency_key": key,
            "aggregate_id": aggregate_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "input_version": input_version,
            "output_version": output_version,
            "policy_snapshot_hash": policy_hash,
            "status": status,
            "reason": reason,
            "duration_ms": 0,
            "cost_cents": 0,
            "created_at": _stamp(self.clock()),
        })

    def _reject(
        self,
        error: RegionError,
        *,
        org_id: Any,
        tenant_context: Mapping[str, Any] | None,
        actor_id: Any,
        trace_id: Any,
        idempotency_key: Any,
        input_hash: str | None = None,
        policy_hash: str | None = None,
    ) -> None:
        context = tenant_context if isinstance(tenant_context, Mapping) else {}
        try:
            actor = str(
                _uuid(
                    actor_id if actor_id is not None else context.get("actor_id", _SYSTEM_ACTOR),
                    "actor_id",
                )
            )
        except RegionError:
            actor = "unknown"
        try:
            trace = _text(
                trace_id if trace_id is not None else context.get("trace_id", "geo-region-001"),
                "trace_id",
                maximum=256,
            )
        except RegionError:
            trace = "geo-region-001"
        self._audit(
            event_type="region.command.rejected",
            tenant=_safe_tenant(org_id, tenant_context),
            actor=actor,
            trace=trace,
            key=str(idempotency_key) if idempotency_key is not None else None,
            aggregate_id=None,
            input_hash=input_hash,
            output_hash=None,
            input_version=None,
            output_version=None,
            policy_hash=policy_hash,
            status="rejected",
            reason=f"{error.code}: {error}",
        )

    def _event(
        self,
        *,
        event_type: str,
        tenant: UUID,
        actor: UUID,
        trace: str,
        key: str,
        aggregate_id: UUID,
        aggregate_version: int,
        from_state: str | None,
        to_state: str | None,
        command: str,
        snapshot_hash: str | None,
        reason: str | None = None,
    ) -> None:
        payload = {
            "aggregate_id": str(aggregate_id),
            "aggregate_version": aggregate_version,
            "from_state": from_state,
            "to_state": to_state,
            "command": command,
            "snapshot_hash": snapshot_hash,
            "reason": reason,
        }
        event = {
            "event_id": str(uuid5(
                _EVENT_NAMESPACE,
                f"{tenant}:{event_type}:{aggregate_id}:{aggregate_version}:{key}:{to_state}",
            )),
            "event_type": event_type,
            "event_schema_version": 1,
            "occurred_at": _stamp(self.clock()),
            "org_id": str(tenant),
            "trace_id": trace,
            "correlation_id": trace,
            "causation_id": None,
            "aggregate_type": (
                "RegionProfile"
                if event_type.startswith("region.profile.")
                and not event_type.startswith("region.profile_version.")
                else "RegionProfileVersion"
            ),
            "aggregate_id": str(aggregate_id),
            "aggregate_version": aggregate_version,
            "actor_type": "system" if actor == _SYSTEM_ACTOR else "user",
            "actor_id": str(actor),
            "idempotency_key": key,
            "payload": payload,
            "payload_hash": _hash(payload),
        }
        self.store.events.append(event)

    def _profile_for(self, tenant: UUID, profile_id: Any) -> RegionProfile:
        identity = _uuid(profile_id, "region_profile_id")
        assert identity is not None
        profile = self.store.profiles.get(identity)
        if profile is None:
            raise RegionError("REGION_PROFILE_NOT_FOUND", "profile does not belong to organization")
        if profile.org_id != tenant:
            raise RegionError("TENANT_SCOPE_VIOLATION", "profile is outside this organization")
        _validate_profile(profile)
        return deepcopy(profile)

    def _version_for(self, tenant: UUID, version_id: Any) -> RegionProfileVersion:
        identity = _uuid(version_id, "region_profile_version_id")
        assert identity is not None
        version = self.store.versions.get(identity)
        if version is None:
            raise RegionError("REGION_VERSION_NOT_FOUND", "version does not belong to organization")
        if version.org_id != tenant:
            raise RegionError("TENANT_SCOPE_VIOLATION", "version is outside this organization")
        _validate_version(version)
        return deepcopy(version)

    def create_profile(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        region_code: Any = None,
        profile_id: Any = None,
        created_at: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        **_: Any,
    ) -> RegionProfile:
        self._lock.acquire()
        input_hash: str | None = None
        policy_hash: str | None = None
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            code = _region_code(region_code)
            # The original public helper predated command idempotency and its
            # callers still omit a key.  Give that compatibility path a stable
            # namespace key so repeated legacy calls replay the same command;
            # explicit callers continue to get the normal validation.
            key = (
                _text(idempotency_key, "idempotency_key", maximum=200)
                if idempotency_key is not None
                else f"legacy-profile:{tenant}:{code}"
            )
            _validate_predecessors(predecessor_artifacts, tenant=tenant)
            _guard_nested_tenant(policy_snapshot, tenant, "policy_snapshot")
            policy_hash = _policy_hash(policy_snapshot)
            identity = (
                _uuid(profile_id, "profile_id")
                if profile_id is not None
                else uuid5(_PROFILE_NAMESPACE, f"{tenant}:{code}")
            )
            assert identity is not None
            input_hash = _hash({
                "command": "create_profile",
                "org_id": str(tenant),
                "region_code": code,
                "profile_id": str(identity),
                "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
                "policy_snapshot_hash": policy_hash,
            })
            prior = self.store.get_command(tenant, "profile:create", key)
            if prior is not None:
                if prior["request_hash"] != input_hash:
                    raise RegionError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            by_code = self.store.profile_index.get((tenant, code))
            if by_code is not None:
                raise RegionError("DUPLICATE_REGION", "region code already exists")
            by_id = self.store.profiles.get(identity)
            if by_id is not None:
                if by_id.org_id != tenant:
                    raise RegionError("TENANT_SCOPE_VIOLATION", "profile id belongs to another organization")
                raise RegionError("REGION_PROFILE_ID_CONFLICT", "profile id already exists")
            created = _time(created_at, "created_at") if created_at is not None else self.clock()
            assert created is not None
            profile = RegionProfile(identity, tenant, code, "active", None, created)
            _validate_profile(profile)
            self.store.save_profile(profile)
            self.store.save_command(tenant, "profile:create", key, input_hash, profile)
            self._event(
                event_type="region.profile.created",
                tenant=tenant,
                actor=actor,
                trace=trace,
                key=key,
                aggregate_id=identity,
                aggregate_version=1,
                from_state=None,
                to_state="active",
                command="create",
                snapshot_hash=None,
            )
            self._audit(
                event_type="region.profile.created",
                tenant=str(tenant),
                actor=str(actor),
                trace=trace,
                key=key,
                aggregate_id=str(identity),
                input_hash=input_hash,
                output_hash=_hash(profile.as_contract()),
                input_version=None,
                output_version=1,
                policy_hash=policy_hash,
                status="active",
            )
            return deepcopy(profile)
        except RegionError as error:
            self._reject(
                error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                policy_hash=policy_hash,
            )
            raise
        finally:
            self._lock.release()

    create = create_profile
    register = create_profile
    create_region_profile = create_profile

    def create_draft(
        self,
        *,
        region_profile_id: Any = None,
        profile_id: Any = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        locales: Any = None,
        timezone: Any = None,
        date_number_format: Any = None,
        date_format: Any = None,
        number_format: Any = None,
        units: Any = None,
        currency: Any = None,
        terminology_version: Any = None,
        disclosure_rules: Any = None,
        restricted_topics: Any = None,
        data_residency: Any = None,
        retention_days: Any = None,
        deletion_sla_hours: Any = None,
        platform_eligibility: Any = None,
        policy_snapshot_id: Any = None,
        policy_snapshot_ref: Any = _MISSING,
        data_region: Any = None,
        valid_from: Any = None,
        valid_to: Any = None,
        review_due_at: Any = None,
        expected_current_version_id: Any = _MISSING,
        version_id: Any = None,
        created_at: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        **_: Any,
    ) -> RegionProfileVersion:
        self._lock.acquire()
        input_hash: str | None = None
        policy_hash: str | None = None
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            supplied_ids = [value for value in (region_profile_id, profile_id) if value is not None]
            if not supplied_ids:
                raise RegionError("REGION_PROFILE_INVALID", "region_profile_id is required")
            profile_uuid = _uuid(supplied_ids[0], "region_profile_id")
            assert profile_uuid is not None
            if len(supplied_ids) == 2 and _uuid(supplied_ids[1], "profile_id") != profile_uuid:
                raise RegionError("REGION_PROFILE_INVALID", "profile identifiers disagree")
            profile = self._profile_for(tenant, profile_uuid)
            locale_values = _locales(locales)
            zone = _text(timezone, "timezone", maximum=128)
            try:
                ZoneInfo(zone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise RegionError("REGION_PROFILE_INVALID", "timezone is not an IANA zone") from exc
            if date_number_format is None:
                if date_format is not None and number_format is not None:
                    date_number_format = f"{date_format} | {number_format}"
                elif date_format is not None:
                    date_number_format = date_format
            format_value = _text(date_number_format, "date_number_format", maximum=256)
            units_value = _text(units, "units", maximum=16).lower()
            if units_value not in {"metric", "imperial", "mixed"}:
                raise RegionError("REGION_PROFILE_INVALID", "units is invalid")
            currency_value = _text(currency, "currency", maximum=3)
            if _CURRENCY_RE.fullmatch(currency_value) is None:
                raise RegionError("REGION_PROFILE_INVALID", "currency must be three uppercase letters")
            terminology = _text(terminology_version, "terminology_version", maximum=128)
            # Empty rule/platform collections are valid defaults for a draft;
            # normalize omitted optional inputs before the strict validators.
            disclosure_values = _rules(
                [] if disclosure_rules is None else disclosure_rules,
                "disclosure_rules",
            )
            restricted_values = _rules(
                [] if restricted_topics is None else restricted_topics,
                "restricted_topics",
            )
            if data_residency is None:
                data_residency = data_region
            residency = _text(data_residency, "data_residency", maximum=128)
            retention = _integer(retention_days, "retention_days", maximum=36500)
            deletion_sla = _integer(deletion_sla_hours, "deletion_sla_hours", maximum=87600)
            platform_values = _platforms(
                [] if platform_eligibility is None else platform_eligibility,
            )
            if policy_snapshot_id is None and policy_snapshot_ref is not _MISSING:
                policy_snapshot_id = policy_snapshot_ref
            policy_id = _uuid(policy_snapshot_id, "policy_snapshot_id", required=False)
            start = _time(valid_from, "valid_from")
            end = _time(valid_to, "valid_to")
            review = _time(review_due_at, "review_due_at")
            _validate_interval(start, end, review)
            if expected_current_version_id is _MISSING:
                raise RegionError(
                    "VERSION_PRECONDITION_REQUIRED",
                    "expected_current_version_id is required (use null for the first version)",
                )
            expected_current = _uuid(
                expected_current_version_id,
                "expected_current_version_id",
                required=False,
            )
            explicit_version = _uuid(version_id, "version_id", required=False)
            _validate_predecessors(predecessor_artifacts, tenant=tenant)
            _guard_nested_tenant(policy_snapshot, tenant, "policy_snapshot")
            _guard_nested_tenant(disclosure_values, tenant, "disclosure_rules")
            _guard_nested_tenant(restricted_values, tenant, "restricted_topics")
            policy_hash = _policy_hash(policy_snapshot)
            request_material = {
                "command": "create_draft",
                "org_id": str(tenant),
                "region_profile_id": str(profile_uuid),
                "locales": list(locale_values),
                "timezone": zone,
                "date_number_format": format_value,
                "units": units_value,
                "currency": currency_value,
                "terminology_version": terminology,
                "disclosure_rules": deepcopy(list(disclosure_values)),
                "restricted_topics": deepcopy(list(restricted_values)),
                "data_residency": residency,
                "retention_days": retention,
                "deletion_sla_hours": deletion_sla,
                "platform_eligibility": list(platform_values),
                "policy_snapshot_id": str(policy_id) if policy_id else None,
                "valid_from": _stamp(start) if start else None,
                "valid_to": _stamp(end) if end else None,
                "review_due_at": _stamp(review) if review else None,
                "expected_current_version_id": str(expected_current) if expected_current else None,
                "version_id": str(explicit_version) if explicit_version else None,
                "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
                "policy_snapshot_hash": policy_hash,
            }
            input_hash = _hash(request_material)
            prior = self.store.get_command(tenant, "version:create", key)
            if prior is not None:
                if prior["request_hash"] != input_hash:
                    raise RegionError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            if profile.status != "active":
                raise RegionError("REGION_PROFILE_RETIRED", "retired profile cannot receive versions")
            if profile.current_version_id != expected_current:
                raise RegionError("VERSION_CONFLICT", "current profile pointer changed")
            version_no = 1 + max(
                (
                    item.version_no
                    for item in self.store.versions.values()
                    if item.region_profile_id == profile_uuid
                ),
                default=0,
            )
            identity = explicit_version or uuid5(
                _VERSION_NAMESPACE,
                f"{tenant}:{profile_uuid}:{version_no}",
            )
            assert identity is not None
            existing = self.store.versions.get(identity)
            if existing is not None:
                if existing.org_id != tenant:
                    raise RegionError("TENANT_SCOPE_VIOLATION", "version id belongs to another organization")
                raise RegionError("REGION_VERSION_ID_CONFLICT", "version id already exists")
            created = _time(created_at, "created_at") if created_at is not None else self.clock()
            assert created is not None
            provisional = RegionProfileVersion(
                identity,
                tenant,
                profile_uuid,
                version_no,
                profile.region_code,
                locale_values,
                zone,
                format_value,
                units_value,
                currency_value,
                terminology,
                disclosure_values,
                restricted_values,
                residency,
                retention,
                deletion_sla,
                platform_values,
                policy_id,
                start,
                end,
                review,
                "draft",
                "",
                actor,
                created,
            )
            version = replace(provisional, snapshot_hash=_hash(_version_material(provisional)))
            _validate_version(version)
            self.store.save_version(version)
            self.store.save_command(tenant, "version:create", key, input_hash, version)
            self._event(
                event_type="region.profile_version.created",
                tenant=tenant,
                actor=actor,
                trace=trace,
                key=key,
                aggregate_id=identity,
                aggregate_version=version_no,
                from_state=None,
                to_state="draft",
                command="create_draft",
                snapshot_hash=version.snapshot_hash,
            )
            self._audit(
                event_type="region.profile_version.created",
                tenant=str(tenant),
                actor=str(actor),
                trace=trace,
                key=key,
                aggregate_id=str(identity),
                input_hash=input_hash,
                output_hash=_hash(version.as_contract()),
                input_version=version_no - 1 if version_no > 1 else None,
                output_version=version_no,
                policy_hash=policy_hash,
                status="draft",
            )
            return deepcopy(version)
        except RegionError as error:
            self._reject(
                error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                policy_hash=policy_hash,
            )
            raise
        finally:
            self._lock.release()

    create_version = create_draft
    draft_version = create_draft
    draft = create_draft

    def activate_version(
        self,
        *,
        version_id: Any = None,
        region_profile_version_id: Any = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        expected_version: Any = None,
        if_match: Any = None,
        policy_snapshot_id: Any = _MISSING,
        valid_from: Any = _MISSING,
        valid_to: Any = _MISSING,
        review_due_at: Any = _MISSING,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        **_: Any,
    ) -> RegionProfileVersion:
        self._lock.acquire()
        input_hash: str | None = None
        policy_hash: str | None = None
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            supplied_ids = [value for value in (version_id, region_profile_version_id) if value is not None]
            if not supplied_ids:
                raise RegionError("REGION_PROFILE_INVALID", "version_id is required")
            identity = _uuid(supplied_ids[0], "version_id")
            assert identity is not None
            if len(supplied_ids) == 2 and _uuid(supplied_ids[1], "region_profile_version_id") != identity:
                raise RegionError("REGION_PROFILE_INVALID", "version identifiers disagree")
            version = self._version_for(tenant, identity)
            required_version = _if_match(expected_version, if_match)
            _validate_predecessors(predecessor_artifacts, tenant=tenant)
            _guard_nested_tenant(policy_snapshot, tenant, "policy_snapshot")
            policy_hash = _policy_hash(policy_snapshot)
            policy_id = (
                version.policy_snapshot_id
                if policy_snapshot_id is _MISSING
                else _uuid(policy_snapshot_id, "policy_snapshot_id", required=False)
            )
            start = version.valid_from if valid_from is _MISSING else _time(valid_from, "valid_from")
            end = version.valid_to if valid_to is _MISSING else _time(valid_to, "valid_to")
            review = (
                version.review_due_at
                if review_due_at is _MISSING
                else _time(review_due_at, "review_due_at")
            )
            _validate_interval(start, end, review)
            input_hash = _hash({
                "command": "activate",
                "org_id": str(tenant),
                "version_id": str(identity),
                "expected_version": required_version,
                "policy_snapshot_id": str(policy_id) if policy_id else None,
                "valid_from": _stamp(start) if start else None,
                "valid_to": _stamp(end) if end else None,
                "review_due_at": _stamp(review) if review else None,
                "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
                "policy_snapshot_hash": policy_hash,
            })
            prior = self.store.get_command(tenant, "version:activate", key)
            if prior is not None:
                if prior["request_hash"] != input_hash:
                    raise RegionError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            if version.version_no != required_version:
                raise RegionError("VERSION_CONFLICT", "version precondition is stale")
            if version.status != "draft":
                raise RegionError("INVALID_STATE_TRANSITION", "only a draft version can be activated")
            if policy_id is None:
                raise RegionError("ACTIVATION_REQUIREMENTS_MISSING", "policy_snapshot_id is required")
            if start is None or end is None:
                raise RegionError("ACTIVATION_REQUIREMENTS_MISSING", "valid_from and valid_to are required")
            if version.deletion_sla_hours <= 0 or not version.data_residency:
                raise RegionError(
                    "ACTIVATION_REQUIREMENTS_MISSING",
                    "positive deletion SLA and data residency are required",
                )
            profile = self._profile_for(tenant, version.region_profile_id)
            if profile.status != "active":
                raise RegionError("REGION_PROFILE_RETIRED", "retired profile cannot activate a version")
            provisional = replace(
                version,
                policy_snapshot_id=policy_id,
                valid_from=start,
                valid_to=end,
                review_due_at=review,
                status="active",
            )
            active = replace(provisional, snapshot_hash=_hash(_version_material(provisional)))
            _validate_version(active)
            previous: RegionProfileVersion | None = None
            if profile.current_version_id is not None and profile.current_version_id != identity:
                previous = self._version_for(tenant, profile.current_version_id)
                if previous.status != "active":
                    raise RegionError("VERSION_CONFLICT", "current pointer does not reference an active version")
                previous = replace(previous, status="retired")
                _validate_version(previous)
                self.store.save_version(previous)
            self.store.save_version(active)
            updated_profile = replace(profile, current_version_id=identity)
            _validate_profile(updated_profile)
            self.store.save_profile(updated_profile)
            self.store.save_command(tenant, "version:activate", key, input_hash, active)
            if previous is not None:
                self._event(
                    event_type="region.profile_version.retired",
                    tenant=tenant,
                    actor=actor,
                    trace=trace,
                    key=key,
                    aggregate_id=previous.id,
                    aggregate_version=previous.version_no,
                    from_state="active",
                    to_state="retired",
                    command="retire",
                    snapshot_hash=previous.snapshot_hash,
                    reason=f"replaced by {identity}",
                )
            self._event(
                event_type="region.profile_version.activated",
                tenant=tenant,
                actor=actor,
                trace=trace,
                key=key,
                aggregate_id=identity,
                aggregate_version=active.version_no,
                from_state="draft",
                to_state="active",
                command="activate",
                snapshot_hash=active.snapshot_hash,
            )
            self._audit(
                event_type="region.profile_version.activated",
                tenant=str(tenant),
                actor=str(actor),
                trace=trace,
                key=key,
                aggregate_id=str(identity),
                input_hash=input_hash,
                output_hash=_hash(active.as_contract()),
                input_version=version.version_no,
                output_version=active.version_no,
                policy_hash=policy_hash,
                status="active",
                reason=f"replaced {previous.id}" if previous else None,
            )
            return deepcopy(active)
        except RegionError as error:
            self._reject(
                error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                policy_hash=policy_hash,
            )
            raise
        finally:
            self._lock.release()

    activate = activate_version
    publish = activate_version

    def retire_version(
        self,
        *,
        version_id: Any = None,
        region_profile_version_id: Any = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        expected_version: Any = None,
        if_match: Any = None,
        reason: Any = None,
        policy_snapshot: Any = None,
        **_: Any,
    ) -> RegionProfileVersion:
        self._lock.acquire()
        input_hash: str | None = None
        policy_hash: str | None = None
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            supplied_ids = [value for value in (version_id, region_profile_version_id) if value is not None]
            if not supplied_ids:
                raise RegionError("REGION_PROFILE_INVALID", "version_id is required")
            identity = _uuid(supplied_ids[0], "version_id")
            assert identity is not None
            if len(supplied_ids) == 2 and _uuid(supplied_ids[1], "region_profile_version_id") != identity:
                raise RegionError("REGION_PROFILE_INVALID", "version identifiers disagree")
            required_version = _if_match(expected_version, if_match)
            reason_text = _text(reason, "reason", maximum=1024)
            _guard_nested_tenant(policy_snapshot, tenant, "policy_snapshot")
            policy_hash = _policy_hash(policy_snapshot)
            input_hash = _hash({
                "command": "retire",
                "org_id": str(tenant),
                "version_id": str(identity),
                "expected_version": required_version,
                "reason": reason_text,
                "policy_snapshot_hash": policy_hash,
            })
            prior = self.store.get_command(tenant, "version:retire", key)
            if prior is not None:
                if prior["request_hash"] != input_hash:
                    raise RegionError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            version = self._version_for(tenant, identity)
            if version.version_no != required_version:
                raise RegionError("VERSION_CONFLICT", "version precondition is stale")
            if version.status != "active":
                raise RegionError("INVALID_STATE_TRANSITION", "only an active version can be retired")
            retired = replace(version, status="retired")
            _validate_version(retired)
            self.store.save_version(retired)
            profile = self._profile_for(tenant, version.region_profile_id)
            if profile.current_version_id == identity:
                profile = replace(profile, current_version_id=None)
                _validate_profile(profile)
                self.store.save_profile(profile)
            self.store.save_command(tenant, "version:retire", key, input_hash, retired)
            self._event(
                event_type="region.profile_version.retired",
                tenant=tenant,
                actor=actor,
                trace=trace,
                key=key,
                aggregate_id=identity,
                aggregate_version=retired.version_no,
                from_state="active",
                to_state="retired",
                command="retire",
                snapshot_hash=retired.snapshot_hash,
                reason=reason_text,
            )
            self._audit(
                event_type="region.profile_version.retired",
                tenant=str(tenant),
                actor=str(actor),
                trace=trace,
                key=key,
                aggregate_id=str(identity),
                input_hash=input_hash,
                output_hash=_hash(retired.as_contract()),
                input_version=version.version_no,
                output_version=retired.version_no,
                policy_hash=policy_hash,
                status="retired",
                reason=reason_text,
            )
            return deepcopy(retired)
        except RegionError as error:
            self._reject(
                error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
                policy_hash=policy_hash,
            )
            raise
        finally:
            self._lock.release()

    retire = retire_version

    def retire_profile(
        self,
        *,
        profile_id: Any,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        reason: Any = None,
        **_: Any,
    ) -> RegionProfile:
        self._lock.acquire()
        input_hash: str | None = None
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            identity = _uuid(profile_id, "profile_id")
            assert identity is not None
            reason_text = _text(reason, "reason", maximum=1024)
            input_hash = _hash({
                "command": "retire_profile",
                "org_id": str(tenant),
                "profile_id": str(identity),
                "reason": reason_text,
            })
            prior = self.store.get_command(tenant, "profile:retire", key)
            if prior is not None:
                if prior["request_hash"] != input_hash:
                    raise RegionError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return deepcopy(prior["response"])
            profile = self._profile_for(tenant, identity)
            if profile.status != "active":
                raise RegionError("INVALID_STATE_TRANSITION", "only an active profile can be retired")
            if profile.current_version_id is not None:
                raise RegionError("ACTIVE_VERSION_EXISTS", "retire the current version first")
            retired = replace(profile, status="retired")
            _validate_profile(retired)
            self.store.save_profile(retired)
            self.store.save_command(tenant, "profile:retire", key, input_hash, retired)
            self._audit(
                event_type="region.profile.retired",
                tenant=str(tenant),
                actor=str(actor),
                trace=trace,
                key=key,
                aggregate_id=str(identity),
                input_hash=input_hash,
                output_hash=_hash(retired.as_contract()),
                input_version=1,
                output_version=1,
                policy_hash=None,
                status="retired",
                reason=reason_text,
            )
            return deepcopy(retired)
        except RegionError as error:
            self._reject(
                error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
                input_hash=input_hash,
            )
            raise
        finally:
            self._lock.release()

    def get_profile(
        self,
        *,
        profile_id: Any,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> RegionProfile:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        return self._profile_for(tenant, profile_id)

    def get_version(
        self,
        *,
        version_id: Any,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> RegionProfileVersion:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        return self._version_for(tenant, version_id)

    def list_profiles(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> tuple[RegionProfile, ...]:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        return tuple(
            deepcopy(item)
            for item in sorted(
                (value for value in self.store.profiles.values() if value.org_id == tenant),
                key=lambda value: (value.region_code, str(value.id)),
            )
        )

    def list_versions(
        self,
        *,
        profile_id: Any,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> tuple[RegionProfileVersion, ...]:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        profile = self._profile_for(tenant, profile_id)
        return tuple(
            deepcopy(item)
            for item in sorted(
                (
                    value
                    for value in self.store.versions.values()
                    if value.region_profile_id == profile.id
                ),
                key=lambda value: value.version_no,
            )
        )

    def audit_for(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant, __, ___ = _resolve_tenant(org_id, tenant_context)
        return tuple(deepcopy(item) for item in self.store.audit if item.get("org_id") == str(tenant))

    def publish_version(
        self,
        *,
        org_id: Any,
        profile_id: Any,
        locales: Any,
        timezone: Any,
        date_format: Any,
        number_format: Any,
        units: Any,
        currency: Any,
        retention_days: Any,
        deletion_sla_hours: Any,
        policy_snapshot_ref: Any,
        valid_from: Any,
        valid_to: Any,
        expected_current_version_id: Any = None,
        idempotency_key: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        terminology_version: Any = None,
        disclosure_rules: Any = None,
        restricted_topics: Any = None,
        data_residency: Any = None,
        platform_eligibility: Any = None,
        review_due_at: Any = None,
        **kwargs: Any,
    ) -> RegionProfileVersion:
        """Compatibility helper: create a complete draft and activate it."""

        profile_uuid = _uuid(profile_id, "profile_id")
        assert profile_uuid is not None
        try:
            policy_id = _uuid(policy_snapshot_ref, "policy_snapshot_ref")
        except RegionError:
            policy_id = uuid5(NAMESPACE_URL, f"geo-region-policy:{policy_snapshot_ref}")
        profile = self.profiles.get(profile_uuid)
        current_pointer = profile.current_version_id if profile is not None else None
        # The compatibility helper derives an internal idempotency namespace
        # when callers omit a key.  Include both the caller's expected pointer
        # and the pointer observed at the start of this command.  A repeated
        # stale publish must therefore re-run the optimistic concurrency check
        # instead of replaying an earlier successful draft.
        base_key = (
            _text(idempotency_key, "idempotency_key", maximum=180)
            if idempotency_key is not None
            else f"legacy-publish-{_hash([str(profile_uuid), str(expected_current_version_id), str(current_pointer), policy_snapshot_ref, valid_from, valid_to])[:32]}"
        )
        residency = data_residency if data_residency is not None else (
            profile.region_code if profile is not None else "unspecified"
        )
        draft = self.create_draft(
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
            idempotency_key=f"{base_key}:draft",
            profile_id=profile_uuid,
            locales=locales,
            timezone=timezone,
            date_number_format=f"{_text(date_format, 'date_format', maximum=128)} | {_text(number_format, 'number_format', maximum=128)}",
            units=units,
            currency=currency,
            terminology_version=terminology_version or str(policy_snapshot_ref),
            disclosure_rules=disclosure_rules or [],
            restricted_topics=restricted_topics or [],
            data_residency=residency,
            retention_days=retention_days,
            deletion_sla_hours=deletion_sla_hours,
            platform_eligibility=platform_eligibility or [],
            policy_snapshot_id=policy_id,
            valid_from=valid_from,
            valid_to=valid_to,
            review_due_at=review_due_at,
            expected_current_version_id=expected_current_version_id,
            **kwargs,
        )
        return self.activate_version(
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
            idempotency_key=f"{base_key}:activate",
            version_id=draft.id,
            expected_version=draft.version_no,
        )


GeoRegionService = InMemoryRegionService
RegionProfileService = InMemoryRegionService


__all__ = [
    "RegionError",
    "RegionProfile",
    "RegionProfileVersion",
    "InMemoryRegionStore",
    "InMemoryRegionService",
    "GeoRegionService",
    "RegionProfileService",
]
