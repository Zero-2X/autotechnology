"""Account-free GEO_CONTENT/GEO_REGION quality aggregation for ANALYTICS-004.

The service consumes already validated Observation contracts.  It deliberately
keeps content quality and regional compliance in separate projections so a
missing locale or a regional restriction cannot be hidden by a content score.
"""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from .catalog import AnalyticsError, _context, _hash, _stamp, _text, _time, _uuid
from .observation import _locale, _region


_ROOT = Path(__file__).resolve().parents[2]
_OBSERVATION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/observation.schema.json").read_text(encoding="utf-8")
)
_SNAPSHOT_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/analytics-geo-quality-snapshot.schema.json").read_text(encoding="utf-8")
)
_OBSERVATION_VALIDATOR = Draft202012Validator(_OBSERVATION_SCHEMA, format_checker=FormatChecker())
_SNAPSHOT_VALIDATOR = Draft202012Validator(_SNAPSHOT_SCHEMA, format_checker=FormatChecker())
_NAMESPACE = UUID("a0de3f65-10d4-5a87-9a80-7e77985f65df")
_EVENT_NAMESPACE = UUID("dbd8bce0-2e66-5cf0-9b64-67ea55feef61")
_RULE_VERSION = "analytics-004.v1"

# Metric names are intentionally aliases: Observation metric definitions may
# use either dotted names or the historical underscore spelling.
_CONTENT_ALIASES = {
    "geo.content.mentioned": "mentioned",
    "geo.content.mention": "mentioned",
    "geo.content.cited": "cited",
    "geo.content.citation": "cited",
    "geo.content.correct": "correct",
    "geo.content.correctness": "correct",
    "geo_content.mentioned": "mentioned",
    "geo_content.cited": "cited",
    "geo_content.correct": "correct",
}
_REGION_ALIASES = {
    "geo.region.allowed": "allowed",
    "geo.region.compliant": "compliant",
    "geo.region.restricted": "restricted",
    "geo.region.hreflang_valid": "hreflang_valid",
    "geo_region.allowed": "allowed",
    "geo_region.compliant": "compliant",
    "geo_region.restricted": "restricted",
    "geo_region.hreflang_valid": "hreflang_valid",
}


class GeoQualityError(AnalyticsError):
    """Stable failure for GEO quality aggregation."""


def _bool(value: Any, *, metric: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "pass", "passed", "correct", "allowed", "compliant", "valid"}:
            return True
        if normalized in {"false", "no", "fail", "failed", "incorrect", "restricted", "invalid"}:
            return False
    raise GeoQualityError("GEO_QUALITY_VALUE_INVALID", f"{metric} has an unsupported value")


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else round(numerator / denominator, 6),
    }


