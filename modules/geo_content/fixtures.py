"""GEO_CONTENT-002 query fixtures and offline command port.

The fixture service owns a small immutable prompt test set.  It deliberately
keeps commands, transition events, and audit rows in an in-memory port so the
module can be exercised without a database or an external search provider.
The corresponding migration stores only the durable ``geo_query_fixtures``
projection; a composition root may replace this port with a repository.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/geo-query-fixture.schema.json")
    .read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_UUID_NAMESPACE = UUID("b2b5b2a0-8522-5a13-a0d1-2f1c2b8c4d02")
_STATES = frozenset({"created", "active", "retired"})
_BAD_PREDECESSOR_STATES = frozenset(
    {
        "blocked", "expired", "failed", "invalid", "rejected", "retired", "stale", "withdrawn",
        "pending", "draft", "unknown", "quarantined", "review", "manual_review", "cancelled",
    }
)
_READY_PREDECESSOR_STATES = frozenset(
    {
        "active", "approved", "published", "ready", "rendered", "succeeded", "valid", "verified",
        "captured", "completed", "complete", "done", "fact_checked", "evidence_pending", "usable", "fresh",
    }
)


class GeoQueryFixtureError(ValueError):
    """Stable machine-readable error for GEO_CONTENT-002 commands."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    except (TypeError, ValueError) as exc:
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "value must be finite JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, maximum: int = 4096, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} must be non-empty")
    if len(result) > maximum:
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} exceeds {maximum} characters")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} contains a control character")
    return result


