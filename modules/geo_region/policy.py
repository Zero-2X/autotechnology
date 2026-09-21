"""Offline GEO_REGION-002 policy decisions.

The services in this module consume an immutable :class:`RegionProfileVersion`
from :mod:`modules.geo_region.service` and page/data snapshots supplied by a
caller.  They deliberately do not fetch a page, call a provider, mutate a
region version, or delete data.  A decision or deletion plan is an append-only
projection that can be handed to a downstream worker.

The implementation accepts both the dataclasses used by GEO_REGION-001 and
plain mappings.  This keeps the port useful to the site module while making
the contract output stable and easy to replay in tests.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from threading import RLock
from collections.abc import Mapping as ABCMapping
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence
from urllib.parse import urlsplit
from uuid import UUID, NAMESPACE_URL, uuid5

from jsonschema import Draft202012Validator, FormatChecker

from .service import (
    RegionError,
    RegionProfileVersion,
    _canonical,
    _guard_nested_tenant,
    _hash,
    _locale,
    _region_code,
    _resolve_tenant,
    _stamp,
    _text,
    _time,
    _uuid,
)


ROOT = Path(__file__).resolve().parents[2]
_CHECK_SCHEMA = json.loads(
    (ROOT / "packages/contracts/jsonschema/region-check-decision.schema.json").read_text(encoding="utf-8")
)
_DELETE_SCHEMA = json.loads(
    (ROOT / "packages/contracts/jsonschema/region-deletion-policy.schema.json").read_text(encoding="utf-8")
)
_CHECK_VALIDATOR = Draft202012Validator(_CHECK_SCHEMA, format_checker=FormatChecker())
_DELETE_VALIDATOR = Draft202012Validator(_DELETE_SCHEMA, format_checker=FormatChecker())

_POLICY_NAMESPACE = UUID("f88a6e43-84d1-5f5d-941c-d4e09c8abf1b")
_DECISION_NAMESPACE = UUID("ed1102f8-c7a3-5c67-a9e4-e7e76c76941b")
_DELETE_NAMESPACE = UUID("b3a559a7-9fb7-5dc0-b53f-0a4c636183e9")
_SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
_URL_RE = re.compile(r"^https?://[^?#]+$", re.IGNORECASE)
_READY_PAGE_STATES = frozenset({"ready", "published"})
_ACTIVE_VERSION_STATES = frozenset({"active"})
_TARGETS = ("relational_db", "object_storage", "vector_index", "cache", "export_package")
_SENSITIVE_ERROR_RE = re.compile(r"(?i)\b(?:token|secret|password|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+")


class RegionPolicyError(RegionError):
    """Stable error raised for malformed or cross-tenant policy commands."""


# A few callers use the shorter name when wiring the service as a port.
GeoRegionPolicyError = RegionPolicyError


def _json_safe(value: Any) -> Any:
    """Return a bounded, non-sensitive JSON representation for evidence."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items() if str(key).lower() not in {
            "body", "content", "raw", "html", "markdown", "answer", "text_body", "payload"
        }}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_time(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    parsed = _time(value, field) if value is not None else default
    if parsed is None:
        raise RegionPolicyError("REGION_POLICY_INVALID", f"{field} is required")
    return parsed


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "as_contract"):
        candidate = value.as_contract()
        if isinstance(candidate, Mapping):
            return candidate
    raise RegionPolicyError("REGION_POLICY_INVALID", f"{field} must be an object")


def _value(value: Any, *names: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        for name in names:
            if name in value:
                return value[name]
    else:
        for name in names:
            if hasattr(value, name):
                return getattr(value, name)
    return default


def _normalise_version(value: Any) -> Mapping[str, Any]:
    candidate = _mapping(value, "region_version")
    # Dataclass as_contract already emits canonical names; these aliases are
    # accepted for adapters from the pre-GEO_REGION-001 site code.
    result = dict(candidate)
    if "id" not in result and "region_profile_version_id" in result:
        result["id"] = result["region_profile_version_id"]
    if "region_profile_id" not in result and "profile_id" in result:
        result["region_profile_id"] = result["profile_id"]
    if "data_residency" not in result and "data_region" in result:
        result["data_residency"] = result["data_region"]
    if "policy_snapshot_id" not in result and "policy_snapshot_ref" in result:
        result["policy_snapshot_id"] = result["policy_snapshot_ref"]
    for key in ("locales", "restricted_topics", "disclosure_rules", "platform_eligibility"):
        if result.get(key) is None:
            result[key] = []
    return result


def _version_id(version: Mapping[str, Any]) -> UUID:
    identity = _uuid(version.get("id", version.get("region_profile_version_id")), "region_profile_version_id")
    assert identity is not None
    return identity


def _profile_id(version: Mapping[str, Any]) -> UUID | None:
    raw = version.get("region_profile_id", version.get("profile_id"))
    return None if raw is None else _uuid(raw, "region_profile_id")


def _field(page: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in page:
            return page[name]
    return default


def _canonical_url(value: Any) -> str:
    if not isinstance(value, str):
        raise RegionPolicyError("REGION_POLICY_INVALID", "canonical_url must be a URL")
    url = value.strip()
    parts = urlsplit(url)
    if not _URL_RE.fullmatch(url) or parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        raise RegionPolicyError("REGION_POLICY_INVALID", "canonical_url must be an absolute URL without query or fragment")
    # Fragments/query strings are excluded by the regex.  Empty paths are
    # canonicalized to '/' so equivalent candidates deduplicate.
    path = parts.path or "/"
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def _normalise_locale(value: Any) -> str:
    try:
        return _locale(value)
    except RegionError as exc:
        raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc


def _rule_name(rule: Any) -> str | None:
    if isinstance(rule, str) and rule.strip():
        return rule.strip()
    if isinstance(rule, Mapping):
        for key in ("id", "name", "topic", "term", "text", "disclosure", "code"):
            raw = rule.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
    return None


def _list_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray, Mapping)):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, Mapping):
            name = _rule_name(item)
            if name:
                result.append(name)
    return tuple(result)


def _contains_ci(values: Iterable[str], target: str) -> bool:
    needle = target.casefold()
    return any(item.casefold() == needle for item in values)


