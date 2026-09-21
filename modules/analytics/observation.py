"""Tenant-scoped, append-only Observation ingestion for ANALYTICS-002."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .catalog import (
    AnalyticsError,
    CanonicalEventCatalog,
    _canonical,
    _context,
    _hash,
    _stamp,
    _text,
    _time,
    _uuid,
)


_ROOT = Path(__file__).resolve().parents[2]
_OBSERVATION_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/observation.schema.json").read_text(encoding="utf-8")
)
_METRIC_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/metric-definition.schema.json").read_text(encoding="utf-8")
)
_OBSERVATION_VALIDATOR = Draft202012Validator(_OBSERVATION_SCHEMA, format_checker=FormatChecker())
_METRIC_VALIDATOR = Draft202012Validator(_METRIC_SCHEMA, format_checker=FormatChecker())
_OBSERVATION_NAMESPACE = UUID("016c7ea2-5af0-51d3-a14b-20a8e317c8b6")
_OBSERVATION_EVENT_NAMESPACE = UUID("ae5d94a8-f7a4-5860-a259-fe778c53b544")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_REGION_RE = re.compile(r"^[A-Z]{2,8}(?:-[A-Z0-9]{2,8})*$")
_SENSITIVE_KEYS = frozenset({
    "authorization", "cookie", "password", "raw_content", "raw_output",
    "secret", "token", "access_token", "refresh_token",
})
_SNAPSHOT_REQUIRED_SOURCES = frozenset({"site", "platform", "geo", "support", "qa"})


ObservationError = AnalyticsError
ObservationServiceError = AnalyticsError


def _locale(value: Any) -> str | None:
    if value is None:
        return None
    raw = _text(value, "locale", maximum=64)
    if _LOCALE_RE.fullmatch(raw) is None:
        raise AnalyticsError("OBSERVATION_INVALID", "locale must use a supported BCP-47 form")
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


def _region(value: Any) -> str | None:
    if value is None:
        return None
    result = _text(value, "region", maximum=32).upper()
    if _REGION_RE.fullmatch(result) is None:
        raise AnalyticsError("OBSERVATION_INVALID", "region must be a market or region code")
    return result


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise AnalyticsError("OBSERVATION_INVALID", f"{field} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError("OBSERVATION_INVALID", f"{field} must be a positive integer") from exc
    if result < 1 or str(value).strip() != str(result):
        raise AnalyticsError("OBSERVATION_INVALID", f"{field} must be a positive integer")
    return result


def _expected(expected_version: Any, if_match: Any) -> int:
    def parse(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "version must be a positive integer")
        raw = str(value).strip()
        if raw.startswith("W/"):
            raw = raw[2:].strip()
        raw = raw.strip('"')
        if not raw.isdecimal() or int(raw) < 1:
            raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "version must be a positive integer")
        return int(raw)

    expected, matched = parse(expected_version), parse(if_match)
    if expected is None and matched is None:
        raise AnalyticsError("VERSION_PRECONDITION_REQUIRED", "expected_version or If-Match is required")
    if expected is not None and matched is not None and expected != matched:
        raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "expected_version and If-Match disagree")
    return expected if expected is not None else matched  # type: ignore[return-value]


def _assert_safe_value(value: Any, *, path: str = "metric_value", depth: int = 0) -> None:
    if depth > 20:
        raise AnalyticsError("OBSERVATION_INVALID", "metric_value nesting is too deep")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AnalyticsError("OBSERVATION_INVALID", "metric_value object keys must be strings")
            if key.strip().lower() in _SENSITIVE_KEYS:
                raise AnalyticsError("SENSITIVE_OBSERVATION_REJECTED", "metric_value contains a forbidden sensitive field")
            _assert_safe_value(item, path=f"{path}.{key}", depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _assert_safe_value(item, path=f"{path}[{index}]", depth=depth + 1)
    elif isinstance(value, (bytes, bytearray)):
        raise AnalyticsError("OBSERVATION_INVALID", "metric_value must be JSON")


def _validate_value(observation: Mapping[str, Any], definition: Mapping[str, Any]) -> None:
    try:
        json.dumps([observation, definition], ensure_ascii=False, allow_nan=False)
        _OBSERVATION_VALIDATOR.validate(observation)
        _METRIC_VALIDATOR.validate(definition)
    except (TypeError, ValueError, ValidationError) as exc:
        raise AnalyticsError("OBSERVATION_INVALID", "observation or metric definition violates its schema") from exc
    if definition["status"] != "active":
        raise AnalyticsError("METRIC_DEFINITION_NOT_ACTIVE", "metric definition must be active")
    if (
        observation["metric_definition_id"] != definition["id"]
        or observation["metric_definition_version_no"] != definition["version_no"]
        or observation["metric_name"] != definition["key"]
        or observation["metric_type"] != definition["metric_type"]
    ):
        raise AnalyticsError("METRIC_DEFINITION_BINDING_MISMATCH", "observation does not match its metric definition")
    value_schema = definition["quality_rules"].get("value_schema")
    if value_schema is None:
        return
    try:
        Draft202012Validator.check_schema(value_schema)
        dialect = value_schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
        if dialect != "https://json-schema.org/draft/2020-12/schema":
            raise ValueError("unsupported value schema dialect")
        if definition["metric_type"] == "enum":
            members = value_schema.get("enum")
            if not isinstance(members, list) or not members or not all(isinstance(item, str) for item in members):
                raise ValueError("enum values must be explicit strings")
        Draft202012Validator(
            value_schema,
            format_checker=FormatChecker(),
            registry=Registry(),
        ).validate(observation["metric_value"])
    except (SchemaError, ValidationError, Unresolvable, TypeError, ValueError, RecursionError) as exc:
        raise AnalyticsError("METRIC_VALUE_REJECTED", "metric value failed its definition quality rules") from exc


class InMemoryObservationStore:
    """Append-only deterministic observation and idempotency adapter."""

    def __init__(self) -> None:
        self.lock = RLock()
        self._observations: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._by_dedupe: dict[tuple[str, str], list[str]] = {}
        self._commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []

    def versions(self, org_id: str, dedupe_key: str) -> tuple[dict[str, Any], ...]:
        ids = self._by_dedupe.get((org_id, dedupe_key), [])
        return tuple(deepcopy(self._observations[identity]) for identity in ids)

    def metadata(self, identity: str) -> dict[str, Any] | None:
        value = self._metadata.get(identity)
        return deepcopy(value) if value is not None else None

    def save(self, observation: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
        identity = str(observation["id"])
        if identity in self._observations:
            raise AnalyticsError("OBSERVATION_ID_CONFLICT", "observation id already exists")
        key = (str(observation["org_id"]), str(observation["dedupe_key"]))
        self._observations[identity] = deepcopy(dict(observation))
        self._metadata[identity] = deepcopy(dict(metadata))
        self._by_dedupe.setdefault(key, []).append(identity)
        self._by_dedupe[key].sort(key=lambda item: self._observations[item]["observation_version"])

    def get(self, identity: str) -> dict[str, Any] | None:
        value = self._observations.get(identity)
        return deepcopy(value) if value is not None else None

    def command(self, org_id: str, namespace: str, key: str) -> dict[str, Any] | None:
        value = self._commands.get((org_id, namespace, key))
        return deepcopy(value) if value is not None else None

    def save_command(
        self,
        org_id: str,
        namespace: str,
        key: str,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> None:
        self._commands[(org_id, namespace, key)] = {
            "request_hash": request_hash,
            "response": deepcopy(dict(response)),
        }


ObservationStore = InMemoryObservationStore
AnalyticsObservationStore = InMemoryObservationStore


class ObservationService:
    """Validate and append observations without external network access."""

    def __init__(
        self,
        store: InMemoryObservationStore | None = None,
        *,
        metric_definitions: Any | None = None,
        event_catalog: CanonicalEventCatalog | None = None,
        clock: Any | None = None,
    ) -> None:
        self.store = store or InMemoryObservationStore()
        self.metric_definitions = metric_definitions
        self.event_catalog = event_catalog or CanonicalEventCatalog()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self, value: Any = None) -> datetime:
        return _time(value, "recorded_at", required=True) if value is not None else _time(self._clock(), "clock", required=True)  # type: ignore[return-value]

    def _replay(self, org_id: str, namespace: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self.store.command(org_id, namespace, key)
        if prior is None:
            return None
        if prior["request_hash"] != digest:
            raise AnalyticsError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with another payload")
        return deepcopy(prior["response"])

    def _definition(
        self,
        supplied: Mapping[str, Any] | None,
        *,
        values: Mapping[str, Any],
        tenant: UUID,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if supplied is not None:
            if not isinstance(supplied, Mapping):
                raise AnalyticsError("METRIC_DEFINITION_INVALID", "metric_definition must be an object")
            definition = deepcopy(dict(supplied))
        elif self.metric_definitions is not None:
            identity = values.get("metric_definition_id")
            if identity is None:
                raise AnalyticsError("METRIC_DEFINITION_INVALID", "metric_definition_id is required")
            getter = getattr(self.metric_definitions, "get_metric_definition", None) or getattr(self.metric_definitions, "get", None)
            if not callable(getter):
                raise AnalyticsError("METRIC_DEFINITION_INVALID", "metric definition resolver has no get operation")
            resolver_context = {**dict(context or {}), "org_id": str(tenant)}
            definition = getter(identity, context=resolver_context)
        else:
            raise AnalyticsError("METRIC_DEFINITION_REQUIRED", "an active metric definition is required")
        try:
            _METRIC_VALIDATOR.validate(definition)
        except ValidationError as exc:
            raise AnalyticsError("METRIC_DEFINITION_INVALID", "metric definition violates its schema") from exc
        if definition["org_id"] not in {None, str(tenant)}:
            raise AnalyticsError("TENANT_SCOPE_VIOLATION", "metric definition belongs to another organization")
        return definition

    def _category(self, explicit: Any, definition: Mapping[str, Any], source: str, subject_type: str) -> str:
        if explicit is not None:
            category = _text(explicit, "category", maximum=32).lower()
            self.event_catalog.definition_for(category)
            return category
        data_source = str(definition.get("data_source", ""))
        if data_source.startswith("analytics.") and data_source.endswith(".observed"):
            category = data_source.split(".", 2)[1]
            self.event_catalog.definition_for(category)
            return category
        if source in {"qa", "geo", "support"}:
            return source
        if subject_type == "asset":
            return "asset"
        if subject_type == "publication":
            return "publication"
        return "content"

    def _account_hash(
        self,
        *,
        tenant: UUID,
        source: str,
        external_account_available: bool,
        account_evidence: Mapping[str, Any] | None,
    ) -> str | None:
        if source != "platform":
            return None
        verified = external_account_available
        if account_evidence is not None:
            if not isinstance(account_evidence, Mapping):
                raise AnalyticsError("EXT_ACCOUNT_EVIDENCE_INVALID", "account evidence must be an object")
            lowered = {str(key).strip().lower() for key in account_evidence}
            if lowered & _SENSITIVE_KEYS:
                raise AnalyticsError("SENSITIVE_OBSERVATION_REJECTED", "account evidence contains a forbidden sensitive field")
            marker = account_evidence.get("org_id")
            if marker is not None and _uuid(marker, "account_evidence.org_id") != tenant:
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "account evidence belongs to another organization")
            verified = verified or str(account_evidence.get("status", "")).lower() in {"active", "ready", "verified"}
        if not verified:
            raise AnalyticsError("EXT_ACCOUNT_UNAVAILABLE", "platform observations require verified external account evidence")
        return _hash(account_evidence if account_evidence is not None else {"org_id": str(tenant), "verified": True})

    def _event(
        self,
        event_type: str,
        observation: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        tenant: UUID,
        actor: UUID,
        trace: str,
        idempotency_key: str,
        at: datetime,
    ) -> dict[str, Any]:
        event_id = str(uuid5(
            _OBSERVATION_EVENT_NAMESPACE,
            f"{event_type}:{observation['id']}:{observation['observation_version']}",
        ))
        body = deepcopy(dict(payload))
        return {
            "event_id": event_id,
            "event_type": event_type,
            "event_schema_version": 1,
            "occurred_at": _stamp(at),
            "org_id": str(tenant),
            "trace_id": trace,
            "correlation_id": None,
            "causation_id": None,
            "aggregate_type": "Observation",
            "aggregate_id": observation["id"],
            "aggregate_version": observation["observation_version"],
            "actor_type": "user",
            "actor_id": str(actor),
            "idempotency_key": idempotency_key,
            "payload": body,
            "payload_hash": _hash(body),
        }

    def record_observation(
        self,
        observation: Mapping[str, Any] | None = None,
        *,
        payload: Mapping[str, Any] | None = None,
        metric_definition: Mapping[str, Any] | None = None,
        definition: Mapping[str, Any] | None = None,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any,
        expected_version: Any = None,
        if_match: Any = None,
        category: Any = None,
        external_account_available: bool = False,
        account_evidence: Mapping[str, Any] | None = None,
        recorded_at: Any = None,
        **fields: Any,
    ) -> dict[str, Any]:
        tenant, actor, trace, ctx = _context(
            tenant_context=tenant_context,
            context=context,
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        if observation is not None and payload is not None:
            raise AnalyticsError("OBSERVATION_INVALID", "provide observation or payload, not both")
        if metric_definition is not None and definition is not None:
            raise AnalyticsError("METRIC_DEFINITION_INVALID", "provide metric_definition or definition, not both")
        raw = observation if observation is not None else payload if payload is not None else {}
        if not isinstance(raw, Mapping):
            raise AnalyticsError("OBSERVATION_INVALID", "observation must be an object")
        values = {**dict(raw), **fields}
        unknown = sorted(set(values) - set(_OBSERVATION_SCHEMA["properties"]))
        if unknown:
            raise AnalyticsError("OBSERVATION_INVALID", "observation contains unsupported fields", details={"fields": unknown})
        requested_org = values.get("org_id")
        if requested_org is not None and _uuid(requested_org, "observation.org_id") != tenant:
            raise AnalyticsError("TENANT_SCOPE_VIOLATION", "observation belongs to another organization")
        supplied_definition = metric_definition if metric_definition is not None else definition
        metric = self._definition(supplied_definition, values=values, tenant=tenant, context=ctx)
        if metric["status"] != "active":
            raise AnalyticsError("METRIC_DEFINITION_NOT_ACTIVE", "metric definition must be active")
        for field, expected_value in (
            ("metric_definition_id", metric["id"]),
            ("metric_definition_version_no", metric["version_no"]),
            ("metric_name", metric["key"]),
            ("metric_type", metric["metric_type"]),
        ):
            if field in values and values[field] != expected_value:
                raise AnalyticsError("METRIC_DEFINITION_BINDING_MISMATCH", f"{field} does not match metric definition")
        source = _text(values.get("source"), "source", maximum=16).lower()
        if source not in {"site", "fake", "manual", "platform", "geo", "support", "qa"}:
            raise AnalyticsError("OBSERVATION_INVALID", "source is unsupported")
        subject_type = _text(values.get("subject_type"), "subject_type", maximum=32).lower()
        subject_id = str(_uuid(values.get("subject_id"), "subject_id"))
        observed = _time(values.get("observed_at"), "observed_at", required=True)
        locale = _locale(values.get("locale"))
        region = _region(values.get("region"))
        data_quality = _text(values.get("data_quality"), "data_quality", maximum=16).lower()
        if data_quality not in {"raw", "validated", "estimated"}:
            raise AnalyticsError("OBSERVATION_INVALID", "data_quality is unsupported")
        dedupe_key = _text(values.get("dedupe_key"), "dedupe_key", maximum=512)
        source_ref_value = values.get("source_snapshot_ref")
        source_ref = None if source_ref_value is None else _text(source_ref_value, "source_snapshot_ref", maximum=2048)
        if source in _SNAPSHOT_REQUIRED_SOURCES and source_ref is None:
            raise AnalyticsError("SOURCE_SNAPSHOT_REQUIRED", f"{source} observations require source_snapshot_ref")
        metric_value = deepcopy(values.get("metric_value"))
        _assert_safe_value(metric_value)
        encoded_value = _canonical(metric_value).encode("utf-8")
        if len(encoded_value) > 65536:
            raise AnalyticsError("OBSERVATION_VALUE_TOO_LARGE", "metric_value exceeds 64 KiB")
        canonical_category = self._category(category, metric, source, subject_type)
        event_definition = self.event_catalog.definition_for(canonical_category)
        if source not in event_definition["allowed_sources"]:
            raise AnalyticsError("OBSERVATION_SOURCE_CATEGORY_MISMATCH", "source is not allowed for analytics category")
        if subject_type not in event_definition["subject_types"]:
            raise AnalyticsError("OBSERVATION_SUBJECT_CATEGORY_MISMATCH", "subject is not allowed for analytics category")
        account_hash = self._account_hash(
            tenant=tenant,
            source=source,
            external_account_available=external_account_available,
            account_evidence=account_evidence,
        )
        idempotency = _text(idempotency_key, "idempotency_key", maximum=200)
        at = self._now(recorded_at)
        requested_version = values.get("observation_version")
        normalized = {
            "org_id": str(tenant),
            "source": source,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "metric_definition_id": metric["id"],
            "metric_definition_version_no": metric["version_no"],
            "metric_name": metric["key"],
            "metric_type": metric["metric_type"],
            "metric_value": metric_value,
            "observed_at": _stamp(observed),  # type: ignore[arg-type]
            "locale": locale,
            "region": region,
            "data_quality": data_quality,
            "dedupe_key": dedupe_key,
            "source_snapshot_ref": source_ref,
        }
        request = {
            "operation": "record_observation",
            "observation": normalized,
            "requested_id": values.get("id"),
            "requested_version": requested_version,
            "expected_version": expected_version,
            "if_match": if_match,
            "category": canonical_category,
            "account_evidence_hash": account_hash,
        }
        digest = _hash(request)
        with getattr(self.store, "lock", nullcontext()):
            replay = self._replay(str(tenant), "observation.record", idempotency, digest)
            if replay is not None:
                return replay
            versions = self.store.versions(str(tenant), dedupe_key)
            latest_version = versions[-1]["observation_version"] if versions else 0
            if requested_version is None:
                version_no = 1 if not versions else latest_version
            else:
                version_no = _positive(requested_version, "observation_version")
            generated_id = str(uuid5(_OBSERVATION_NAMESPACE, f"{tenant}:{dedupe_key}:{version_no}"))
            identity = str(_uuid(values["id"], "id")) if values.get("id") is not None else generated_id
            result = {"id": identity, **normalized, "observation_version": version_no}
            _validate_value(result, metric)
            snapshot_hash = _hash(result)
            if versions and version_no <= latest_version:
                existing = next((item for item in versions if item["observation_version"] == version_no), None)
                metadata = self.store.metadata(existing["id"]) if existing is not None else None
                if existing is not None and metadata is not None and metadata["snapshot_hash"] == snapshot_hash:
                    self.store.save_command(str(tenant), "observation.record", idempotency, digest, existing)
                    return deepcopy(existing)
                raise AnalyticsError("OBSERVATION_VERSION_CONFLICT", "observation version already exists with another snapshot")
            if version_no != latest_version + 1:
                raise AnalyticsError("OBSERVATION_VERSION_SEQUENCE_INVALID", "observation_version must be the next version")
            if versions:
                expected_current = _expected(expected_version, if_match)
                if expected_current != latest_version:
                    raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "observation version changed")
                first = versions[0]
                identity_fields = ("source", "subject_type", "subject_id", "metric_definition_id", "metric_name", "metric_type")
                if any(first[field] != result[field] for field in identity_fields):
                    raise AnalyticsError("OBSERVATION_IDENTITY_CHANGED", "observation revisions must keep source, subject and metric identity")
            elif expected_version is not None or if_match is not None:
                raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "first observation has no prior version")
            generic_payload = {
                "aggregate_id": result["id"],
                "aggregate_version": version_no,
                "from_state": None,
                "to_state": "recorded",
                "command": "record",
                "snapshot_hash": snapshot_hash,
                "reason": None,
                "source": source,
                "data_quality": data_quality,
            }
            generic_event = self._event(
                "observation.recorded", result, generic_payload,
                tenant=tenant, actor=actor, trace=trace, idempotency_key=idempotency, at=at,
            )
            canonical_payload = {
                "aggregate_id": result["id"],
                "aggregate_version": version_no,
                "category": canonical_category,
                "observation_id": result["id"],
                "metric_definition_id": metric["id"],
                "metric_definition_version_no": metric["version_no"],
                "source": source,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "observed_at": result["observed_at"],
                "data_quality": data_quality,
                "snapshot_hash": snapshot_hash,
            }
            canonical_event = self._event(
                event_definition["event_type"], result, canonical_payload,
                tenant=tenant, actor=actor, trace=trace, idempotency_key=idempotency, at=at,
            )
            self.event_catalog.validate_event(
                canonical_event,
                external_account_available=source != "platform" or account_hash is not None,
            )
            metadata = {
                "snapshot_hash": snapshot_hash,
                "category": canonical_category,
                "source_event_type": canonical_event["event_type"],
                "source_event_id": canonical_event["event_id"],
                "account_evidence_hash": account_hash,
                "created_by": str(actor),
                "created_at": _stamp(at),
            }
            self.store.save(result, metadata)
            self.store.outbox.extend((deepcopy(generic_event), deepcopy(canonical_event)))
            self.store.audit.append(
                {
                    "event_type": "observation.recorded",
                    "org_id": str(tenant),
                    "actor_id": str(actor),
                    "trace_id": trace,
                    "observation_id": result["id"],
                    "observation_version": version_no,
                    "metric_definition_id": metric["id"],
                    "metric_definition_version_no": metric["version_no"],
                    "source": source,
                    "category": canonical_category,
                    "data_quality": data_quality,
                    "snapshot_hash": snapshot_hash,
                    "occurred_at": _stamp(at),
                }
            )
            self.store.save_command(str(tenant), "observation.record", idempotency, digest, result)
            return deepcopy(result)

    record = record_observation
    ingest = record_observation
    create_observation = record_observation
    append_observation = record_observation

    def revise_observation(self, observation: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        return self.record_observation(observation, **kwargs)

    def get_observation(
        self,
        observation_id: Any,
        *,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
    ) -> dict[str, Any]:
        tenant, _, _, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id)
        identity = str(_uuid(observation_id, "observation_id"))
        with getattr(self.store, "lock", nullcontext()):
            value = self.store.get(identity)
            if value is None:
                raise AnalyticsError("OBSERVATION_NOT_FOUND", "observation does not exist")
            if value["org_id"] != str(tenant):
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "observation belongs to another organization")
            return value

    get = get_observation

    def list_observations(
        self,
        *,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        dedupe_key: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant, _, _, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id)
        with getattr(self.store, "lock", nullcontext()):
            if dedupe_key is not None:
                return self.store.versions(str(tenant), _text(dedupe_key, "dedupe_key", maximum=512))
            rows = [
                deepcopy(item) for item in self.store._observations.values()
                if item["org_id"] == str(tenant)
            ]
        return tuple(sorted(rows, key=lambda item: (item["dedupe_key"], item["observation_version"])))

    list = list_observations


AnalyticsObservationService = ObservationService
ObservationIngestionService = ObservationService
ObservationRepository = InMemoryObservationStore


__all__ = [
    "AnalyticsObservationService",
    "AnalyticsObservationStore",
    "InMemoryObservationStore",
    "ObservationError",
    "ObservationIngestionService",
    "ObservationRepository",
    "ObservationService",
    "ObservationServiceError",
    "ObservationStore",
]