class InMemoryGeoQualityStore:
    """Thread-safe append-only snapshot, command, audit and outbox adapter."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []

    def get(self, identity: str) -> dict[str, Any] | None:
        value = self.snapshots.get(identity)
        return deepcopy(value) if value is not None else None

    def command(self, org_id: str, key: str) -> dict[str, Any] | None:
        value = self.commands.get((org_id, key))
        return deepcopy(value) if value is not None else None

    def save(self, snapshot: Mapping[str, Any], *, org_id: str, key: str, request_hash: str) -> None:
        identity = str(snapshot["id"])
        prior = self.snapshots.get(identity)
        if prior is not None and prior != snapshot:
            raise GeoQualityError("GEO_QUALITY_SNAPSHOT_CONFLICT", "snapshot id has another payload")
        self.snapshots[identity] = deepcopy(dict(snapshot))
        self.commands[(org_id, key)] = {"request_hash": request_hash, "response": deepcopy(dict(snapshot))}


GeoQualityStore = InMemoryGeoQualityStore


class GeoQualityService:
    """Build separate content and region quality projections from observations."""

    rule_version = _RULE_VERSION

    def __init__(self, store: InMemoryGeoQualityStore | None = None, *, clock: Any | None = None) -> None:
        self.store = store or InMemoryGeoQualityStore()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self, value: Any = None) -> datetime:
        return _time(value, "calculated_at", required=True) if value is not None else _time(self._clock(), "clock", required=True)  # type: ignore[return-value]

    def _latest(self, observations: Sequence[Mapping[str, Any]], tenant: UUID) -> tuple[dict[str, Any], ...]:
        by_id: dict[str, dict[str, Any]] = {}
        by_key: dict[str, dict[str, Any]] = {}
        versions: dict[tuple[str, int], str] = {}
        for raw in observations:
            if not isinstance(raw, Mapping):
                raise GeoQualityError("GEO_QUALITY_INPUT_INVALID", "observations must contain objects")
            item = deepcopy(dict(raw))
            try:
                json.dumps(item, allow_nan=False)
                _OBSERVATION_VALIDATOR.validate(item)
            except (ValidationError, ValueError, TypeError):
                raise GeoQualityError("GEO_QUALITY_INPUT_INVALID", "observation violates its schema") from None
            if item["org_id"] != str(tenant):
                raise GeoQualityError("TENANT_SCOPE_VIOLATION", "observation belongs to another organization")
            digest = _hash(item)
            if item["id"] in by_id:
                if _hash(by_id[item["id"]]) != digest:
                    raise GeoQualityError("GEO_QUALITY_INPUT_CONFLICT", "observation id has conflicting snapshots")
                continue
            by_id[item["id"]] = item
            vk = (item["dedupe_key"], item["observation_version"])
            if vk in versions and versions[vk] != digest:
                raise GeoQualityError("GEO_QUALITY_INPUT_CONFLICT", "dedupe key/version has conflicting snapshots")
            versions[vk] = digest
            prior = by_key.get(item["dedupe_key"])
            if prior is not None and any(prior[field] != item[field] for field in (
                "source", "subject_type", "subject_id", "metric_definition_id", "metric_name", "metric_type"
            )):
                raise GeoQualityError("GEO_QUALITY_INPUT_CONFLICT", "observation revision changed its identity")
            if prior is None or item["observation_version"] > prior["observation_version"]:
                by_key[item["dedupe_key"]] = item
        return tuple(by_key[key] for key in sorted(by_key))

    def calculate_snapshot(
        self,
        observations: Sequence[Mapping[str, Any]],
        *,
        window_start: Any,
        window_end: Any,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any,
        region: Any = None,
        locale: Any = None,
        external_account_available: bool = False,
        account_evidence: Mapping[str, Any] | None = None,
        calculated_at: Any = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id,
                                           actor_id=actor_id, trace_id=trace_id)
        if isinstance(observations, (str, bytes, Mapping)) or not isinstance(observations, Sequence):
            raise GeoQualityError("GEO_QUALITY_INPUT_INVALID", "observations must be an array")
        start, end = _time(window_start, "window_start", required=True), _time(window_end, "window_end", required=True)
        if start >= end:  # type: ignore[operator]
            raise GeoQualityError("GEO_QUALITY_WINDOW_INVALID", "window_start must be before window_end")
        region_filter, locale_filter = _region(region), _locale(locale)
        key = _text(idempotency_key, "idempotency_key", maximum=200)
        at = self._now(calculated_at)
        latest = self._latest(observations, tenant)
        selected: list[dict[str, Any]] = []
        issues: dict[tuple[str, str], int] = {}

        def issue(code: str, scope: str, count: int = 1) -> None:
            issues[(code, scope)] = issues.get((code, scope), 0) + count

        for item in latest:
            observed = _time(item["observed_at"], "observed_at", required=True)
            if not (start <= observed < end):  # type: ignore[operator]
                continue
            if region_filter is not None and item["region"] != region_filter:
                continue
            if locale_filter is not None and item["locale"] != locale_filter:
                continue
            name = item["metric_name"].lower()
            scope = "content" if name in _CONTENT_ALIASES else "region" if name in _REGION_ALIASES else None
            if scope is None:
                issue("UNSUPPORTED_GEO_METRIC", "all")
                continue
            if item["locale"] is None:
                issue("MISSING_LOCALE", scope)
            if item["region"] is None:
                issue("MISSING_REGION", scope)
            if item["data_quality"] == "raw":
                issue("RAW_INPUT_PRESENT", scope)
            elif item["data_quality"] == "estimated":
                issue("ESTIMATED_INPUT_PRESENT", scope)
            selected.append(item)
        if not selected:
            raise GeoQualityError("GEO_QUALITY_NO_SUPPORTED_INPUT", "no supported GEO observations fall in the window")
        if any(item["source"] == "platform" for item in selected):
            verified = external_account_available
            if account_evidence is not None:
                if not isinstance(account_evidence, Mapping):
                    raise GeoQualityError("EXT_ACCOUNT_EVIDENCE_INVALID", "account evidence must be an object")
                marker = account_evidence.get("org_id")
                if marker is not None and _uuid(marker, "account_evidence.org_id") != tenant:
                    raise GeoQualityError("TENANT_SCOPE_VIOLATION", "account evidence belongs to another organization")
                if {str(k).lower() for k in account_evidence} & {"token", "secret", "password", "cookie", "authorization"}:
                    raise GeoQualityError("SENSITIVE_ANALYTICS_INPUT", "account evidence contains a forbidden field")
                verified = verified or str(account_evidence.get("status", "")).lower() in {"active", "ready", "verified"}
            if not verified:
                raise GeoQualityError("EXT_ACCOUNT_UNAVAILABLE", "platform GEO observations require account evidence")
        buckets: dict[str, dict[str, list[int]]] = {
            "content": {}, "region": {},
        }
        for item in selected:
            scope = "content" if item["metric_name"].lower() in _CONTENT_ALIASES else "region"
            metric = (_CONTENT_ALIASES if scope == "content" else _REGION_ALIASES)[item["metric_name"].lower()]
            bucket = buckets[scope].setdefault(metric, [0, 0])
            try:
                truth = _bool(item["metric_value"], metric=item["metric_name"])
            except GeoQualityError:
                issue("UNKNOWN_VALUE_EXCLUDED", scope)
                continue
            bucket[1] += 1
            bucket[0] += int(truth)
        def projection(scope: str) -> dict[str, Any]:
            values = buckets[scope]
            return {
                "sample_count": sum(value[1] for value in values.values()),
                "metric_counts": {key: _ratio(pair[0], pair[1]) for key, pair in sorted(values.items())},
            }
        quality = [{"code": code, "scope": scope, "count": count} for (code, scope), count in sorted(issues.items())]
        content, region_result = projection("content"), projection("region")
        status = "needs_review" if any(item["code"] in {"UNKNOWN_VALUE_EXCLUDED", "RAW_INPUT_PRESENT", "ESTIMATED_INPUT_PRESENT"} for item in quality) else "complete"
        included = sorted(selected, key=lambda item: item["id"])
        input_ids = [item["id"] for item in included]
        input_hash = _hash([{"id": item["id"], "hash": _hash(item)} for item in included])
        request = {"window_start": _stamp(start), "window_end": _stamp(end), "region": region_filter, "locale": locale_filter,
                   "input_snapshot_hash": input_hash, "quality_issues": quality, "rule_version": _RULE_VERSION}
        digest = _hash(request)
        with getattr(self.store, "lock", nullcontext()):
            prior = self.store.command(str(tenant), key)
            if prior is not None:
                if prior["request_hash"] != digest:
                    raise GeoQualityError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with another payload")
                return deepcopy(prior["response"])
            identity = str(uuid5(_NAMESPACE, f"{tenant}:{digest}"))
            existing = self.store.get(identity)
            if existing is not None:
                return existing
            base = {"id": identity, "org_id": str(tenant), "window_start": request["window_start"], "window_end": request["window_end"],
                    "region": region_filter, "locale": locale_filter, "source_scope": "all_verified" if any(i["source"] == "platform" for i in selected) else "account_free",
                    "input_observation_ids": input_ids, "input_snapshot_hash": input_hash, "content": content, "region_quality": region_result,
                    "status": status, "quality_issues": quality, "rule_version": _RULE_VERSION, "created_by": str(actor), "created_at": _stamp(at)}
            result = {**base, "snapshot_hash": _hash(base)}
            try:
                _SNAPSHOT_VALIDATOR.validate(result)
            except ValidationError as exc:
                raise GeoQualityError("GEO_QUALITY_SNAPSHOT_INVALID", "computed snapshot violates its schema") from exc
            self.store.save(result, org_id=str(tenant), key=key, request_hash=digest)
            payload = {"aggregate_id": identity, "aggregate_version": 1, "status": status, "snapshot_hash": result["snapshot_hash"],
                       "input_snapshot_hash": input_hash, "window_start": result["window_start"], "window_end": result["window_end"]}
            self.store.outbox.append({"event_id": str(uuid5(_EVENT_NAMESPACE, identity)), "event_type": "analytics.geo_quality_snapshot.created",
                                      "event_schema_version": 1, "occurred_at": _stamp(at), "org_id": str(tenant), "trace_id": trace,
                                      "correlation_id": None, "causation_id": None, "aggregate_type": "AnalyticsGeoQualitySnapshot",
                                      "aggregate_id": identity, "aggregate_version": 1, "actor_type": "user", "actor_id": str(actor),
                                      "idempotency_key": key, "payload": payload, "payload_hash": _hash(payload)})
            self.store.audit.append({"event_type": "analytics.geo_quality_snapshot.created", "org_id": str(tenant), "actor_id": str(actor),
                                     "trace_id": trace, "snapshot_id": identity, "status": status, "source_scope": base["source_scope"],
                                     "input_count": len(input_ids), "input_snapshot_hash": input_hash, "snapshot_hash": result["snapshot_hash"],
                                     "occurred_at": _stamp(at)})
            return deepcopy(result)

    calculate = calculate_snapshot
    aggregate = calculate_snapshot
    compute = calculate_snapshot

    def get_snapshot(self, snapshot_id: Any, *, tenant_context: Mapping[str, Any] | None = None,
                     context: Mapping[str, Any] | None = None, org_id: Any = None) -> dict[str, Any]:
        tenant, _, _, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id)
        identity = str(_uuid(snapshot_id, "snapshot_id"))
        with getattr(self.store, "lock", nullcontext()):
            value = self.store.get(identity)
            if value is None:
                raise GeoQualityError("GEO_QUALITY_SNAPSHOT_NOT_FOUND", "GEO quality snapshot does not exist")
            if value["org_id"] != str(tenant):
                raise GeoQualityError("TENANT_SCOPE_VIOLATION", "snapshot belongs to another organization")
            return value


AnalyticsGeoQualityService = GeoQualityService
GeoQualityAggregationService = GeoQualityService

__all__ = ["GeoQualityError", "InMemoryGeoQualityStore", "GeoQualityStore", "GeoQualityService", "AnalyticsGeoQualityService", "GeoQualityAggregationService"]
