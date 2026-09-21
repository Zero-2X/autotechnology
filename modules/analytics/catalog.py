"""Canonical analytics event catalogue and versioned metric definitions.

ANALYTICS-001 is deliberately account-free.  It defines the event vocabulary
used by later observation writers and owns immutable metric configuration.
Platform-sourced events are accepted only when the caller supplies verified
account availability; fake and manual sources remain usable for M1.
"""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
import yaml


_ROOT = Path(__file__).resolve().parents[2]
_METRIC_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/metric-definition.schema.json").read_text(encoding="utf-8")
)
_CATALOG_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/analytics-event-catalog.schema.json").read_text(encoding="utf-8")
)
_CATALOG_PATH = _ROOT / "docs/contracts/analytics-event-catalog-v1.yaml"
_EVENT_ENVELOPE = json.loads(
    (_ROOT / "packages/contracts/events/event-envelope.schema.json").read_text(encoding="utf-8")
)
_METRIC_VALIDATOR = Draft202012Validator(_METRIC_SCHEMA, format_checker=FormatChecker())
_CATALOG_VALIDATOR = Draft202012Validator(_CATALOG_SCHEMA, format_checker=FormatChecker())
_SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
_DEFINITION_NAMESPACE = UUID("853ca690-9570-5e6e-b9d2-f2f58880203d")
_EVENT_NAMESPACE = UUID("fc67b68c-e121-50fd-9559-ed012af03924")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_.]{0,127}$")
_DIMENSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MISSING = object()