def _uuid(value: Any, field: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GeoQueryFixtureError("INVALID_TENANT_CONTEXT", f"{field} must be a UUID") from exc


def _actor(value: Any) -> str:
    if value is None:
        return "00000000-0000-4000-8000-000000000000"
    if isinstance(value, UUID):
        return str(value)
    return _text(value, "actor_id", maximum=256)


def _time(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    if value is None and default is not None:
        parsed = default
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} must be ISO-8601") from exc
    else:
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sequence(value: Any, field: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field} must be an array")
    return list(value)


def _refs(value: Any, field: str, *, uuid_only: bool = False) -> list[str]:
    result: list[str] = []
    for item in _sequence(value, field):
        if isinstance(item, UUID):
            ref = str(item)
        else:
            ref = _text(item, f"{field}[]", maximum=256)
        if uuid_only:
            try:
                ref = str(UUID(ref))
            except (TypeError, ValueError) as exc:
                raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{field}[] must be a UUID") from exc
        if ref not in result:
            result.append(ref)
    return result


def _fixture_identity_payload(
    *,
    org_id: str,
    query: str,
    locale: str,
    region: str,
    expected_entities: Sequence[str],
    expected_claim_ids: Sequence[str],
    predecessor_hash: str | None,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the stable business payload covered by ``fixture_hash``.

    The raw predecessor snapshot is hashed separately.  Including that digest
    here keeps the fixture digest reproducible from the persisted projection,
    even though the full predecessor snapshot is deliberately not copied into
    the fixture row.
    """

    return {
        "org_id": org_id,
        "query": query,
        "locale": locale,
        "region": region,
        "expected_entities": list(expected_entities),
        "expected_claim_ids": list(expected_claim_ids),
        "predecessor_hash": predecessor_hash,
        "metadata": deepcopy(dict(metadata)),
    }


def validate_fixture_integrity(
    fixture: Mapping[str, Any],
    *,
    predecessor_artifacts: Mapping[str, Any] | None = None,
) -> None:
    """Validate a fixture projection at every trust boundary.

    Store-backed rows and caller-supplied fixture objects must receive the
    same checks.  JSON Schema catches shape/format errors; this function adds
    the cross-field invariants that protect the immutable business digest.
    """

    if not isinstance(fixture, Mapping):
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "fixture must be an object")
    errors = sorted(_VALIDATOR.iter_errors(dict(fixture)), key=lambda error: list(error.path))
    if errors:
        location = ".".join(str(part) for part in errors[0].path) or "fixture"
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", f"{location}: {errors[0].message}")
    query = _text(fixture.get("query"), "fixture.query", maximum=4096)
    prompt = fixture.get("prompt")
    if prompt is not None and _text(prompt, "fixture.prompt", maximum=4096) != query:
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "fixture.query and fixture.prompt disagree")
    expected_entities = [
        _text(item, "fixture.expected_entities[]", maximum=512)
        for item in fixture.get("expected_entities", [])
    ]
    expected_claim_ids = [
        str(UUID(str(item))) for item in fixture.get("expected_claim_ids", [])
    ]
    predecessor_hash = fixture.get("predecessor_hash")
    if predecessor_artifacts is not None:
        org_id = _uuid(fixture.get("org_id"), "fixture.org_id")
        assert org_id is not None
        validate_predecessors(predecessor_artifacts, org_id=org_id)
    if fixture.get("prompt_hash") is not None and fixture.get("prompt_hash") != _hash(query):
        raise GeoQueryFixtureError("FIXTURE_HASH_MISMATCH", "prompt hash does not match query")
    # A projection with no raw predecessor snapshot can still be fully
    # re-derived.  For older rows that carried a predecessor digest, the
    # digest itself is the persisted input to this calculation.
    identity_payload = _fixture_identity_payload(
        org_id=str(UUID(str(fixture["org_id"]))),
        query=query,
        locale=_text(fixture.get("locale"), "fixture.locale", maximum=32),
        region=_text(fixture.get("region"), "fixture.region", maximum=128),
        expected_entities=expected_entities,
        expected_claim_ids=expected_claim_ids,
        predecessor_hash=predecessor_hash,
        metadata=fixture.get("metadata") or {},
    )
    expected_hash = _hash(identity_payload)
    if fixture.get("fixture_hash") != expected_hash:
        raise GeoQueryFixtureError("FIXTURE_HASH_MISMATCH", "fixture hash does not match immutable payload")


def _tenant_markers(record: Mapping[str, Any]) -> list[Any]:
    return [record[name] for name in ("org_id", "tenant_id") if name in record]


def _guard_nested_tenant(value: Any, tenant: str, field: str = "predecessor_artifacts") -> None:
    """Reject every nested tenant marker that is outside the command tenant."""

    if isinstance(value, Mapping):
        for marker in _tenant_markers(value):
            if marker is None or _uuid(marker, f"{field}.org_id") != tenant:
                raise GeoQueryFixtureError("TENANT_SCOPE_VIOLATION", f"{field} is outside this organization")
        for name, child in value.items():
            if isinstance(child, Mapping):
                _guard_nested_tenant(child, tenant, f"{field}.{name}")
            elif isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                for index, item in enumerate(child):
                    if isinstance(item, Mapping) or (
                        isinstance(item, Sequence) and not isinstance(item, (str, bytes))
                    ):
                        _guard_nested_tenant(item, tenant, f"{field}.{name}[{index}]")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _guard_nested_tenant(item, tenant, f"{field}[{index}]")


def _resolve_tenant(
    org_id: Any = None,
    tenant_context: Mapping[str, Any] | None = None,
    actor_id: Any = None,
    trace_id: Any = None,
) -> tuple[str, str, str]:
    context = tenant_context if tenant_context is not None else {}
    if not isinstance(context, Mapping):
        raise GeoQueryFixtureError("INVALID_TENANT_CONTEXT", "tenant_context must be an object")
    markers = [value for value in (org_id, context.get("org_id"), context.get("tenant_id")) if value is not None]
    if not markers:
        raise GeoQueryFixtureError("INVALID_TENANT_CONTEXT", "org_id is required")
    tenant = _uuid(markers[0], "org_id")
    assert tenant is not None
    for marker in markers[1:]:
        if _uuid(marker, "org_id") != tenant:
            raise GeoQueryFixtureError("TENANT_SCOPE_VIOLATION", "tenant context markers disagree")
    actor = _actor(actor_id if actor_id is not None else context.get("actor_id", context.get("actor")))
    trace = trace_id if trace_id is not None else context.get("trace_id", "geo-content-002")
    trace = _text(trace, "trace_id", maximum=256)
    return tenant, actor, trace


def _safe_tenant(org_id: Any = None, tenant_context: Mapping[str, Any] | None = None) -> str:
    """Best-effort tenant extraction for rejection audit rows.

    Rejection handling must never mask the original validation error.  It does,
    however, still preserve a valid tenant supplied only through
    ``tenant_context`` so the audit row remains queryable by that tenant.
    """

    try:
        tenant, _, _ = _resolve_tenant(org_id, tenant_context)
        return tenant
    except Exception:
        candidates: list[Any] = [org_id]
        if isinstance(tenant_context, Mapping):
            candidates.extend([tenant_context.get("org_id"), tenant_context.get("tenant_id")])
        for candidate in candidates:
            if candidate is None:
                continue
            try:
                return str(UUID(str(candidate)))
            except (TypeError, ValueError, AttributeError):
                continue
        return "unknown"


def _policy_hash(policy_snapshot: Any) -> str | None:
    if policy_snapshot is None:
        return None
    if isinstance(policy_snapshot, str) and _HASH_RE.fullmatch(policy_snapshot.strip()):
        return policy_snapshot.strip().lower()
    return _hash(policy_snapshot)


def _if_match(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise GeoQueryFixtureError("VERSION_CONFLICT", "If-Match must be a version")
    raw = str(value).strip()
    if raw.startswith("W/"):
        raw = raw[2:].strip()
    raw = raw.strip('"')
    try:
        version = int(raw)
    except ValueError as exc:
        raise GeoQueryFixtureError("VERSION_CONFLICT", "If-Match must be an integer version") from exc
    if version < 1:
        raise GeoQueryFixtureError("VERSION_CONFLICT", "version must be positive")
    return version


def _predecessor_refs(value: Mapping[str, Any] | None) -> list[str]:
    if not value:
        return []
    refs: list[str] = []
    for key, item in value.items():
        values = item if isinstance(item, Sequence) and not isinstance(item, (str, bytes, Mapping)) else [item]
        for record in values:
            if isinstance(record, Mapping):
                ref = record.get("id", record.get("version_id", record.get("ref")))
                if ref is not None:
                    refs.append(_text(ref, f"predecessor_artifacts.{key}.id", maximum=256))
            elif record is not None:
                refs.append(_text(record, f"predecessor_artifacts.{key}", maximum=256))
    return sorted(set(refs))


def validate_predecessors(
    predecessor_artifacts: Mapping[str, Any] | None,
    *,
    org_id: str,
) -> None:
    """Validate tenant scope and explicit readiness signals from predecessors.

    Missing optional predecessor groups are accepted so a fixture can be built
    independently.  When a caller supplies a readiness/status marker, unsafe
    or failed states are deterministic hard failures; an explicit false
    ``ready``/``eligible`` marker is never silently ignored.
    """

    if predecessor_artifacts is None:
        return
    if not isinstance(predecessor_artifacts, Mapping):
        raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "predecessor_artifacts must be an object")
    _guard_nested_tenant(predecessor_artifacts, org_id)
    for name, value in predecessor_artifacts.items():
        records = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)) else [value]
        for record in records:
            if not isinstance(record, Mapping):
                continue
            status = record.get("status", record.get("state"))
            if isinstance(status, str) and status.strip().lower() in _BAD_PREDECESSOR_STATES:
                raise GeoQueryFixtureError(
                    "PREDECESSOR_NOT_READY",
                    f"predecessor {name} is in {status!r} state",
                    details={"predecessor": name, "status": status},
                )
            for marker in ("ready", "is_ready", "eligible_for_citation", "citation_ready"):
                if marker in record and record[marker] is False:
                    raise GeoQueryFixtureError(
                        "PREDECESSOR_NOT_READY",
                        f"predecessor {name} is not ready",
                        details={"predecessor": name, "marker": marker},
                    )
            if isinstance(status, str) and status.strip().lower() not in _READY_PREDECESSOR_STATES:
                raise GeoQueryFixtureError(
                    "PREDECESSOR_NOT_READY",
                    f"predecessor {name} has no approved readiness state",
                    details={"predecessor": name, "status": status},
                )
            if isinstance(status, str) and status.strip().lower() == "draft" and name.lower() in {
                "site_publication", "publication", "site_page", "site_page_version", "canonical", "canonical_content"
            }:
                raise GeoQueryFixtureError("PREDECESSOR_NOT_READY", f"predecessor {name} is still draft")


class InMemoryGeoQueryFixtureStore:
    """Thread-safe append-only command/event port used by the GEO-002 service."""

    def __init__(self) -> None:
        self.fixtures: dict[tuple[str, str], dict[str, Any]] = {}
        self.fixture_versions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    @staticmethod
    def _command_key(org_id: str, idempotency_key: str, namespace: str | None = None) -> tuple[str, str]:
        return (org_id, idempotency_key if namespace is None else f"{namespace}:{idempotency_key}")

    def get_command(self, *, org_id: str, idempotency_key: str, namespace: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            value = self.commands.get(self._command_key(org_id, idempotency_key, namespace))
            return deepcopy(value) if value is not None else None

    def save_command(self, *, org_id: str, idempotency_key: str, request_hash: str, response: Mapping[str, Any], namespace: str | None = None) -> None:
        with self._lock:
            key = self._command_key(org_id, idempotency_key, namespace)
            existing = self.commands.get(key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise GeoQueryFixtureError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return
            self.commands[key] = {"request_hash": request_hash, "response": deepcopy(dict(response))}

    def get_fixture(self, *, org_id: str, fixture_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self.fixtures.get((org_id, fixture_id))
            return deepcopy(value) if value is not None else None

    def find_fixture(self, *, fixture_id: str) -> dict[str, Any] | None:
        """Find an identity without exposing another tenant's row contents."""

        with self._lock:
            for (__, identity), value in self.fixtures.items():
                if identity == fixture_id:
                    return deepcopy(value)
        return None

    def has_fixture(self, *, fixture_id: str) -> bool:
        with self._lock:
            return any(identity == fixture_id for __, identity in self.fixtures)

    def find_by_hash(self, *, org_id: str, fixture_hash: str) -> dict[str, Any] | None:
        with self._lock:
            for (tenant, __), value in self.fixtures.items():
                if tenant == org_id and value.get("fixture_hash") == fixture_hash:
                    return deepcopy(value)
        return None

    def save_fixture(self, value: Mapping[str, Any]) -> None:
        row = deepcopy(dict(value))
        key = (str(row["org_id"]), str(row["id"]))
        with self._lock:
            self.fixtures[key] = row
            self.fixture_versions.setdefault(key, []).append(deepcopy(row))

    def list_fixtures(self, *, org_id: str, status: str | None = None) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = [deepcopy(row) for (tenant, _), row in self.fixtures.items() if tenant == org_id]
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        return tuple(sorted(rows, key=lambda row: (row.get("created_at", ""), row.get("id", ""))))

    def append_event(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            self.events.append(deepcopy(dict(event)))

    def append_audit(self, row: Mapping[str, Any]) -> None:
        with self._lock:
            self.audit.append(deepcopy(dict(row)))

    def audit_for(self, *, org_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(row) for row in self.audit if row.get("org_id") == org_id)


class GeoQueryFixtureService:
    """Create and transition tenant-scoped immutable GEO query fixtures."""

    task_id = "GEO_CONTENT-002"
    rule_version = "geo-content-002.v1"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        store: InMemoryGeoQueryFixtureStore | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = store or InMemoryGeoQueryFixtureStore()
        # Keep a direct alias for callers that used the GEO-001 service shape.
        self.audit = self.store.audit
        self._lock = RLock()

    def _audit(
        self,
        *,
        event_type: str,
        tenant: str,
        actor: str,
        trace: str,
        idempotency_key: str | None,
        aggregate_id: str | None,
        input_hash: str | None,
        output_hash: str | None,
        input_version: int | None,
        output_version: int | None,
        policy_hash: str | None,
        status: str,
        reason: str | None = None,
        duration_ms: int = 0,
        cost_cents: int = 0,
    ) -> dict[str, Any]:
        now = _stamp(self.clock())
        row = {
            "event_type": event_type,
            "task_id": self.task_id,
            "org_id": tenant,
            "actor_id": actor,
            "trace_id": trace,
            "idempotency_key": idempotency_key,
            "aggregate_id": aggregate_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "input_version": input_version,
            "output_version": output_version,
            "policy_snapshot_hash": policy_hash,
            "status": status,
            "reason": reason,
            "duration_ms": max(0, int(duration_ms)),
            "cost_cents": max(0, int(cost_cents)),
            "created_at": now,
        }
        self.store.append_audit(row)
        return row

    def _reject(self, error: GeoQueryFixtureError, *, org_id: Any, tenant_context: Mapping[str, Any] | None, actor_id: Any, trace_id: Any, idempotency_key: Any, input_hash: str | None = None) -> None:
        tenant = _safe_tenant(org_id, tenant_context)
        try:
            actor = _actor(actor_id)
        except GeoQueryFixtureError:
            actor = "unknown"
        try:
            trace = _text(trace_id or "geo-content-002", "trace_id", maximum=256)
        except GeoQueryFixtureError:
            trace = "geo-content-002"
        self._audit(
            event_type="geo.fixture.rejected",
            tenant=tenant,
            actor=actor,
            trace=trace,
            idempotency_key=str(idempotency_key) if idempotency_key is not None else None,
            aggregate_id=None,
            input_hash=input_hash,
            output_hash=None,
            input_version=None,
            output_version=None,
            policy_hash=None,
            status="rejected",
            reason=f"{error.code}: {error}",
        )

    def _command_replay(self, tenant: str, key: str, request_hash: str, *, namespace: str | None = None) -> dict[str, Any] | None:
        prior = self.store.get_command(org_id=tenant, idempotency_key=key, namespace=namespace)
        if prior is None:
            return None
        if prior.get("request_hash") != request_hash:
            raise GeoQueryFixtureError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
        return deepcopy(prior["response"])

    def _event(
        self,
        *,
        event_type: str,
        fixture: Mapping[str, Any],
        actor: str,
        trace: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        event_id = str(uuid4())
        payload_hash = _hash(payload)
        actor_uuid: str | None
        try:
            actor_uuid = str(UUID(actor))
            actor_type = "user"
        except (TypeError, ValueError):
            actor_uuid = None
            actor_type = "service"
        event = {
            "event_id": event_id,
            "event_type": event_type,
            "event_schema_version": 1,
            "occurred_at": _stamp(self.clock()),
            "org_id": fixture["org_id"],
            "trace_id": trace,
            "correlation_id": trace,
            "causation_id": None,
            "aggregate_type": "GeoQueryFixture",
            "aggregate_id": fixture["id"],
            "aggregate_version": fixture["version"],
            "actor_type": actor_type,
            "actor_id": actor_uuid,
            "idempotency_key": idempotency_key,
            "payload": dict(payload),
            "payload_hash": payload_hash,
        }
        self.store.append_event(event)
        return event

    def _normalize_fixture(
        self,
        *,
        tenant: str,
        actor: str,
        trace: str,
        query: Any,
        prompt: Any,
        locale: Any,
        region: Any,
        expected_entities: Any,
        expected_claim_ids: Any,
        predecessor_artifacts: Mapping[str, Any] | None,
        policy_snapshot: Any,
        fixture_id: Any,
        created_at: Any,
        metadata: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], str, str | None]:
        if query is None:
            query = prompt
        elif prompt is not None and _text(prompt, "prompt") != _text(query, "query"):
            raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "query and prompt disagree")
        query_text = _text(query, "query")
        locale_text = _text(locale, "locale", maximum=32)
        region_text = _text(region, "region", maximum=128)
        entities: list[str] = []
        for item in _sequence(expected_entities, "expected_entities"):
            value = _text(item, "expected_entities[]", maximum=512)
            if value not in entities:
                entities.append(value)
        claims = _refs(expected_claim_ids, "expected_claim_ids", uuid_only=True)
        if predecessor_artifacts is not None:
            validate_predecessors(predecessor_artifacts, org_id=tenant)
        if metadata is not None and not isinstance(metadata, Mapping):
            raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "metadata must be an object")
        created = _time(created_at, "created_at", default=self.clock())
        predecessor_hash = _hash(predecessor_artifacts or {}) if predecessor_artifacts else None
        identity_payload = _fixture_identity_payload(
            org_id=tenant,
            query=query_text,
            locale=locale_text,
            region=region_text,
            expected_entities=entities,
            expected_claim_ids=claims,
            predecessor_hash=predecessor_hash,
            metadata=metadata or {},
        )
        fixture_hash = _hash(identity_payload)
        if fixture_id is None:
            identity = str(uuid5(_UUID_NAMESPACE, f"{tenant}:{fixture_hash}"))
        else:
            identity = _uuid(fixture_id, "fixture_id")
            assert identity is not None
        policy_hash = _policy_hash(policy_snapshot)
        created_by: str | None
        try:
            created_by = str(UUID(actor))
        except (TypeError, ValueError):
            created_by = None
        row: dict[str, Any] = {
            "id": identity,
            "org_id": tenant,
            "query": query_text,
            "prompt": query_text,
            "locale": locale_text,
            "region": region_text,
            "expected_entities": entities,
            "expected_claim_ids": claims,
            "status": "created",
            "version": 1,
            "fixture_hash": fixture_hash,
            "prompt_hash": _hash(query_text),
            "predecessor_refs": _predecessor_refs(predecessor_artifacts),
            "predecessor_hash": predecessor_hash,
            "created_by": created_by,
            "created_at": _stamp(created),
            "updated_by": None,
            "updated_at": None,
            "trace_id": trace,
            "policy_snapshot_hash": policy_hash,
            "metadata": deepcopy(dict(metadata or {})),
        }
        validate_fixture_integrity(row, predecessor_artifacts=predecessor_artifacts)
        # Idempotency hashes describe the caller's business payload.  Dynamic
        # audit fields (clock, trace, and generated identity) must not make a
        # retry with the same key look like a different command.
        request_hash = _hash({
            "command": "create",
            "org_id": tenant,
            "query": query_text,
            "locale": locale_text,
            "region": region_text,
            "expected_entities": entities,
            "expected_claim_ids": claims,
            "predecessor_artifacts": deepcopy(predecessor_artifacts or {}),
            "policy_snapshot_hash": policy_hash,
            # Normalize UUID objects and textual UUID spellings before binding
            # the idempotency digest.
            "fixture_id": identity,
            "metadata": deepcopy(dict(metadata or {})),
        })
        return row, request_hash, policy_hash

    def create_fixture(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
        query: Any = None,
        prompt: Any = None,
        locale: Any = None,
        region: Any = None,
        expected_entities: Any = None,
        expected_claim_ids: Any = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        fixture_id: Any = None,
        created_at: Any = None,
        metadata: Mapping[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Create a deterministic fixture or replay an identical command."""

        self._lock.acquire()
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            row, request_hash, policy_hash = self._normalize_fixture(
                tenant=tenant,
                actor=actor,
                trace=trace,
                query=query,
                prompt=prompt,
                locale=locale,
                region=region,
                expected_entities=expected_entities,
                expected_claim_ids=expected_claim_ids,
                predecessor_artifacts=predecessor_artifacts,
                policy_snapshot=policy_snapshot,
                fixture_id=fixture_id,
                created_at=created_at,
                metadata=metadata,
            )
            replay = self._command_replay(tenant, key, request_hash, namespace=None)
            if replay is not None:
                return replay
            existing = self.store.get_fixture(org_id=tenant, fixture_id=row["id"])
            if existing is not None:
                if existing.get("fixture_hash") == row["fixture_hash"]:
                    raise GeoQueryFixtureError("DUPLICATE_FIXTURE", "fixture already exists")
                raise GeoQueryFixtureError("FIXTURE_ID_CONFLICT", "fixture id belongs to another payload")
            existing_identity = self.store.find_fixture(fixture_id=row["id"])
            if existing_identity is not None and existing_identity.get("org_id") != tenant:
                raise GeoQueryFixtureError("TENANT_SCOPE_VIOLATION", "fixture id belongs to another organization")
            existing_hash = self.store.find_by_hash(org_id=tenant, fixture_hash=row["fixture_hash"])
            if existing_hash is not None:
                raise GeoQueryFixtureError("DUPLICATE_FIXTURE", "fixture payload already exists")
            self.store.save_fixture(row)
            self.store.save_command(org_id=tenant, idempotency_key=key, request_hash=request_hash, response=row, namespace=None)
            # The checked-in event registry defines transition events for the
            # aggregate (activate/retire).  Creation remains an append-only
            # audit row until a future registry revision adds a creation event.
            self._audit(
                event_type="geo.fixture.created",
                tenant=tenant,
                actor=actor,
                trace=trace,
                idempotency_key=key,
                aggregate_id=row["id"],
                input_hash=request_hash,
                output_hash=_hash(row),
                input_version=None,
                output_version=1,
                policy_hash=policy_hash,
                status="created",
            )
            return deepcopy(row)
        except GeoQueryFixtureError as error:
            # Idempotency conflicts are themselves evidence; never swallow the
            # original machine-readable code.
            self._reject(error, org_id=org_id, tenant_context=tenant_context, actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key)
            raise
        finally:
            self._lock.release()

    # Common public aliases used by command adapters and hidden contract tests.
    create = create_fixture
    register = create_fixture
    create_query_fixture = create_fixture

    def get_fixture(self, *, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None, fixture_id: Any = None, **_: Any) -> dict[str, Any]:
        tenant, _, _ = _resolve_tenant(org_id, tenant_context)
        identity = _uuid(fixture_id, "fixture_id")
        assert identity is not None
        row = self.store.get_fixture(org_id=tenant, fixture_id=identity)
        if row is None:
            if self.store.has_fixture(fixture_id=identity):
                raise GeoQueryFixtureError("TENANT_SCOPE_VIOLATION", "fixture is outside this organization")
            raise GeoQueryFixtureError("FIXTURE_NOT_FOUND", "fixture does not belong to organization")
        return row

    get = get_fixture
    retrieve = get_fixture

    def list_fixtures(self, *, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None, status: str | None = None, **_: Any) -> tuple[dict[str, Any], ...]:
        tenant, _, _ = _resolve_tenant(org_id, tenant_context)
        if status is not None and status not in _STATES:
            raise GeoQueryFixtureError("INVALID_GEO_QUERY_FIXTURE", "unknown fixture status")
        return self.store.list_fixtures(org_id=tenant, status=status)

    list = list_fixtures

    def _transition(
        self,
        *,
        action: str,
        fixture_id: Any,
        org_id: Any,
        tenant_context: Mapping[str, Any] | None,
        actor_id: Any,
        trace_id: Any,
        idempotency_key: Any,
        expected_version: Any,
        if_match: Any,
        reason: Any,
        policy_snapshot: Any,
    ) -> dict[str, Any]:
        self._lock.acquire()
        try:
            tenant, actor, trace = _resolve_tenant(org_id, tenant_context, actor_id, trace_id)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            identity = _uuid(fixture_id, "fixture_id")
            assert identity is not None
            current = self.store.get_fixture(org_id=tenant, fixture_id=identity)
            if current is None:
                if self.store.has_fixture(fixture_id=identity):
                    raise GeoQueryFixtureError("TENANT_SCOPE_VIOLATION", "fixture is outside this organization")
                raise GeoQueryFixtureError("FIXTURE_NOT_FOUND", "fixture does not belong to organization")
            supplied_version = expected_version if expected_version is not None else if_match
            version = _if_match(supplied_version)
            if expected_version is not None and if_match is not None:
                expected = _if_match(expected_version)
                header = _if_match(if_match)
                if expected != header:
                    raise GeoQueryFixtureError("VERSION_CONFLICT", "expected_version and If-Match disagree")
            if version is None:
                raise GeoQueryFixtureError("VERSION_CONFLICT", "expected_version or If-Match is required")
            target = {"activate": "active", "retire": "retired"}.get(action)
            if target is None:
                raise GeoQueryFixtureError("INVALID_STATE_TRANSITION", f"unknown action {action}")
            normalized_reason = (
                _text(reason, "reason", maximum=1024, required=False) or None
                if reason is not None else None
            )
            policy_hash = _policy_hash(policy_snapshot)
            request_hash = _hash({
                "command": action,
                "fixture_id": identity,
                "expected_version": version,
                "reason": normalized_reason,
                "policy_snapshot_hash": policy_hash,
            })
            replay = self._command_replay(tenant, key, request_hash, namespace="transition")
            if replay is not None:
                return replay
            if current["version"] != version:
                raise GeoQueryFixtureError("VERSION_CONFLICT", "fixture version changed")
            allowed = {"activate": ("created",), "retire": ("active",)}[action]
            if current["status"] not in allowed:
                raise GeoQueryFixtureError("INVALID_STATE_TRANSITION", f"cannot {action} fixture from {current['status']}")
            if action == "retire" and normalized_reason is None:
                raise GeoQueryFixtureError("REASON_REQUIRED", "retiring a fixture requires a replacement or invalidation reason")
            if action == "activate" and not (current.get("expected_entities") or current.get("expected_claim_ids")):
                raise GeoQueryFixtureError(
                    "FIXTURE_INCOMPLETE",
                    "fixture activation requires at least one expected entity or claim",
                )
            now = _stamp(self.clock())
            updated_by: str | None
            try:
                updated_by = str(UUID(actor))
            except (TypeError, ValueError):
                updated_by = None
            next_row = deepcopy(current)
            next_row.update({
                "status": target,
                "version": current["version"] + 1,
                "updated_by": updated_by,
                "updated_at": now,
                "trace_id": trace,
                "policy_snapshot_hash": policy_hash if policy_hash is not None else current.get("policy_snapshot_hash"),
            })
            self.store.save_fixture(next_row)
            self.store.save_command(org_id=tenant, idempotency_key=key, request_hash=request_hash, response=next_row, namespace="transition")
            event_type = "geo.fixture.activated" if action == "activate" else "geo.fixture.retired"
            self._event(
                event_type=event_type,
                fixture=next_row,
                actor=actor,
                trace=trace,
                idempotency_key=key,
                payload={
                    "from_state": current["status"],
                    "to_state": target,
                    "command": action,
                    "aggregate_version": next_row["version"],
                    "snapshot_hash": next_row["fixture_hash"],
                    "reason": normalized_reason,
                },
            )
            self._audit(
                event_type=event_type,
                tenant=tenant,
                actor=actor,
                trace=trace,
                idempotency_key=key,
                aggregate_id=identity,
                input_hash=request_hash,
                output_hash=_hash(next_row),
                input_version=current["version"],
                output_version=next_row["version"],
                policy_hash=next_row.get("policy_snapshot_hash"),
                status=target,
                reason=normalized_reason,
            )
            return deepcopy(next_row)
        except GeoQueryFixtureError as error:
            self._reject(error, org_id=org_id, tenant_context=tenant_context, actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key)
            raise
        finally:
            self._lock.release()

    def activate_fixture(self, *, fixture_id: Any, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None, actor_id: Any = None, trace_id: Any = None, idempotency_key: Any = None, expected_version: Any = None, if_match: Any = None, reason: Any = None, policy_snapshot: Any = None, **_: Any) -> dict[str, Any]:
        return self._transition(action="activate", fixture_id=fixture_id, org_id=org_id, tenant_context=tenant_context, actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key, expected_version=expected_version, if_match=if_match, reason=reason, policy_snapshot=policy_snapshot)

    def retire_fixture(self, *, fixture_id: Any, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None, actor_id: Any = None, trace_id: Any = None, idempotency_key: Any = None, expected_version: Any = None, if_match: Any = None, reason: Any = None, policy_snapshot: Any = None, **_: Any) -> dict[str, Any]:
        return self._transition(action="retire", fixture_id=fixture_id, org_id=org_id, tenant_context=tenant_context, actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key, expected_version=expected_version, if_match=if_match, reason=reason, policy_snapshot=policy_snapshot)

    activate = activate_fixture
    retire = retire_fixture

    def transition(self, *, action: str, fixture_id: Any = None, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None, actor_id: Any = None, trace_id: Any = None, idempotency_key: Any = None, expected_version: Any = None, if_match: Any = None, reason: Any = None, policy_snapshot: Any = None, **kwargs: Any) -> dict[str, Any]:
        if action not in {"activate", "retire"}:
            error = GeoQueryFixtureError("INVALID_STATE_TRANSITION", f"unknown action {action}")
            self._reject(
                error,
                org_id=org_id,
                tenant_context=tenant_context,
                actor_id=actor_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            )
            raise error
        return self._transition(action=action, fixture_id=fixture_id, org_id=org_id, tenant_context=tenant_context, actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key, expected_version=expected_version, if_match=if_match, reason=reason, policy_snapshot=policy_snapshot, **kwargs)

    def audit_for(self, *, org_id: Any = None, tenant_context: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], ...]:
        tenant, _, _ = _resolve_tenant(org_id, tenant_context)
        return self.store.audit_for(org_id=tenant)


# Compatibility names for callers that use the aggregate rather than the task
# name.  They intentionally point at the same implementation.
GeoFixtureService = GeoQueryFixtureService
QueryFixtureService = GeoQueryFixtureService
GeoQueryFixtureStore = InMemoryGeoQueryFixtureStore
GeoFixtureError = GeoQueryFixtureError


__all__ = [
    "GeoQueryFixtureError",
    "GeoFixtureError",
    "InMemoryGeoQueryFixtureStore",
    "GeoQueryFixtureStore",
    "GeoQueryFixtureService",
    "GeoFixtureService",
    "QueryFixtureService",
    "validate_fixture_integrity",
    "validate_predecessors",
]