def _check(code: str, status: str, field: str, observed: Any, expected: Any, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "field": field,
        "observed": _json_safe(observed),
        "expected": _json_safe(expected),
        "message": message[:512],
    }


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message[:512]}


def _redact_error(value: Any) -> str:
    """Bound queue/audit error text without retaining credential material."""

    normalized = " ".join(str(value).replace("\n", " ").split())
    normalized = _SENSITIVE_ERROR_RE.sub("[REDACTED]", normalized)
    return normalized[:512] or "policy handoff failed"


def _version_snapshot_hash(version: Mapping[str, Any]) -> str:
    raw = version.get("snapshot_hash", version.get("content_hash"))
    if isinstance(raw, str) and re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        return raw.lower()
    return _hash(_json_safe(version))


def _validate_supplied_version_snapshot(version: Mapping[str, Any]) -> None:
    """Fail closed when an adapter supplies a tampered immutable snapshot.

    GEO_REGION-001 computes ``snapshot_hash`` from the contract fields while
    excluding runtime identity/status metadata.  Mappings from older ports may
    not contain every field, so validation is performed only when a hash and
    enough material to reproduce it are present; a missing hash is handled by
    the deterministic projection hash used for evidence.
    """

    supplied = version.get("snapshot_hash", version.get("content_hash"))
    if not isinstance(supplied, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", supplied):
        return
    material = _json_safe(dict(version))
    for name in ("id", "status", "snapshot_hash", "content_hash", "created_by", "created_at"):
        material.pop(name, None)
    # Legacy aliases are not part of the GEO_REGION-001 hash material.
    for name in ("profile_id", "policy_snapshot_ref", "date_format", "number_format", "data_region"):
        material.pop(name, None)
    expected = _hash(material)
    if expected.lower() != supplied.lower():
        raise RegionPolicyError("REGION_SNAPSHOT_HASH_MISMATCH", "region version snapshot hash does not match its configuration")


@dataclass(frozen=True)
class RegionCheckDecision(ABCMapping[str, Any]):
    """Immutable contract projection returned by :meth:`check_page`."""

    value: Mapping[str, Any]

    def as_contract(self) -> dict[str, Any]:
        return deepcopy(dict(self.value))

    def __getitem__(self, key: str) -> Any:
        return self.value[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.value.get(key, default)

    def __iter__(self):
        return iter(self.value)

    def __len__(self) -> int:
        return len(self.value)

    def __getattr__(self, name: str) -> Any:
        if name in self.value:
            return self.value[name]
        raise AttributeError(name)


@dataclass(frozen=True)
class RegionDeletionPlan(ABCMapping[str, Any]):
    """Immutable deletion-policy projection; it performs no deletion."""

    value: Mapping[str, Any]

    def as_contract(self) -> dict[str, Any]:
        return deepcopy(dict(self.value))

    def __getitem__(self, key: str) -> Any:
        return self.value[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.value.get(key, default)

    def __iter__(self):
        return iter(self.value)

    def __len__(self) -> int:
        return len(self.value)

    def __getattr__(self, name: str) -> Any:
        if name in self.value:
            return self.value[name]
        raise AttributeError(name)


class InMemoryRegionPolicyStore:
    """Append-only projections and command replay records."""

    def __init__(self) -> None:
        self.decisions: dict[UUID, dict[str, Any]] = {}
        self.deletion_plans: dict[UUID, dict[str, Any]] = {}
        self.commands: dict[tuple[UUID, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def get_command(self, tenant: UUID, namespace: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.commands.get((tenant, namespace, key))
            return deepcopy(value) if value is not None else None

    def save_command(self, tenant: UUID, namespace: str, key: str, request_hash: str, response: Mapping[str, Any]) -> None:
        with self._lock:
            identity = (tenant, namespace, key)
            prior = self.commands.get(identity)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise RegionPolicyError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return
            self.commands[identity] = {"request_hash": request_hash, "response": deepcopy(dict(response))}


class _PolicyBase:
    task_id = "GEO_REGION-002"
    rule_version = "geo-region-002.v1"

    def __init__(
        self,
        *,
        region_service: Any = None,
        region_port: Any = None,
        store: InMemoryRegionPolicyStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.region_service = region_service or region_port
        self.store = store or InMemoryRegionPolicyStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.audit = self.store.audit
        self._lock = RLock()

    def _tenant(self, org_id: Any, tenant_context: Mapping[str, Any] | None, actor_id: Any, trace_id: Any) -> tuple[UUID, UUID, str]:
        try:
            return _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
        except RegionError as exc:
            raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc

    @staticmethod
    def _guard(value: Any, tenant: UUID, field: str) -> None:
        """Translate the shared tenant guard into this module's stable error type."""
        try:
            _guard_nested_tenant(value, tenant, field)
        except RegionError as exc:
            raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc

    def _version(self, tenant: UUID, version_id: Any, supplied: Any = None) -> Mapping[str, Any]:
        if supplied is not None:
            version = _normalise_version(supplied)
            owner = _uuid(version.get("org_id"), "region_version.org_id") if version.get("org_id") is not None else tenant
            if owner != tenant:
                raise RegionPolicyError("TENANT_SCOPE_VIOLATION", "region version is outside this organization")
            if _version_id(version) != _uuid(version_id, "region_profile_version_id"):
                raise RegionPolicyError("REGION_VERSION_NOT_FOUND", "region version identifier does not match")
            _validate_supplied_version_snapshot(version)
            supplied_profile_status = version.get("profile_status")
            if supplied_profile_status is not None and str(supplied_profile_status).lower() != "active":
                # Keep the failure code aligned with a resolved profile.  The
                # caller can still use a real service source to obtain a
                # profile and receive the same deterministic result.
                raise RegionPolicyError("REGION_VERSION_INACTIVE", "region profile is not active")
            return version
        if self.region_service is None:
            raise RegionPolicyError("REGION_VERSION_NOT_FOUND", "a region version source is required")
        getter = getattr(self.region_service, "get_version", None)
        if getter is None:
            getter = getattr(self.region_service, "version", None)
        if getter is None:
            raise RegionPolicyError("REGION_VERSION_NOT_FOUND", "region version source cannot resolve versions")
        try:
            value = getter(version_id=version_id, org_id=tenant)
        except TypeError:
            value = getter(version_id, tenant)
        except RegionError as exc:
            if exc.code in {"REGION_VERSION_NOT_FOUND", "TENANT_SCOPE_VIOLATION"}:
                raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc
            raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc
        version = _normalise_version(value)
        try:
            _validate_supplied_version_snapshot(version)
        except RegionError as exc:
            raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc
        return version

    def _profile_status(self, tenant: UUID, version: Mapping[str, Any]) -> str | None:
        profile_id = _profile_id(version)
        if profile_id is None or self.region_service is None:
            return None
        getter = getattr(self.region_service, "get_profile", None)
        if getter is None:
            return None
        try:
            profile = getter(profile_id=profile_id, org_id=tenant)
        except TypeError:
            profile = getter(profile_id, tenant)
        except RegionError as exc:
            raise RegionPolicyError(exc.code, str(exc), details=exc.details) from exc
        return str(_value(profile, "status", default="")).lower() or None

    def _save_audit(self, *, tenant: UUID, actor: UUID, trace: str, key: str | None, action: str, status: str, reason: str | None = None, input_hash: str | None = None, output_hash: str | None = None) -> None:
        self.store.audit.append({
            "task_id": self.task_id,
            "event_type": action,
            "org_id": str(tenant),
            "actor_id": str(actor),
            "trace_id": trace,
            "idempotency_key": key,
            "status": status,
            "reason": reason,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "duration_ms": 0,
            "cost_cents": 0,
            "created_at": _stamp(self.clock()),
        })


class RegionEligibilityService(_PolicyBase):
    """Evaluate a page snapshot against one explicit immutable region version."""

    def _page(self, page_snapshot: Any = None, page: Any = None, page_version: Any = None) -> Mapping[str, Any]:
        value = page_snapshot if page_snapshot is not None else page if page is not None else page_version
        if value is None:
            raise RegionPolicyError("REGION_POLICY_INVALID", "page_snapshot is required")
        return _mapping(value, "page_snapshot")

    def check_page(
        self,
        page_snapshot: Any = None,
        *,
        page: Any = None,
        page_version: Any = None,
        region_profile_version_id: Any = None,
        version_id: Any = None,
        region_version: Any = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        market: Any = None,
        platform: Any = None,
        evaluated_at: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        **kwargs: Any,
    ) -> RegionCheckDecision:
        page_map = self._page(page_snapshot, page, page_version)
        identity_value = region_profile_version_id if region_profile_version_id is not None else version_id
        if identity_value is None:
            identity_value = _field(page_map, "region_profile_version_id", "region_version_id")
        if identity_value is None:
            raise RegionPolicyError("REGION_VERSION_NOT_FOUND", "region_profile_version_id is required")
        tenant, actor, trace = self._tenant(org_id, tenant_context, actor_id, trace_id)
        self._guard(page_map, tenant, "page_snapshot")
        if predecessor_artifacts is not None:
            self._guard(predecessor_artifacts, tenant, "predecessor_artifacts")
        self._guard(policy_snapshot, tenant, "policy_snapshot")
        version = self._version(tenant, identity_value, region_version)
        version_uuid = _version_id(version)
        embedded_version = _field(page_map, "region_profile_version_id", "region_version_id")
        if embedded_version is not None and _uuid(embedded_version, "page_snapshot.region_profile_version_id") != version_uuid:
            raise RegionPolicyError("REGION_VERSION_NOT_FOUND", "page snapshot references a different region version")
        at = _parse_time(evaluated_at, "evaluated_at", default=self.clock())
        key = _text(idempotency_key, "idempotency_key", maximum=200) if idempotency_key is not None else f"check:{version_uuid}:{_hash(_json_safe(page_map))[:24]}"
        locale_raw = _field(page_map, "locale", "language")
        locale = _normalise_locale(locale_raw)
        market_value = market if market is not None else _field(page_map, "market", "region", "region_code")
        market_norm = str(market_value).strip().upper() if market_value is not None else None
        platform_value = platform if platform is not None else _field(page_map, "platform", "channel")
        platform_norm = str(platform_value).strip() if platform_value is not None else None
        page_id_raw = _field(page_map, "page_version_id", "id")
        page_id = None if page_id_raw is None else _uuid(page_id_raw, "page_version_id")
        page_key = _text(_field(page_map, "page_key", "key", "canonical_key", default=str(page_id or "page")), "page_key", maximum=512)
        policy_ref_raw = version.get("policy_snapshot_ref", version.get("policy_snapshot_id"))
        policy_ref = None if policy_ref_raw is None else str(policy_ref_raw)
        request_material = {
            "org_id": str(tenant),
            "version_id": str(version_uuid),
            "page": _json_safe(page_map),
            "market": market_norm,
            "platform": platform_norm,
            # An omitted clock value is not part of the command payload.  It
            # therefore replays the original decision even when a later call
            # observes a different wall clock; an explicit timestamp remains
            # part of the hash because it changes interval semantics.
            "evaluated_at": _stamp(at) if evaluated_at is not None else None,
            "policy_snapshot": _json_safe(policy_snapshot),
        }
        request_hash = _hash(request_material)
        # The public contract names this digest ``input_snapshot_hash`` and
        # existing consumers also use it as the idempotency request hash.
        # Keep the two equal so replay/audit joins do not need a second lookup.
        input_snapshot_hash = request_hash
        prior = self.store.get_command(tenant, "region:check_page", key)
        if prior is not None:
            if prior["request_hash"] != request_hash:
                raise RegionPolicyError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return RegionCheckDecision(prior["response"])

        checks: list[dict[str, Any]] = []
        reasons: list[dict[str, str]] = []
        required_disclosures: list[str] = []
        matched_restrictions: list[str] = []

        def add_pass(code: str, field: str, observed: Any, expected: Any, message: str) -> None:
            checks.append(_check(code, "pass", field, observed, expected, message))

        def add_fail(code: str, field: str, observed: Any, expected: Any, message: str) -> None:
            checks.append(_check(code, "fail", field, observed, expected, message))
            reasons.append(_reason(code, message))

        # The reference and tenant have already been resolved above.  Keep an
        # explicit check in the evidence so consumers can audit ordering.
        add_pass("TENANT_SCOPE", "org_id", tenant, tenant, "tenant context matches page and region version")
        page_state = _field(page_map, "status", "state", default=None)
        if page_state is not None and str(page_state).lower() not in _READY_PAGE_STATES:
            add_fail("REGION_CONTENT_BLOCKED", "page.status", page_state, sorted(_READY_PAGE_STATES), "page is not publicly eligible")
        elif page_state is not None:
            add_pass("PAGE_PUBLIC", "page.status", page_state, sorted(_READY_PAGE_STATES), "page is publicly eligible")
        profile_status = self._profile_status(tenant, version)
        version_status = str(version.get("status", "")).lower()
        if profile_status is not None and profile_status != "active":
            add_fail("REGION_VERSION_INACTIVE", "profile.status", profile_status, "active", "region profile is not active")
        elif version_status not in _ACTIVE_VERSION_STATES:
            add_fail("REGION_VERSION_INACTIVE", "version.status", version_status, "active", "region version is not active")
        else:
            add_pass("REGION_VERSION_ACTIVE", "version.status", version_status, "active", "region version is active")

        valid_from = _time(version.get("valid_from"), "valid_from")
        valid_to = _time(version.get("valid_to"), "valid_to")
        if (valid_from is not None and at < valid_from) or (valid_to is not None and at >= valid_to):
            add_fail("REGION_VERSION_EXPIRED", "validity", _stamp(at), {"valid_from": _stamp(valid_from) if valid_from else None, "valid_to": _stamp(valid_to) if valid_to else None}, "region version is outside its validity interval")
        else:
            add_pass("REGION_VERSION_VALID", "validity", _stamp(at), {"valid_from": _stamp(valid_from) if valid_from else None, "valid_to": _stamp(valid_to) if valid_to else None}, "region version is valid at evaluation time")

        allowed_locales = tuple(_normalise_locale(item) for item in version.get("locales", ()) or ())
        if not _contains_ci(allowed_locales, locale):
            add_fail("LOCALE_NOT_ALLOWED", "locale", locale, allowed_locales, "page locale is not allowed by region version")
        else:
            add_pass("LOCALE_ALLOWED", "locale", locale, allowed_locales, "page locale is allowed")

        version_region = version.get("region_code", version.get("region"))
        if market_norm is not None and version_region is not None and market_norm != str(version_region).upper():
            # An explicit list of markets on an adapter can widen the version
            # code check; otherwise a concrete mismatch is a denial.
            allowed_markets = _list_strings(version.get("markets", version.get("market_allowlist")))
            if not _contains_ci(allowed_markets, market_norm):
                add_fail("MARKET_NOT_ALLOWED", "market", market_norm, version_region, "market does not match region version")
            else:
                add_pass("MARKET_ALLOWED", "market", market_norm, allowed_markets, "market is in the configured allowlist")
        else:
            add_pass("MARKET_ALLOWED", "market", market_norm, version_region, "market is compatible with region version")

        data_region = _field(page_map, "data_region", "data_residency")
        residency = version.get("data_residency")
        if data_region is not None and residency is not None and str(data_region).casefold() != str(residency).casefold():
            add_fail("REGION_CONTENT_BLOCKED", "data_region", data_region, residency, "page data region is not permitted")
        else:
            add_pass("DATA_RESIDENCY_ALLOWED", "data_region", data_region, residency, "data residency is compatible")

        page_platforms = _list_strings(_field(page_map, "platforms", default=None))
        if platform_norm:
            page_platforms = tuple(dict.fromkeys((*page_platforms, platform_norm)))
        allowed_platforms = _list_strings(version.get("platform_eligibility"))
        if page_platforms and allowed_platforms and any(not _contains_ci(allowed_platforms, item) for item in page_platforms):
            add_fail("REGION_CONTENT_BLOCKED", "platform", page_platforms, allowed_platforms, "platform is not eligible for region version")
        else:
            add_pass("PLATFORM_ALLOWED", "platform", page_platforms, allowed_platforms, "platform is eligible")

        page_region = (
            market_norm
            or str(_field(page_map, "region", "region_code", default="")).upper()
            or (str(version_region).upper() if version_region is not None else None)
        )
        blocked_regions = _list_strings(_field(page_map, "blocked_regions", "disabled_regions"))
        permitted_regions = _list_strings(_field(page_map, "permitted_regions", "allowed_regions"))
        region_disabled = _field(page_map, "region_disabled", default=False) is True
        policy = _field(page_map, "region_policy", default={})
        if isinstance(policy, Mapping):
            region_disabled = region_disabled or policy.get("disabled", policy.get("region_disabled", False)) is True
            blocked_regions = tuple(dict.fromkeys((*blocked_regions, *_list_strings(policy.get("blocked_regions")))))
            permitted_regions = tuple(dict.fromkeys((*permitted_regions, *_list_strings(policy.get("permitted_regions")))))
        if region_disabled or (page_region and _contains_ci(blocked_regions, page_region)) or (permitted_regions and page_region and not _contains_ci(permitted_regions, page_region)):
            add_fail("REGION_CONTENT_BLOCKED", "region_policy", page_region, {"blocked_regions": blocked_regions, "permitted_regions": permitted_regions}, "page is disabled in this region")
        else:
            add_pass("REGION_CONTENT_ALLOWED", "region_policy", page_region, {"blocked_regions": blocked_regions, "permitted_regions": permitted_regions}, "page is not disabled in this region")

        topic_values = _list_strings(_field(page_map, "topics", "tags", "categories", default=[]))
        for restriction in version.get("restricted_topics", ()) or ():
            name = _rule_name(restriction)
            if not name:
                continue
            applies = True
            if isinstance(restriction, Mapping):
                markets = _list_strings(restriction.get("markets", restriction.get("regions")))
                platforms = _list_strings(restriction.get("platforms"))
                if markets and market_norm and not _contains_ci(markets, market_norm):
                    applies = False
                if platforms and page_platforms and not any(_contains_ci(platforms, item) for item in page_platforms):
                    applies = False
            if applies and (_contains_ci(topic_values, name) or name.casefold() in {item.casefold() for item in topic_values}):
                matched_restrictions.append(name)
        if matched_restrictions:
            add_fail("REGION_CONTENT_BLOCKED", "restricted_topics", matched_restrictions, (), "page contains a restricted topic")
        else:
            add_pass("RESTRICTED_TOPICS_CLEAR", "restricted_topics", topic_values, (), "page has no matching restricted topic")

        page_disclosures = set(item.casefold() for item in _list_strings(_field(page_map, "disclosures", "disclosure_ids", "disclosure_rules", "required_disclosures", default=[])))
        for rule in version.get("disclosure_rules", ()) or ():
            name = _rule_name(rule)
            if not name:
                continue
            # A string rule is the compact GEO_REGION-001 form and denotes a
            # required disclosure.  Structured rules may explicitly opt out
            # with ``required: false`` while defaulting to required when they
            # carry no optional marker.
            mandatory = (
                isinstance(rule, str)
                or (
                    isinstance(rule, Mapping)
                    and bool(rule.get("required", rule.get("mandatory", rule.get("is_required", True))))
                )
            )
            if mandatory and name.casefold() not in page_disclosures:
                required_disclosures.append(name)
        if required_disclosures:
            add_fail("DISCLOSURE_REQUIRED", "disclosures", sorted(required_disclosures), sorted(page_disclosures), "required disclosure is missing")
        else:
            add_pass("DISCLOSURES_SATISFIED", "disclosures", sorted(page_disclosures), required_disclosures, "required disclosures are present")

        deny_codes = {item["code"] for item in checks if item["status"] == "fail" and item["code"] in {
            "TENANT_SCOPE_VIOLATION", "REGION_VERSION_NOT_FOUND", "REGION_VERSION_INACTIVE", "REGION_VERSION_EXPIRED",
            "LOCALE_NOT_ALLOWED", "MARKET_NOT_ALLOWED", "REGION_CONTENT_BLOCKED", "DISCLOSURE_REQUIRED",
        }}
        decision = "deny" if deny_codes else "eligible"
        status = "blocked" if decision == "deny" else "eligible"
        # A caller may explicitly signal an unresolved predecessor or policy
        # review.  Review never outranks a deterministic denial.
        if not deny_codes and (_field(page_map, "manual_review", default=False) is True or kwargs.get("manual_review") is True):
            decision, status = "manual_review", "review"
            checks.append(_check("MANUAL_REVIEW", "page_snapshot", True, False, "page requires manual policy review"))
            reasons.append(_reason("MANUAL_REVIEW", "page requires manual policy review"))
        reasons = list({(item["code"], item["message"]): item for item in reasons}.values())
        decision_material = {
            "org_id": str(tenant),
            "region_profile_version_id": str(version_uuid),
            "page_version_id": str(page_id) if page_id else None,
            "page_key": page_key,
            "locale": locale,
            "market": market_norm,
            "region": page_region,
            "decision": decision,
            "status": status,
            "input_snapshot_hash": input_snapshot_hash,
            "checks": checks,
            "reasons": reasons,
            "required_disclosures": sorted(required_disclosures),
            "matched_restrictions": sorted(matched_restrictions),
            "policy_snapshot_ref": policy_ref,
            "evaluated_at": _stamp(at),
            "request_hash": request_hash,
            "idempotency_key": key,
            "actor_id": str(actor),
            "trace_id": trace,
        }
        hash_material = dict(decision_material)
        for runtime_field in ("idempotency_key", "actor_id", "trace_id", "request_hash"):
            hash_material.pop(runtime_field, None)
        decision_hash = _hash(hash_material)
        decision_material["decision_hash"] = decision_hash
        decision_material["id"] = str(uuid5(_DECISION_NAMESPACE, f"{tenant}:{version_uuid}:{page_id or page_key}:{request_hash}"))
        decision_material["created_at"] = _stamp(at)
        errors = sorted(_CHECK_VALIDATOR.iter_errors(decision_material), key=lambda item: list(item.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "decision"
            raise RegionPolicyError("REGION_POLICY_INVALID", f"{location}: {errors[0].message}")
        self.store.save_command(tenant, "region:check_page", key, request_hash, decision_material)
        self.store.decisions[UUID(decision_material["id"])] = deepcopy(decision_material)
        self._save_audit(tenant=tenant, actor=actor, trace=trace, key=key, action="region.page.checked", status=decision, input_hash=request_hash, output_hash=decision_hash, reason=reasons[0]["code"] if reasons else None)
        return RegionCheckDecision(decision_material)

    check = check_page
    evaluate_page = check_page

    def filter_hreflang(
        self,
        pages: Sequence[Any] | None = None,
        *,
        candidates: Sequence[Any] | None = None,
        variants: Sequence[Any] | None = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        page_key: Any = None,
        canonical_identity: Any = None,
        default_locale: Any = None,
        x_default_locale: Any = None,
        evaluated_at: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        **kwargs: Any,
    ) -> list[dict[str, str]]:
        values = pages if pages is not None else candidates if candidates is not None else variants
        if values is None:
            values = ()
        if isinstance(values, Mapping) or isinstance(values, (str, bytes)):
            raise RegionPolicyError("REGION_POLICY_INVALID", "pages must be an array")
        tenant, actor, trace = self._tenant(org_id, tenant_context, actor_id, trace_id)
        allowed: list[tuple[str, str, Mapping[str, Any]]] = []
        # Keep one canonical URL per normalized locale. Input order must not
        # decide which duplicate survives; choose the smallest URL and then
        # the stable page id as a deterministic tie breaker.
        by_locale: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
        target_page_key = page_key
        for index, raw in enumerate(values):
            page_map = _mapping(raw, f"pages[{index}]")
            self._guard(page_map, tenant, f"pages[{index}]")
            state = str(_field(page_map, "status", "state", default="")).lower()
            if state not in _READY_PAGE_STATES:
                continue
            candidate_key = _field(page_map, "page_key", "key", "canonical_key", default=None)
            if target_page_key is None and candidate_key is not None:
                target_page_key = candidate_key
            if target_page_key is not None and candidate_key != target_page_key:
                continue
            if canonical_identity is not None and _field(page_map, "canonical_identity", "canonical_key", "page_key", default=None) != canonical_identity:
                continue
            url_raw = _field(page_map, "canonical_url", "url", "href")
            try:
                url = _canonical_url(url_raw)
            except RegionPolicyError:
                continue
            try:
                result = self.check_page(page_map, org_id=tenant, region_profile_version_id=_field(page_map, "region_profile_version_id", "region_version_id"), market=_field(page_map, "market", "region"), evaluated_at=evaluated_at, idempotency_key=f"hreflang:{_hash(_json_safe(page_map))[:40]}", actor_id=actor, trace_id=trace, manual_review=False)
            except RegionError:
                continue
            if result.get("decision") != "eligible":
                continue
            locale = _normalise_locale(_field(page_map, "locale", "language"))
            identity = locale.casefold()
            candidate = (locale, url, page_map)
            prior = by_locale.get(identity)
            candidate_key = (url, str(_field(page_map, "id", "version_id", default="")))
            prior_key = (prior[1], str(_field(prior[2], "id", "version_id", default=""))) if prior else None
            if prior is None or candidate_key < prior_key:
                by_locale[identity] = candidate
        allowed = list(by_locale.values())
        allowed.sort(key=lambda item: (item[0].casefold(), item[1]))
        if not allowed:
            return []
        chosen_default: tuple[str, str, Mapping[str, Any]] | None = None
        requested_default = x_default_locale if x_default_locale is not None else default_locale
        if requested_default is not None:
            normalized_default = _normalise_locale(requested_default)
            chosen_default = next((item for item in allowed if item[0].casefold() == normalized_default.casefold()), None)
        if chosen_default is None:
            chosen_default = allowed[0]
        result = [{"locale": locale, "url": url} for locale, url, _ in allowed]
        if not any(item["locale"] == "x-default" for item in result):
            result.append({"locale": "x-default", "url": chosen_default[1]})
        return result

    def get_decision(
        self,
        decision_id: Any,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> RegionCheckDecision:
        tenant, _actor, _trace = self._tenant(org_id, tenant_context, None, None)
        identity = _uuid(decision_id, "decision_id")
        value = self.store.decisions.get(identity)
        if value is None:
            raise RegionPolicyError("REGION_DECISION_NOT_FOUND", "region decision was not found")
        if str(value.get("org_id")) != str(tenant):
            raise RegionPolicyError("TENANT_SCOPE_VIOLATION", "region decision is outside this organization")
        return RegionCheckDecision(deepcopy(value))

    def list_decisions(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        page_version_id: Any = None,
        region_profile_version_id: Any = None,
    ) -> tuple[RegionCheckDecision, ...]:
        tenant, _actor, _trace = self._tenant(org_id, tenant_context, None, None)
        page_filter = None if page_version_id is None else str(_uuid(page_version_id, "page_version_id"))
        version_filter = None if region_profile_version_id is None else str(_uuid(region_profile_version_id, "region_profile_version_id"))
        values = []
        for item in self.store.decisions.values():
            if str(item.get("org_id")) != str(tenant):
                continue
            if page_filter is not None and item.get("page_version_id") != page_filter:
                continue
            if version_filter is not None and item.get("region_profile_version_id") != version_filter:
                continue
            values.append(item)
        values.sort(key=lambda item: (item.get("evaluated_at", ""), item.get("id", "")))
        return tuple(RegionCheckDecision(deepcopy(item)) for item in values)

    def audit_for(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant, _actor, _trace = self._tenant(org_id, tenant_context, None, None)
        return tuple(deepcopy(item) for item in self.audit if item.get("org_id") == str(tenant))


class RegionDeletionService(_PolicyBase):
    """Build a retention/deletion plan without mutating or deleting facts."""

    def __init__(self, *, propagation_service: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.propagation_service = propagation_service

    def plan(
        self,
        *,
        subject_type: Any = None,
        subject_id: Any = None,
        record: Any = None,
        data_record: Any = None,
        region_profile_version_id: Any = None,
        version_id: Any = None,
        region_version: Any = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        anchor_at: Any = None,
        requested_at: Any = None,
        created_at: Any = None,
        legal_hold: Any = False,
        requested_deletion: Any = True,
        already_deleted: Any = False,
        retention_days: Any = None,
        deletion_sla_hours: Any = None,
        data_residency: Any = None,
        policy_snapshot: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        request_id: Any = None,
        **kwargs: Any,
    ) -> RegionDeletionPlan:
        source_record = record if record is not None else data_record
        if source_record is not None:
            source = _mapping(source_record, "record")
            if subject_type is None:
                subject_type = _field(source, "subject_type", "type", "kind", default=None)
            if subject_id is None:
                subject_id = _field(source, "subject_id", "id", default=None)
            if data_residency is None:
                data_residency = _field(source, "data_residency", "data_region", default=None)
            if anchor_at is None and requested_at is None and created_at is None:
                anchor_at = _field(source, "anchor_at", "requested_at", "created_at", default=None)
            if legal_hold is False and "legal_hold" in source:
                legal_hold = source["legal_hold"]
            if already_deleted is False and "already_deleted" in source:
                already_deleted = source["already_deleted"]
        if subject_type is None or subject_id is None:
            raise RegionPolicyError("REGION_POLICY_INVALID", "subject_type and subject_id are required")
        identity_value = region_profile_version_id if region_profile_version_id is not None else version_id
        if identity_value is None:
            raise RegionPolicyError("REGION_VERSION_NOT_FOUND", "region_profile_version_id is required")
        tenant, actor, trace = self._tenant(org_id, tenant_context, actor_id, trace_id)
        if source_record is not None:
            self._guard(source_record, tenant, "record")
        self._guard(policy_snapshot, tenant, "policy_snapshot")
        version = self._version(tenant, identity_value, region_version)
        version_uuid = _version_id(version)
        subject = _uuid(subject_id, "subject_id")
        kind = _text(subject_type, "subject_type", maximum=128)
        key = _text(idempotency_key, "idempotency_key", maximum=200) if idempotency_key is not None else f"delete:{version_uuid}:{kind}:{subject}"
        anchor = _parse_time(anchor_at if anchor_at is not None else requested_at if requested_at is not None else created_at, "anchor_at", default=self.clock())
        if type(legal_hold) is not bool:
            raise RegionPolicyError("REGION_POLICY_INVALID", "legal_hold must be a boolean")
        if type(requested_deletion) is not bool:
            raise RegionPolicyError("REGION_POLICY_INVALID", "requested_deletion must be a boolean")
        if type(already_deleted) is not bool:
            raise RegionPolicyError("REGION_POLICY_INVALID", "already_deleted must be a boolean")
        configured_retention = version.get("retention_days")
        configured_sla = version.get("deletion_sla_hours")
        configured_residency = version.get("data_residency")
        # Retention and deletion timing are facts of the immutable region
        # version.  Command parameters may repeat those facts for adapters,
        # but cannot fill a missing policy or override a published value.
        retention_missing = configured_retention is None
        sla_missing = configured_sla is None
        try:
            # Keep the projection schema-valid when a legacy snapshot lacks a
            # policy.  The zero placeholders are never treated as permission
            # to delete: status becomes manual_review below.
            retention = 0 if retention_missing else int(configured_retention)
            sla = 0 if sla_missing else int(configured_sla)
            if retention_days is not None and not retention_missing and int(retention_days) != retention:
                raise RegionPolicyError("REGION_POLICY_INVALID", "retention_days cannot override the immutable region version")
            if deletion_sla_hours is not None and not sla_missing and int(deletion_sla_hours) != sla:
                raise RegionPolicyError("REGION_POLICY_INVALID", "deletion_sla_hours cannot override the immutable region version")
        except RegionPolicyError:
            raise
        except (TypeError, ValueError) as exc:
            raise RegionPolicyError("REGION_POLICY_INVALID", "retention_days and deletion_sla_hours must be integers") from exc
        if retention < 0 or retention > 36500:
            raise RegionPolicyError("REGION_POLICY_INVALID", "retention_days is outside the supported range")
        if sla < 0 or sla > 87600:
            raise RegionPolicyError("REGION_POLICY_INVALID", "deletion_sla_hours is outside the supported range")
        residency = _text(configured_residency, "data_residency", maximum=128) if configured_residency is not None else None
        if data_residency is not None:
            supplied_residency = _text(data_residency, "data_residency", maximum=128)
            if residency is not None and supplied_residency.casefold() != residency.casefold():
                raise RegionPolicyError("REGION_CONTENT_BLOCKED", "data residency cannot override the immutable region version")
        if source_record is not None:
            record_residency = _field(_mapping(source_record, "record"), "data_residency", "data_region", default=None)
            if record_residency is not None and residency is not None and str(record_residency).casefold() != residency.casefold():
                raise RegionPolicyError("REGION_CONTENT_BLOCKED", "record data residency does not match region policy")
        if already_deleted or not requested_deletion:
            status = "completed"
        elif residency is None or retention_missing or sla_missing or legal_hold:
            status = "manual_review"
        else:
            status = "planned"
        retention_expires = anchor + timedelta(days=retention)
        due_at = retention_expires + timedelta(hours=sla)
        policy_ref_raw = version.get("policy_snapshot_ref", version.get("policy_snapshot_id"))
        policy_ref = None if policy_ref_raw is None else str(policy_ref_raw)
        request_material = {
            "org_id": str(tenant),
            "version_id": str(version_uuid),
            "subject_type": kind,
            "subject_id": str(subject),
            # The evaluated anchor is part of the command payload.  Reusing a
            # key with a different retention clock must be rejected instead
            # of silently changing the due date.
            "anchor_at": _stamp(anchor),
            "retention_days": retention,
            "deletion_sla_hours": sla,
            "data_residency": residency,
            "legal_hold": bool(legal_hold),
            "requested_deletion": bool(requested_deletion),
            "already_deleted": bool(already_deleted),
            "policy_snapshot": _json_safe(policy_snapshot),
        }
        request_hash = _hash(request_material)
        prior = self.store.get_command(tenant, "region:deletion_plan", key)
        if prior is not None:
            if prior["request_hash"] != request_hash:
                raise RegionPolicyError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return RegionDeletionPlan(prior["response"])
        plan_material: dict[str, Any] = {
            "org_id": str(tenant),
            "region_profile_version_id": str(version_uuid),
            "subject_type": kind,
            "subject_id": str(subject),
            "data_residency": residency or "unknown",
            "retention_days": retention,
            "deletion_sla_hours": sla,
            "anchor_at": _stamp(anchor),
            "retention_expires_at": _stamp(retention_expires),
            "due_at": _stamp(due_at),
            "legal_hold": bool(legal_hold),
            "status": status,
            "targets": list(_TARGETS),
            "policy_snapshot_ref": policy_ref,
            "input_snapshot_hash": _version_snapshot_hash(version),
            "request_hash": request_hash,
            "request_id": None,
            "idempotency_key": key,
            "evaluated_at": _stamp(anchor),
            "actor_id": str(actor),
            "trace_id": trace,
        }
        # Newer contract revisions expose the action independently from the
        # queue status.  Emit it when the schema advertises that field while
        # remaining compatible with the original closed schema.
        plan_material["deletion_action"] = (
            "already_deleted" if already_deleted else
            "retain" if not requested_deletion else
            "manual_review" if status == "manual_review" else
            "delete"
        )
        if request_id is not None:
            if status != "planned":
                raise RegionPolicyError("REGION_POLICY_INVALID", "only an eligible deletion plan may reference a queue request")
            plan_material["request_id"] = str(_uuid(request_id, "request_id"))
            plan_material["status"] = "queued"
        if self.propagation_service is not None and status == "planned" and plan_material["request_id"] is None:
            requester = getattr(self.propagation_service, "request", None)
            if requester is not None:
                try:
                    request = requester(org_id=tenant, subject_type=kind, subject_id=subject, requested_by=actor, idempotency_key=f"{key}:propagation", trace_id=trace, requested_at=anchor)
                    plan_material["request_id"] = str(_uuid(getattr(request, "id", _value(request, "id")), "request_id"))
                    plan_material["status"] = "queued"
                except Exception as exc:
                    # A planning call must remain deterministic.  A failed
                    # downstream queue handoff is represented as review and
                    # never causes a deletion side effect.
                    plan_material["status"] = "manual_review"
                    self._save_audit(tenant=tenant, actor=actor, trace=trace, key=key, action="region.deletion.queue_failed", status="manual_review", input_hash=request_hash, reason=_redact_error(exc))
        # Legal holds and missing policy stay in the human-review queue; no
        # automatic propagation request is created for those states.  A
        # request id is present only after a real queue handoff (or when the
        # caller supplied one explicitly).
        if plan_material["status"] == "queued" and plan_material["request_id"] is None:
            raise RegionPolicyError("REGION_POLICY_INVALID", "queued deletion plan requires request_id")
        plan_material["deletion_action"] = (
            "already_deleted" if already_deleted else
            "retain" if not requested_deletion else
            "manual_review" if plan_material["status"] == "manual_review" else
            "delete"
        )
        plan_hash_material = dict(plan_material)
        for runtime_field in ("idempotency_key", "actor_id", "trace_id", "request_hash", "request_id"):
            plan_hash_material.pop(runtime_field, None)
        plan_material["plan_hash"] = _hash(plan_hash_material)
        plan_material["id"] = str(uuid5(_DELETE_NAMESPACE, f"plan:{tenant}:{version_uuid}:{kind}:{subject}:{request_hash}"))
        errors = sorted(_DELETE_VALIDATOR.iter_errors(plan_material), key=lambda item: list(item.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "deletion_plan"
            raise RegionPolicyError("REGION_POLICY_INVALID", f"{location}: {errors[0].message}")
        self.store.save_command(tenant, "region:deletion_plan", key, request_hash, plan_material)
        self.store.deletion_plans[UUID(plan_material["id"])] = deepcopy(plan_material)
        self._save_audit(tenant=tenant, actor=actor, trace=trace, key=key, action="region.deletion.planned", status=plan_material["status"], input_hash=request_hash, output_hash=plan_material["plan_hash"])
        return RegionDeletionPlan(plan_material)

    plan_deletion = plan

    def propagate(
        self,
        plan: RegionDeletionPlan | Mapping[str, Any] | Any,
        *,
        targets: Mapping[str, Any],
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        idempotency_key: Any = None,
        trace_id: Any = None,
    ) -> Any:
        """Delegate a queued plan to the existing five-stage state machine.

        This method is an explicit side-effect boundary.  Planning itself is
        offline; callers must opt into propagation and provide all five
        independently verifiable target adapters.
        """
        if self.propagation_service is None or not hasattr(self.propagation_service, "propagate"):
            raise RegionPolicyError("DELETION_PROPAGATION_UNAVAILABLE", "a DeletionPropagationService is required")
        value = plan.as_contract() if hasattr(plan, "as_contract") else dict(plan)
        tenant, _actor, trace = self._tenant(org_id, tenant_context, None, trace_id)
        if str(value.get("org_id")) != str(tenant):
            raise RegionPolicyError("TENANT_SCOPE_VIOLATION", "deletion plan is outside this organization")
        request_value = value.get("request_id")
        if request_value is None:
            raise RegionPolicyError("DELETION_NOT_QUEUED", "deletion plan has no propagation request")
        key = _text(idempotency_key, "idempotency_key", maximum=200) if idempotency_key is not None else f"{value.get('id')}:propagate"
        return self.propagation_service.propagate(
            org_id=tenant,
            request_id=_uuid(request_value, "request_id"),
            targets=targets,
            idempotency_key=key,
            trace_id=trace,
        )

    execute = propagate

    def get_plan(self, plan_id: Any, *, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None) -> RegionDeletionPlan:
        tenant, _, _ = self._tenant(org_id, tenant_context, None, None)
        identity = _uuid(plan_id, "plan_id")
        value = self.store.deletion_plans.get(identity)
        if value is None:
            raise RegionPolicyError("REGION_DELETION_NOT_FOUND", "deletion plan was not found")
        if UUID(value["org_id"]) != tenant:
            raise RegionPolicyError("TENANT_SCOPE_VIOLATION", "deletion plan is outside this organization")
        return RegionDeletionPlan(deepcopy(value))

    def list_plans(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        subject_id: Any = None,
        region_profile_version_id: Any = None,
    ) -> tuple[RegionDeletionPlan, ...]:
        tenant, _actor, _trace = self._tenant(org_id, tenant_context, None, None)
        subject_filter = None if subject_id is None else str(_uuid(subject_id, "subject_id"))
        version_filter = None if region_profile_version_id is None else str(_uuid(region_profile_version_id, "region_profile_version_id"))
        values = []
        for item in self.store.deletion_plans.values():
            if str(item.get("org_id")) != str(tenant):
                continue
            if subject_filter is not None and item.get("subject_id") != subject_filter:
                continue
            if version_filter is not None and item.get("region_profile_version_id") != version_filter:
                continue
            values.append(item)
        values.sort(key=lambda item: (item.get("evaluated_at", ""), item.get("id", "")))
        return tuple(RegionDeletionPlan(deepcopy(item)) for item in values)

    def audit_for(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant, _actor, _trace = self._tenant(org_id, tenant_context, None, None)
        return tuple(deepcopy(item) for item in self.audit if item.get("org_id") == str(tenant))


# Compatibility aliases used by early GEO_REGION-002 callers.
GeoRegionEligibilityService = RegionEligibilityService
GeoRegionDeletionService = RegionDeletionService


__all__ = [
    "RegionPolicyError",
    "GeoRegionPolicyError",
    "RegionCheckDecision",
    "RegionDeletionPlan",
    "InMemoryRegionPolicyStore",
    "RegionEligibilityService",
    "GeoRegionEligibilityService",
    "RegionDeletionService",
    "GeoRegionDeletionService",
]