class AnalyticsError(ValueError):
    """Stable machine-readable analytics failure."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


MetricDefinitionError = AnalyticsError
AnalyticsCatalogError = AnalyticsError


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
        raise AnalyticsError("ANALYTICS_INVALID", "value must be finite JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be text")
    result = value.strip()
    if not result:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be non-empty")
    if len(result) > maximum:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} exceeds {maximum} characters")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} contains a control character")
    return result


def _uuid(value: Any, field: str, *, required: bool = True) -> UUID | None:
    if value is None and not required:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a UUID") from exc


def _time(value: Any, field: str, *, required: bool = False) -> datetime | None:
    if value is None:
        if required:
            raise AnalyticsError("ANALYTICS_INVALID", f"{field} is required")
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be ISO-8601") from exc
    else:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalyticsError("ANALYTICS_INVALID", "timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _positive_version(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a positive integer") from exc
    if result < 1 or str(value).strip() not in {str(result), f'"{result}"'}:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a positive integer")
    return result


def _expected_version(expected_version: Any, if_match: Any) -> int:
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


def _context(
    *,
    tenant_context: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    org_id: Any = None,
    actor_id: Any = None,
    trace_id: Any = None,
) -> tuple[UUID, UUID, str, Mapping[str, Any]]:
    if tenant_context is not None and context is not None and tenant_context != context:
        raise AnalyticsError("INVALID_TENANT_CONTEXT", "context and tenant_context disagree")
    ctx = tenant_context if tenant_context is not None else context if context is not None else {}
    if not isinstance(ctx, Mapping):
        raise AnalyticsError("INVALID_TENANT_CONTEXT", "tenant context must be an object")
    markers = [value for value in (org_id, ctx.get("org_id"), ctx.get("tenant_id")) if value is not None]
    if not markers:
        raise AnalyticsError("INVALID_TENANT_CONTEXT", "org_id is required")
    try:
        tenant = markers[0] if isinstance(markers[0], UUID) else UUID(str(markers[0]))
        for marker in markers[1:]:
            if (marker if isinstance(marker, UUID) else UUID(str(marker))) != tenant:
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "tenant context markers disagree")
    except AnalyticsError:
        raise
    except (TypeError, ValueError, AttributeError) as exc:
        raise AnalyticsError("INVALID_TENANT_CONTEXT", "org_id must be a UUID") from exc
    actor_value = actor_id if actor_id is not None else ctx.get("actor_id", ctx.get("actor"))
    actor = _SYSTEM_ACTOR if actor_value is None else _uuid(actor_value, "actor_id")
    trace = _text(trace_id if trace_id is not None else ctx.get("trace_id", "analytics-001"), "trace_id", maximum=256)
    return tenant, actor, trace, ctx


def _dimensions(value: Any) -> list[str]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise AnalyticsError("ANALYTICS_INVALID", "dimensions must be an array")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        name = _text(item, "dimensions[]", maximum=64).lower()
        if _DIMENSION_RE.fullmatch(name) is None:
            raise AnalyticsError("ANALYTICS_INVALID", "dimension names must use snake_case")
        if name in seen:
            raise AnalyticsError("ANALYTICS_INVALID", "dimensions must be unique")
        seen.add(name)
        result.append(name)
    return result


def _quality_rules(value: Any, metric_type: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AnalyticsError("ANALYTICS_INVALID", "quality_rules must be an object")
    rules = deepcopy(dict(value))
    if set(rules) - {"value_schema"}:
        raise AnalyticsError("ANALYTICS_INVALID", "quality_rules contains unsupported keys")
    schema = rules.get("value_schema")
    if metric_type in {"json", "enum"} and not isinstance(schema, Mapping):
        raise AnalyticsError("ANALYTICS_INVALID", f"{metric_type} metrics require quality_rules.value_schema")
    if schema is not None:
        if not isinstance(schema, Mapping) or not schema:
            raise AnalyticsError("ANALYTICS_INVALID", "value_schema must be a non-empty object")
        if "$ref" in _canonical(schema):
            raise AnalyticsError("ANALYTICS_INVALID", "value_schema must be self-contained")
        try:
            Draft202012Validator.check_schema(dict(schema))
        except SchemaError as exc:
            raise AnalyticsError("ANALYTICS_INVALID", "value_schema is not a valid offline schema") from exc
    return rules


class CanonicalEventCatalog:
    """Read and validate the nine account-aware canonical event families."""

    def __init__(self, catalog: Mapping[str, Any] | None = None) -> None:
        raw = catalog if catalog is not None else yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise AnalyticsError("CANONICAL_EVENT_CATALOG_INVALID", "event catalogue must be an object")
        try:
            _CATALOG_VALIDATOR.validate(raw)
        except ValidationError as exc:
            raise AnalyticsError("CANONICAL_EVENT_CATALOG_INVALID", "event catalogue violates its schema") from exc
        self._catalog = deepcopy(dict(raw))
        self._by_category: dict[str, dict[str, Any]] = {}
        self._by_event_type: dict[str, dict[str, Any]] = {}
        for item in self._catalog["categories"]:
            category, event_type = item["category"], item["event_type"]
            if category in self._by_category or event_type in self._by_event_type:
                raise AnalyticsError("CANONICAL_EVENT_CATALOG_INVALID", "event categories and types must be unique")
            if event_type != f"analytics.{category}.observed":
                raise AnalyticsError("CANONICAL_EVENT_CATALOG_INVALID", "event type must match its category")
            path = _ROOT / item["event_schema_ref"]
            if not path.is_file():
                raise AnalyticsError("CANONICAL_EVENT_CATALOG_INVALID", f"missing event schema for {event_type}")
            self._by_category[category] = deepcopy(item)
            self._by_event_type[event_type] = deepcopy(item)

    def list_definitions(self) -> tuple[dict[str, Any], ...]:
        return tuple(deepcopy(self._by_category[key]) for key in sorted(self._by_category))

    list_categories = list_definitions

    def definition_for(self, category: str) -> dict[str, Any]:
        try:
            return deepcopy(self._by_category[_text(category, "category", maximum=32).lower()])
        except KeyError as exc:
            raise AnalyticsError("CANONICAL_EVENT_CATEGORY_UNKNOWN", "unknown canonical event category") from exc

    def category_for(self, event_type: str) -> str:
        try:
            return self._by_event_type[_text(event_type, "event_type", maximum=128)]["category"]
        except KeyError as exc:
            raise AnalyticsError("CANONICAL_EVENT_TYPE_UNKNOWN", "event type is not canonical analytics input") from exc

    def validate_event(
        self,
        event: Mapping[str, Any],
        *,
        external_account_available: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise AnalyticsError("CANONICAL_EVENT_INVALID", "event must be an object")
        value = deepcopy(dict(event))
        event_type = value.get("event_type")
        try:
            definition = self._by_event_type[str(event_type)]
        except KeyError as exc:
            raise AnalyticsError("CANONICAL_EVENT_TYPE_UNKNOWN", "event type is not canonical analytics input") from exc
        schema = json.loads((_ROOT / definition["event_schema_ref"]).read_text(encoding="utf-8"))
        resolved = deepcopy(schema)
        resolved["allOf"][0] = deepcopy(_EVENT_ENVELOPE)
        try:
            Draft202012Validator(resolved, format_checker=FormatChecker()).validate(value)
        except ValidationError as exc:
            raise AnalyticsError("CANONICAL_EVENT_INVALID", "event violates its canonical schema") from exc
        payload = value["payload"]
        analytics_fields = {
            "category", "observation_id", "metric_definition_id",
            "metric_definition_version_no", "source", "subject_type", "subject_id",
            "observed_at", "data_quality", "snapshot_hash",
        }
        missing = sorted(analytics_fields - set(payload))
        if missing:
            raise AnalyticsError(
                "CANONICAL_EVENT_INVALID",
                "canonical analytics payload is incomplete",
                details={"missing": missing},
            )
        source = payload["source"]
        if source in definition["account_gated_sources"] and not external_account_available:
            raise AnalyticsError(
                "EXT_ACCOUNT_UNAVAILABLE",
                "platform-sourced analytics require verified external account evidence",
            )
        if payload["category"] != definition["category"]:
            raise AnalyticsError("CANONICAL_EVENT_INVALID", "event category does not match event type")
        return value

    validate = validate_event


class InMemoryMetricDefinitionStore:
    """Deterministic in-memory adapter used by unit and contract workflows."""

    def __init__(self) -> None:
        self.lock = RLock()
        self._definitions: dict[str, dict[str, Any]] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._commands: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.outbox: list[dict[str, Any]] = []

    def save_definition(self, definition: Mapping[str, Any]) -> None:
        identity = str(definition["id"])
        if identity in self._definitions:
            raise AnalyticsError("METRIC_DEFINITION_CONFLICT", "metric definition id already exists")
        self._definitions[identity] = deepcopy(dict(definition))
        self._states[identity] = {
            "status": definition["status"],
            "effective_at": definition["effective_at"],
            "retired_at": definition["retired_at"],
        }

    def project(self, identity: str) -> dict[str, Any] | None:
        base = self._definitions.get(identity)
        if base is None:
            return None
        value = deepcopy(base)
        value.update(deepcopy(self._states[identity]))
        return value

    def save_state(self, identity: str, state: Mapping[str, Any]) -> None:
        if identity not in self._definitions:
            raise AnalyticsError("METRIC_DEFINITION_NOT_FOUND", "metric definition does not exist")
        self._states[identity] = deepcopy(dict(state))

    def versions(self, org_id: str | None, key: str) -> tuple[dict[str, Any], ...]:
        rows = [
            self.project(identity)
            for identity, item in self._definitions.items()
            if item["org_id"] == org_id and item["key"] == key
        ]
        return tuple(sorted((row for row in rows if row is not None), key=lambda row: row["version_no"]))

    def command(self, scope: str, namespace: str, key: str) -> dict[str, Any] | None:
        value = self._commands.get((scope, namespace, key))
        return deepcopy(value) if value is not None else None

    def save_command(
        self,
        scope: str,
        namespace: str,
        key: str,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> None:
        self._commands[(scope, namespace, key)] = {
            "request_hash": request_hash,
            "response": deepcopy(dict(response)),
        }


MetricDefinitionStore = InMemoryMetricDefinitionStore
AnalyticsStore = InMemoryMetricDefinitionStore


class MetricDefinitionService:
    """Create immutable metric versions and append-only lifecycle facts."""

    def __init__(
        self,
        store: InMemoryMetricDefinitionStore | None = None,
        *,
        event_catalog: CanonicalEventCatalog | None = None,
        clock: Any | None = None,
    ) -> None:
        self.store = store or InMemoryMetricDefinitionStore()
        self.event_catalog = event_catalog or CanonicalEventCatalog()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self, value: Any = None) -> datetime:
        return _time(value, "occurred_at", required=True) if value is not None else _time(self._clock(), "clock", required=True)  # type: ignore[return-value]

    def _scope(self, org_id: str | None) -> str:
        return "global" if org_id is None else org_id

    def _replay(self, scope: str, namespace: str, key: str, digest: str) -> dict[str, Any] | None:
        prior = self.store.command(scope, namespace, key)
        if prior is None:
            return None
        if prior["request_hash"] != digest:
            raise AnalyticsError("IDEMPOTENCY_KEY_REUSED", "idempotency key was reused with another payload")
        return deepcopy(prior["response"])

    def _validate_definition(self, value: Mapping[str, Any]) -> dict[str, Any]:
        result = deepcopy(dict(value))
        try:
            _METRIC_VALIDATOR.validate(result)
        except ValidationError as exc:
            raise AnalyticsError("METRIC_DEFINITION_INVALID", "metric definition violates its schema") from exc
        return result

    def _emit(
        self,
        event_type: str,
        definition: Mapping[str, Any],
        *,
        tenant: UUID,
        actor: UUID,
        trace: str,
        idempotency_key: str,
        command: str,
        from_state: str | None,
        at: datetime,
    ) -> None:
        payload = {
            "aggregate_id": definition["id"],
            "aggregate_version": definition["version_no"],
            "from_state": from_state,
            "to_state": definition["status"],
            "command": command,
            "snapshot_hash": definition["snapshot_hash"],
            "reason": None,
        }
        event_id = str(uuid5(_EVENT_NAMESPACE, f"{event_type}:{definition['id']}:{definition['version_no']}:{idempotency_key}"))
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "event_schema_version": 1,
            "occurred_at": _stamp(at),
            "org_id": str(tenant),
            "trace_id": trace,
            "correlation_id": None,
            "causation_id": None,
            "aggregate_type": "MetricDefinition",
            "aggregate_id": definition["id"],
            "aggregate_version": definition["version_no"],
            "actor_type": "user",
            "actor_id": str(actor),
            "idempotency_key": idempotency_key,
            "payload": payload,
            "payload_hash": _hash(payload),
        }
        self.store.outbox.append(deepcopy(event))
        self.store.audit.append(
            {
                "event_type": event_type,
                "org_id": str(tenant),
                "actor_id": str(actor),
                "trace_id": trace,
                "aggregate_id": definition["id"],
                "aggregate_version": definition["version_no"],
                "scope": self._scope(definition["org_id"]),
                "snapshot_hash": definition["snapshot_hash"],
                "occurred_at": _stamp(at),
            }
        )

    def create_metric_definition(
        self,
        definition: Mapping[str, Any] | None = None,
        *,
        payload: Mapping[str, Any] | None = None,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any,
        expected_version: Any = None,
        if_match: Any = None,
        global_catalog: bool = False,
        occurred_at: Any = None,
        **fields: Any,
    ) -> dict[str, Any]:
        tenant, actor, trace, ctx = _context(
            tenant_context=tenant_context,
            context=context,
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        if definition is not None and payload is not None:
            raise AnalyticsError("ANALYTICS_INVALID", "provide definition or payload, not both")
        raw = definition if definition is not None else payload if payload is not None else {}
        if not isinstance(raw, Mapping):
            raise AnalyticsError("ANALYTICS_INVALID", "definition must be an object")
        values = {**dict(raw), **fields}
        allowed_fields = set(_METRIC_SCHEMA["properties"])
        unknown_fields = sorted(set(values) - allowed_fields)
        if unknown_fields:
            raise AnalyticsError(
                "ANALYTICS_INVALID",
                "definition contains unsupported fields",
                details={"fields": unknown_fields},
            )
        if values.get("status", "draft") != "draft":
            raise AnalyticsError("ANALYTICS_INVALID", "new metric definitions must start as draft")
        for managed_field in ("id", "effective_at", "retired_at", "snapshot_hash"):
            if managed_field in values and values[managed_field] is not None:
                raise AnalyticsError("ANALYTICS_INVALID", f"{managed_field} is service-managed")
        requested_org = values.get("org_id", _MISSING)
        wants_global = global_catalog or requested_org is None and requested_org is not _MISSING
        if wants_global:
            authorized = global_catalog or bool(ctx.get("global_catalog_admin") or ctx.get("can_manage_global_catalog"))
            if not authorized:
                raise AnalyticsError("GLOBAL_CATALOG_FORBIDDEN", "global metric definitions require catalogue permission")
            definition_org: str | None = None
        else:
            if requested_org is not _MISSING and _uuid(requested_org, "definition.org_id") != tenant:
                raise AnalyticsError("TENANT_SCOPE_VIOLATION", "metric definition belongs to another organization")
            definition_org = str(tenant)
        key = _text(values.get("key"), "key", maximum=128).lower()
        if _KEY_RE.fullmatch(key) is None:
            raise AnalyticsError("ANALYTICS_INVALID", "key must use lower-case dotted notation")
        metric_type = _text(values.get("metric_type"), "metric_type", maximum=16).lower()
        if metric_type not in {"number", "boolean", "string", "enum", "json"}:
            raise AnalyticsError("ANALYTICS_INVALID", "metric_type is unsupported")
        at = self._now(occurred_at)
        idempotency = _text(idempotency_key, "idempotency_key", maximum=200)
        scope = self._scope(definition_org)
        owner = _uuid(values.get("owner_actor_id"), "owner_actor_id", required=False)
        normalized = {
            "org_id": definition_org,
            "key": key,
            "metric_type": metric_type,
            "unit": _text(values.get("unit"), "unit", maximum=64),
            "formula": _text(values.get("formula"), "formula", maximum=4096),
            "dimensions": _dimensions(values.get("dimensions", [])),
            "window": _text(values.get("window"), "window", maximum=128),
            "data_source": _text(values.get("data_source"), "data_source", maximum=256),
            "dedupe_rule": _text(values.get("dedupe_rule"), "dedupe_rule", maximum=512),
            "quality_rules": _quality_rules(values.get("quality_rules", {}), metric_type),
            "owner_actor_id": str(owner) if owner is not None else None,
        }
        requested_version = values.get("version_no")
        request = {
            "operation": "create",
            "scope": scope,
            "definition": normalized,
            "requested_version": requested_version,
            "expected_version": expected_version,
            "if_match": if_match,
        }
        digest = _hash(request)
        lock = getattr(self.store, "lock", nullcontext())
        with lock:
            replay = self._replay(scope, "metric_definition.create", idempotency, digest)
            if replay is not None:
                return replay
            versions = self.store.versions(definition_org, key)
            next_version = 1 if not versions else versions[-1]["version_no"] + 1
            supplied_version = requested_version if requested_version is not None else next_version
            version_no = _positive_version(supplied_version, "version_no")
            if version_no != next_version:
                raise AnalyticsError("METRIC_VERSION_SEQUENCE_INVALID", "version_no must be the next version")
            if versions:
                expected = _expected_version(expected_version, if_match)
                if expected != versions[-1]["version_no"]:
                    raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "latest metric definition version changed")
            elif expected_version is not None or if_match is not None:
                raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "first metric definition has no prior version")
            identity = str(uuid5(_DEFINITION_NAMESPACE, f"{scope}:{key}:{version_no}"))
            immutable = {
                "id": identity,
                "version_no": version_no,
                **normalized,
            }
            result = {
                **immutable,
                "status": "draft",
                "effective_at": None,
                "retired_at": None,
                "snapshot_hash": _hash(immutable),
            }
            result = self._validate_definition(result)
            self.store.save_definition(result)
            self._emit(
                "metric.definition.created",
                result,
                tenant=tenant,
                actor=actor,
                trace=trace,
                idempotency_key=idempotency,
                command="create_draft",
                from_state=None,
                at=at,
            )
            self.store.save_command(scope, "metric_definition.create", idempotency, digest, result)
            return deepcopy(result)

    create = create_metric_definition
    register_metric_definition = create_metric_definition
    create_definition = create_metric_definition

    def create_global_metric_definition(self, definition: Mapping[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.create_metric_definition(definition, global_catalog=True, **kwargs)

    def _load(self, identity: Any, tenant: UUID) -> dict[str, Any]:
        definition_id = str(_uuid(identity, "definition_id"))
        value = self.store.project(definition_id)
        if value is None:
            raise AnalyticsError("METRIC_DEFINITION_NOT_FOUND", "metric definition does not exist")
        if value["org_id"] not in {None, str(tenant)}:
            raise AnalyticsError("TENANT_SCOPE_VIOLATION", "metric definition belongs to another organization")
        return value

    def get_metric_definition(
        self,
        definition_id: Any,
        *,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
    ) -> dict[str, Any]:
        tenant, _, _, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id)
        with getattr(self.store, "lock", nullcontext()):
            return deepcopy(self._load(definition_id, tenant))

    get = get_metric_definition

    def list_metric_definitions(
        self,
        *,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        include_global: bool = True,
        status: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        tenant, _, _, _ = _context(tenant_context=tenant_context, context=context, org_id=org_id)
        accepted = {str(tenant), None} if include_global else {str(tenant)}
        rows = []
        with getattr(self.store, "lock", nullcontext()):
            for identity, base in self.store._definitions.items():
                if base["org_id"] not in accepted:
                    continue
                value = self.store.project(identity)
                if value is not None and (status is None or value["status"] == status):
                    rows.append(value)
        return tuple(sorted((deepcopy(row) for row in rows), key=lambda row: (row["key"], row["version_no"])))

    list = list_metric_definitions

    def activate_metric_definition(
        self,
        definition_id: Any,
        *,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any,
        expected_version: Any = None,
        if_match: Any = None,
        global_catalog: bool = False,
        occurred_at: Any = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, ctx = _context(
            tenant_context=tenant_context,
            context=context,
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        expected = _expected_version(expected_version, if_match)
        idempotency = _text(idempotency_key, "idempotency_key", maximum=200)
        at = self._now(occurred_at)
        identity = str(_uuid(definition_id, "definition_id"))
        request = {"operation": "activate", "definition_id": identity, "expected_version": expected}
        digest = _hash(request)
        with getattr(self.store, "lock", nullcontext()):
            current = self._load(identity, tenant)
            scope = self._scope(current["org_id"])
            if current["org_id"] is None and not (
                global_catalog or ctx.get("global_catalog_admin") or ctx.get("can_manage_global_catalog")
            ):
                raise AnalyticsError("GLOBAL_CATALOG_FORBIDDEN", "global metric definitions require catalogue permission")
            replay = self._replay(scope, "metric_definition.activate", idempotency, digest)
            if replay is not None:
                return replay
            if expected != current["version_no"]:
                raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "metric definition version changed")
            if current["status"] != "draft":
                raise AnalyticsError("METRIC_DEFINITION_STATE_INVALID", "only draft definitions can be activated")
            state = {"status": "active", "effective_at": _stamp(at), "retired_at": None}
            self.store.save_state(identity, state)
            result = self._validate_definition(self.store.project(identity) or {})
            self._emit(
                "metric.definition.activated",
                result,
                tenant=tenant,
                actor=actor,
                trace=trace,
                idempotency_key=idempotency,
                command="activate",
                from_state="draft",
                at=at,
            )
            self.store.save_command(scope, "metric_definition.activate", idempotency, digest, result)
            return deepcopy(result)

    activate = activate_metric_definition

    def activate_global_metric_definition(self, definition_id: Any, **kwargs: Any) -> dict[str, Any]:
        return self.activate_metric_definition(definition_id, global_catalog=True, **kwargs)

    def retire_metric_definition(
        self,
        definition_id: Any,
        *,
        replacement_definition_id: Any,
        tenant_context: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        org_id: Any = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any,
        expected_version: Any = None,
        if_match: Any = None,
        global_catalog: bool = False,
        occurred_at: Any = None,
    ) -> dict[str, Any]:
        tenant, actor, trace, ctx = _context(
            tenant_context=tenant_context,
            context=context,
            org_id=org_id,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        expected = _expected_version(expected_version, if_match)
        idempotency = _text(idempotency_key, "idempotency_key", maximum=200)
        at = self._now(occurred_at)
        identity = str(_uuid(definition_id, "definition_id"))
        replacement_id = str(_uuid(replacement_definition_id, "replacement_definition_id"))
        request = {
            "operation": "retire",
            "definition_id": identity,
            "replacement_definition_id": replacement_id,
            "expected_version": expected,
        }
        digest = _hash(request)
        with getattr(self.store, "lock", nullcontext()):
            current = self._load(identity, tenant)
            replacement = self._load(replacement_id, tenant)
            scope = self._scope(current["org_id"])
            if current["org_id"] is None and not (
                global_catalog or ctx.get("global_catalog_admin") or ctx.get("can_manage_global_catalog")
            ):
                raise AnalyticsError("GLOBAL_CATALOG_FORBIDDEN", "global metric definitions require catalogue permission")
            replay = self._replay(scope, "metric_definition.retire", idempotency, digest)
            if replay is not None:
                return replay
            if expected != current["version_no"]:
                raise AnalyticsError("OPTIMISTIC_LOCK_CONFLICT", "metric definition version changed")
            if current["status"] != "active":
                raise AnalyticsError("METRIC_DEFINITION_STATE_INVALID", "only active definitions can be retired")
            if (
                replacement["org_id"] != current["org_id"]
                or replacement["key"] != current["key"]
                or replacement["version_no"] <= current["version_no"]
                or replacement["status"] != "active"
            ):
                raise AnalyticsError(
                    "METRIC_REPLACEMENT_INVALID",
                    "retirement requires a later active version in the same scope",
                )
            state = {"status": "retired", "effective_at": current["effective_at"], "retired_at": _stamp(at)}
            self.store.save_state(identity, state)
            result = self._validate_definition(self.store.project(identity) or {})
            self._emit(
                "metric.definition.retired",
                result,
                tenant=tenant,
                actor=actor,
                trace=trace,
                idempotency_key=idempotency,
                command="retire",
                from_state="active",
                at=at,
            )
            self.store.save_command(scope, "metric_definition.retire", idempotency, digest, result)
            return deepcopy(result)

    retire = retire_metric_definition

    def retire_global_metric_definition(self, definition_id: Any, **kwargs: Any) -> dict[str, Any]:
        return self.retire_metric_definition(definition_id, global_catalog=True, **kwargs)

    def validate_canonical_event(
        self,
        event: Mapping[str, Any],
        *,
        external_account_available: bool = False,
    ) -> dict[str, Any]:
        return self.event_catalog.validate_event(
            event,
            external_account_available=external_account_available,
        )


AnalyticsCatalogService = MetricDefinitionService
AnalyticsEventCatalogService = MetricDefinitionService
AnalyticsService = MetricDefinitionService


__all__ = [
    "AnalyticsCatalogError",
    "AnalyticsCatalogService",
    "AnalyticsError",
    "AnalyticsEventCatalogService",
    "AnalyticsService",
    "AnalyticsStore",
    "CanonicalEventCatalog",
    "InMemoryMetricDefinitionStore",
    "MetricDefinitionError",
    "MetricDefinitionService",
    "MetricDefinitionStore",
]
