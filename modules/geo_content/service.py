"""Offline GEO content readiness checks for GEO_CONTENT-001.

The service consumes already validated predecessor snapshots and produces a
deterministic assessment.  It does not read application tables, call a
network, or claim that a page will rank in a search engine.  The five checks
are deliberately small and composable:

* entity consistency;
* Claim -> Evidence -> SourceSnapshot/RightsRecordVersion traceability;
* citation readiness;
* freshness and validity windows; and
* crawlability of a first-party page snapshot.

All input records are tenant checked before their fields are inspected.  The
in-memory store is an application port used by tests and offline workers;
production composition may replace it with a repository without changing the
rule engine.
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
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads(
    (_ROOT / "packages/contracts/jsonschema/geo-content-assessment.schema.json")
    .read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())
_HASH_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_PATH_BAD = re.compile(r"(?:^|/)\.\.?(?:/|$)")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_ENCODED_PATH_SEPARATOR = re.compile(r"%(?:2f|5c)", re.IGNORECASE)
_RULE_VERSION = "geo-content-001.v1"
_AUDIT_ACTOR_FALLBACK = "00000000-0000-4000-8000-000000000000"
_DIMENSIONS = (
    "entity_consistency",
    "claim_traceability",
    "citation_readiness",
    "freshness",
    "crawlability",
)
_PASSABLE_PAGE_STATES = frozenset({"ready", "published"})
_FRESH_STATES = frozenset({"fresh", "usable", "active", "valid", "verified", "published", "ready"})
_REVIEW_STATES = frozenset({"review_due", "captured", "quarantined", "pending", "draft"})
_BAD_STATES = frozenset({
    "stale", "expired", "withdrawn", "revoked", "blocked", "conflict", "superseded",
    "retired", "complaint_hold", "unusable", "invalid",
})
_KNOWN_ENTITY_STATES = frozenset({"draft", "active", "retired"})
_KNOWN_CLAIM_STATES = frozenset({"draft", "verified", "withdrawn"})
_KNOWN_CLAIM_FRESHNESS = frozenset({"fresh", "review_due", "stale", "withdrawn"})
_KNOWN_EVIDENCE_STATES = frozenset({"captured", "valid", "expired", "revoked"})
_KNOWN_SOURCE_STATES = frozenset({"captured", "quarantined", "usable", "expired", "revoked", "blocked"})
_KNOWN_RIGHTS_STATES = frozenset({"pending", "verified", "expired", "revoked", "complaint_hold"})


class GeoContentError(ValueError):
    """Stable error code returned by GEO content commands."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class InMemoryGeoContentStore:
    """Idempotency and audit port for deterministic local assessments."""

    def __init__(self) -> None:
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.assessments: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def get_command(self, *, org_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self.commands.get((org_id, idempotency_key))
            return None if value is None else deepcopy(value)

    def save_command(
        self, *, org_id: str, idempotency_key: str, request_hash: str,
        response: Mapping[str, Any],
    ) -> None:
        with self._lock:
            key = (org_id, idempotency_key)
            if key in self.commands:
                raise GeoContentError("IDEMPOTENCY_KEY_REUSED", "assessment idempotency key already exists")
            snapshot = deepcopy(dict(response))
            self.commands[key] = {"request_hash": request_hash, "response": snapshot}
            self.assessments[(org_id, str(snapshot["assessment_id"]))] = snapshot

    def append_audit(self, row: Mapping[str, Any]) -> None:
        with self._lock:
            self.audit.append(deepcopy(dict(row)))

    def audit_for(self, *, org_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            return tuple(deepcopy(row) for row in self.audit if row.get("org_id") == org_id)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", "input must be JSON serializable") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, maximum: int = 4096, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} must be non-empty")
    if len(result) > maximum:
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} exceeds {maximum} characters")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} contains a control character")
    return result


def _uuid(value: Any, field: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GeoContentError("INVALID_TENANT_CONTEXT", f"{field} must be a UUID") from exc


def _ref(value: Any, field: str) -> str:
    """Normalize predecessor identifiers while accepting deterministic fixtures."""

    if isinstance(value, UUID):
        return str(value)
    result = _text(value, field, maximum=256)
    if any(char.isspace() for char in result):
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} cannot contain whitespace")
    return result


def _time(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} must be ISO-8601") from exc
    elif default is not None:
        parsed = default
    else:
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", "record collection must be an array")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise GeoContentError("INVALID_GEO_CONTENT_INPUT", "record collection contains a non-object")
        result.append(dict(item))
    return result


def _sequence_values(value: Any, field: str) -> list[Any]:
    """Return an explicitly supplied array without silently coercing scalars."""

    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} must be an array")
    return list(value)


def _first_mapping(source: Mapping[str, Any], names: Iterable[str]) -> dict[str, Any] | None:
    for name in names:
        value = source.get(name)
        if isinstance(value, Mapping):
            return dict(value)
    return None


def _optional_mapping(value: Any, field: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field} must be an object")
    return value


def _collection(source: Mapping[str, Any], names: Iterable[str]) -> list[dict[str, Any]]:
    for name in names:
        if name in source and source[name] is not None:
            return _records(source[name])
    return []


def _tenant_guard(record: Mapping[str, Any], tenant: str, field: str) -> None:
    markers = [record[name] for name in ("org_id", "tenant_id") if name in record]
    if not markers:
        raise GeoContentError("TENANT_SCOPE_VIOLATION", f"{field} has no tenant scope")
    for marker in markers:
        if marker is None or _uuid(marker, f"{field}.org_id") != tenant:
            raise GeoContentError("TENANT_SCOPE_VIOLATION", f"{field} is outside this organization")


def _guard_nested_tenant(value: Any, tenant: str, field: str) -> None:
    """Reject a tenant marker embedded in an opaque predecessor snapshot."""
    if isinstance(value, Mapping):
        markers = [value[name] for name in ("org_id", "tenant_id") if name in value]
        for marker in markers:
            if marker is None or _uuid(marker, f"{field}.org_id") != tenant:
                raise GeoContentError("TENANT_SCOPE_VIOLATION", f"{field} is outside this organization")
        for name, child in value.items():
            if isinstance(child, Mapping):
                _guard_nested_tenant(child, tenant, f"{field}.{name}")
            elif isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                for index, item in enumerate(child):
                    if isinstance(item, Mapping):
                        _guard_nested_tenant(item, tenant, f"{field}.{name}[{index}]")


def _status(value: Any, field: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    return _text(value, field, maximum=64).lower()


def _finding(
    dimension: str, code: str, severity: str, *, subject_ref: str | None = None,
    related_refs: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "code": code,
        "severity": severity,
        "subject_ref": subject_ref,
        "related_refs": sorted({_ref(ref, "related_ref") for ref in related_refs if ref is not None}),
    }


def _missing_fields(row: Mapping[str, Any], fields: Iterable[str]) -> list[str]:
    return sorted(field for field in fields if row.get(field) is None or (isinstance(row.get(field), str) and not row.get(field).strip()))


def _dimension(name: str, findings: list[dict[str, Any]], checked: int) -> dict[str, Any]:
    if any(item["severity"] == "error" for item in findings):
        state = "fail"
    elif any(item["severity"] == "warning" for item in findings):
        state = "review"
    else:
        state = "pass"
    return {"status": state, "checked": max(0, checked), "finding_codes": sorted({item["code"] for item in findings})}


def _page_body(page: Mapping[str, Any]) -> str:
    rows: list[str] = []
    visible = page.get("visible_content")
    if isinstance(visible, Mapping):
        blocks = visible.get("blocks", [])
        for block in _records(blocks):
            text = block.get("text", block.get("content"))
            if text is not None:
                rows.append(_text(text, "visible_content.blocks.text", maximum=20000))
    elif isinstance(visible, str):
        rows.append(_text(visible, "visible_content", maximum=20000))
    methodology = page.get("methodology")
    steps = methodology.get("steps", []) if isinstance(methodology, Mapping) else methodology
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
        rows.extend(_text(value, "methodology.steps[]", maximum=2000) for value in steps)
    limitations = page.get("limitations", [])
    if isinstance(limitations, Sequence) and not isinstance(limitations, (str, bytes)):
        for value in limitations:
            rows.append(_text(value.get("text", value.get("description", "")) if isinstance(value, Mapping) else value, "limitations[]", maximum=2000))
    faq = page.get("faq", [])
    if isinstance(faq, Sequence) and not isinstance(faq, (str, bytes)):
        for value in faq:
            if isinstance(value, Mapping):
                rows.append(_text(value.get("question"), "faq.question", maximum=1000))
                rows.append(_text(value.get("answer"), "faq.answer", maximum=10000))
    return "\n\n".join(row for row in rows if row)


def _entity_name_visible(name: str, visible_text: str) -> bool:
    """Match an entity name without accepting it as a substring of a word."""

    if not name:
        return False
    pattern = re.escape(name)
    if name[0].isalnum():
        pattern = r"(?<!\w)" + pattern
    if name[-1].isalnum():
        pattern += r"(?!\w)"
    return re.search(pattern, visible_text) is not None


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("origin") from exc
    if (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        port = None
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def _clean_path(path: str) -> str:
    """Validate a URL path before it is used as a crawlability fact.

    Encoded separators and dot segments are rejected as well as their literal
    forms.  Treating both representations identically prevents two spellings
    of one URL from bypassing the canonical path check.
    """

    if not path or _BAD_PERCENT.search(path) or _ENCODED_PATH_SEPARATOR.search(path):
        raise ValueError("path")
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("path") from exc
    for candidate in (path, decoded):
        if "\\" in candidate or "//" in candidate or _PATH_BAD.search(candidate):
            raise ValueError("path")
        if any(ord(char) < 0x21 or ord(char) == 0x7F for char in candidate):
            raise ValueError("path")
    return path[:-1] if path != "/" and path.endswith("/") else path


def _canonical_url(page: Mapping[str, Any]) -> str:
    raw = page.get("canonical_url", page.get("url_path"))
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("canonical")
    raw = raw.strip()
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or _BAD_PERCENT.search(parsed.netloc) or any(ord(char) < 0x21 or ord(char) == 0x7F for char in parsed.netloc):
            raise ValueError("canonical")
        origin = _origin(f"{parsed.scheme}://{parsed.netloc}")
        path = _clean_path(parsed.path or "/")
        return origin + path
    if not raw.startswith("/") or "?" in raw or "#" in raw:
        raise ValueError("canonical")
    path = _clean_path(raw)
    # SITE-001 paths are relative; callers may provide base_origin separately.
    origin = _declared_origin(page)
    if not isinstance(origin, str):
        return path
    return _origin(origin) + path


def _declared_origin(record: Mapping[str, Any]) -> Any:
    """Return the first non-null origin declaration in precedence order."""

    for name in ("base_origin", "site_origin", "origin"):
        if name in record and record[name] is not None:
            return record[name]
    return None


class GeoContentRuleService:
    """Evaluate GEO content readiness without external side effects."""

    rule_version = _RULE_VERSION

    def __init__(
        self, *, clock: Callable[[], datetime] | None = None,
        store: InMemoryGeoContentStore | None = None,
    ) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = store or InMemoryGeoContentStore()
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def _record_rejection(
        self, *, tenant: str, actor: str, trace: str, error: GeoContentError,
        input_version_ids: Iterable[str] = (), input_hash: str | None = None,
        policy_snapshot_hash: str | None = None, assessed_at: str | None = None,
        finding_codes: Iterable[str] = (),
    ) -> None:
        row = {
            "event_type": "geo_content.assessment.rejected", "org_id": tenant, "actor_id": actor,
            "trace_id": trace, "error_code": error.code,
            "input_version_ids": sorted(set(input_version_ids)),
            "rule_version": self.rule_version, "status": "rejected",
            "reason": str(error), "input_hash": input_hash, "output_hash": None,
            "policy_snapshot_hash": policy_snapshot_hash, "finding_codes": sorted(set(finding_codes)),
            "assessed_at": assessed_at, "duration_ms": 0,
        }
        with self._lock:
            self.audit.append(deepcopy(row))
            self.store.append_audit(row)

    def assess(
        self, *, org_id: UUID | str, actor_id: UUID | str, trace_id: str,
        idempotency_key: str, page: Mapping[str, Any] | None = None,
        site_page_version: Mapping[str, Any] | None = None,
        canonical: Mapping[str, Any] | None = None,
        entities: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        claims: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        evidences: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        source_snapshots: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        sources: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        rights_record_versions: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        rights: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        assessed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        try:
            tenant = _uuid(org_id, "org_id")
        except GeoContentError as exc:
            # There is no valid tenant key to scope this rejection to, but the
            # failed request still needs an audit trail.  Keep the raw value
            # bounded and avoid interpreting it as a tenant in later reads.
            try:
                invalid_tenant = str(org_id)[:256]
            except Exception:  # pragma: no cover - defensive for hostile objects
                invalid_tenant = "<invalid>"
            self._record_rejection(
                tenant=invalid_tenant, actor=_AUDIT_ACTOR_FALLBACK,
                trace="<invalid>", error=exc,
            )
            raise
        actor = _AUDIT_ACTOR_FALLBACK
        trace = "<invalid>"
        try:
            actor = _uuid(actor_id, "actor_id")
            trace = _text(trace_id, "trace_id", maximum=256)
            key = _text(idempotency_key, "idempotency_key", maximum=200)
            if len(key) < 2:
                raise GeoContentError("INVALID_GEO_CONTENT_INPUT", "idempotency_key must contain at least 2 characters")
        except GeoContentError as exc:
            self._record_rejection(tenant=tenant, actor=actor, trace=trace, error=exc)
            raise
        source_ids: list[str] = []
        request_hash: str | None = None
        policy_hash: str | None = None
        checked_at: datetime | None = None
        try:
            if predecessor_artifacts is not None and not isinstance(predecessor_artifacts, Mapping):
                raise GeoContentError("INVALID_GEO_CONTENT_INPUT", "predecessor_artifacts must be an object")
            source = dict(predecessor_artifacts or {})
            if "source" in source:
                raise GeoContentError(
                    "UNSUPPORTED_GEO_CONTENT_ALIAS",
                    "predecessor_artifacts.source is unsupported; provide sources[] and source_snapshot_id links",
                )
            page_value = page if page is not None else site_page_version if site_page_version is not None else _first_mapping(source, ("page", "page_version", "site_page_version"))
            canonical_value = canonical if canonical is not None else _first_mapping(source, ("canonical", "canonical_content_version", "canonical_version"))
            page_value = _optional_mapping(page_value, "page")
            canonical_value = _optional_mapping(canonical_value, "canonical")
            for field, value in (("page", page_value), ("canonical", canonical_value)):
                if value is not None and value.get("id") is None:
                    raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{field}.id is required")
            if policy_snapshot is None:
                policy_snapshot = source.get("policy_snapshot", source.get("policy"))
            if policy_snapshot is not None and not isinstance(policy_snapshot, Mapping):
                raise GeoContentError("INVALID_GEO_CONTENT_INPUT", "policy_snapshot must be an object")
            entity_rows = _records(entities) if entities is not None else _collection(source, ("entities", "entity"))
            claim_rows = _records(claims) if claims is not None else _collection(source, ("claims", "claim"))
            evidence_rows = _records(evidences) if evidences is not None else _collection(source, ("evidences", "evidence"))
            snapshot_rows = _records(source_snapshots) if source_snapshots is not None else _collection(source, ("source_snapshots", "snapshots", "source_snapshot"))
            source_rows = _records(sources) if sources is not None else _collection(source, ("sources",))
            rights_rows = _records(rights_record_versions) if rights_record_versions is not None else _collection(source, ("rights_record_versions", "rights_versions"))
            if rights is not None:
                rights_rows.extend(_records(rights))
            elif not rights_rows:
                rights_rows = _collection(source, ("rights",))

            records = {
                "page": deepcopy(page_value) if isinstance(page_value, Mapping) else None,
                "canonical": deepcopy(canonical_value) if isinstance(canonical_value, Mapping) else None,
                "entities": deepcopy(entity_rows), "claims": deepcopy(claim_rows),
                "evidences": deepcopy(evidence_rows), "source_snapshots": deepcopy(snapshot_rows),
                "sources": deepcopy(source_rows),
                "rights_record_versions": deepcopy(rights_rows),
                "policy_snapshot": policy_snapshot,
                "rule_version": self.rule_version,
            }
            checked_at = _time(assessed_at, "assessed_at", default=_time(self.clock(), "clock"))
            records["assessed_at"] = _stamp(checked_at)
            policy_hash = None if policy_snapshot is None else _hash(policy_snapshot)
            _guard_nested_tenant(source, tenant, "predecessor_artifacts")
            _guard_nested_tenant(policy_snapshot, tenant, "policy_snapshot")
            request_hash = _hash(records)
            prior = self.store.get_command(org_id=tenant, idempotency_key=key)
            if prior is not None:
                if prior.get("request_hash") != request_hash:
                    raise GeoContentError("IDEMPOTENCY_KEY_REUSED", "assessment payload differs from prior request")
                return deepcopy(dict(prior["response"]))
        except GeoContentError as exc:
            self._record_rejection(
                tenant=tenant, actor=actor, trace=trace, error=exc, input_version_ids=source_ids,
                input_hash=request_hash, policy_snapshot_hash=policy_hash,
                assessed_at=None if checked_at is None else _stamp(checked_at),
            )
            raise
        try:
            for field, rows in (("page", [records["page"]] if records["page"] else []), ("canonical", [records["canonical"]] if records["canonical"] else []),
                                ("entity", records["entities"]), ("claim", records["claims"]), ("evidence", records["evidences"]),
                                ("source_snapshot", records["source_snapshots"]), ("source", records["sources"]),
                                ("rights_record_version", records["rights_record_versions"])):
                for row in rows:
                    _tenant_guard(row, tenant, field)
                    _guard_nested_tenant(row, tenant, field)
                    if row.get("id") is not None:
                        source_ids.append(_ref(row["id"], f"{field}.id"))
            dimensions, findings = self._evaluate(
                tenant=tenant, page=records["page"], canonical=records["canonical"],
                entities=records["entities"], claims=records["claims"], evidences=records["evidences"],
                snapshots=records["source_snapshots"], sources=records["sources"], rights=records["rights_record_versions"],
                now=checked_at,
            )
            findings = sorted(findings, key=lambda item: (item["dimension"], item["code"], item.get("subject_ref") or "", tuple(item["related_refs"])))
            state_values = [dimensions[name]["status"] for name in _DIMENSIONS]
            status = "fail" if "fail" in state_values else "review" if "review" in state_values else "pass"
            score = round(sum(1.0 if value == "pass" else 0.5 if value == "review" else 0.0 for value in state_values) / len(state_values), 4)
            assessment_id = str(uuid5(NAMESPACE_URL, f"geo-content:{tenant}:{request_hash}"))
            result: dict[str, Any] = {
                "schema_version": "geo-content-001.v1", "assessment_id": assessment_id,
                "org_id": tenant, "actor_id": actor, "trace_id": trace, "idempotency_key": key,
                "rule_version": self.rule_version, "assessed_at": _stamp(checked_at),
                "status": status, "score": score, "dimensions": dimensions, "findings": findings,
                "input_hash": request_hash, "policy_snapshot_hash": policy_hash,
                "eligible_for_crawl": dimensions["crawlability"]["status"] == "pass" and status != "fail",
                "eligible_for_citation": (
                    dimensions["citation_readiness"]["status"] == "pass"
                    and dimensions["claim_traceability"]["status"] == "pass"
                    and dimensions["freshness"]["status"] == "pass"
                    and dimensions["entity_consistency"]["status"] == "pass"
                    and dimensions["crawlability"]["status"] == "pass"
                ),
                "source_refs": sorted(set(source_ids)),
            }
            # Hash the deterministic assessment payload.  The digest excludes
            # its own field and the audit envelope, which carries the digest
            # and therefore cannot be part of the input without a cycle.
            result["output_hash"] = _hash(result)
            audit = {
                "event_type": "geo_content.assessed", "org_id": tenant, "actor_id": actor,
                "trace_id": trace, "assessment_id": assessment_id, "rule_version": self.rule_version,
                "input_hash": request_hash, "output_hash": result["output_hash"], "status": status,
                "finding_count": len(findings), "policy_snapshot_hash": policy_hash,
                "assessed_at": result["assessed_at"], "duration_ms": 0,
            }
            result["audit_evidence"] = audit
            errors = sorted(_VALIDATOR.iter_errors(result), key=lambda error: list(error.path))
            if errors:
                raise GeoContentError("INVALID_GEO_CONTENT_OUTPUT", errors[0].message)
            with self._lock:
                self.audit.append(deepcopy(audit))
                self.store.append_audit(audit)
                self.store.save_command(org_id=tenant, idempotency_key=key, request_hash=request_hash, response=result)
            return deepcopy(result)
        except GeoContentError as exc:
            self._record_rejection(
                tenant=tenant, actor=actor, trace=trace, error=exc, input_version_ids=source_ids,
                input_hash=request_hash, policy_snapshot_hash=policy_hash,
                assessed_at=None if checked_at is None else _stamp(checked_at),
            )
            raise

    evaluate = assess
    check = assess
    run = assess

    def _evaluate(
        self, *, tenant: str, page: Mapping[str, Any] | None, canonical: Mapping[str, Any] | None,
        entities: Sequence[Mapping[str, Any]], claims: Sequence[Mapping[str, Any]],
        evidences: Sequence[Mapping[str, Any]], snapshots: Sequence[Mapping[str, Any]],
        sources: Sequence[Mapping[str, Any]],
        rights: Sequence[Mapping[str, Any]], now: datetime,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        entity_findings: list[dict[str, Any]] = []
        claim_findings: list[dict[str, Any]] = []
        citation_findings: list[dict[str, Any]] = []
        freshness_findings: list[dict[str, Any]] = []
        crawl_findings: list[dict[str, Any]] = []
        page_scope = {
            "locale": page.get("locale") if page is not None else None,
            "region": (page.get("region") or page.get("region_profile_version_id")) if page is not None else None,
            "version": (page.get("version") or page.get("canonical_content_version_id")) if page is not None else None,
        }
        if not entities:
            entity_findings.append(_finding("entity_consistency", "ENTITY_INPUT_MISSING", "warning"))
        entity_map: dict[str, Mapping[str, Any]] = {}
        canonical_names: dict[str, str] = {}
        for entity in entities:
            identity = _ref(entity.get("id"), "entity.id") if entity.get("id") is not None else None
            if identity is None:
                entity_findings.append(_finding("entity_consistency", "ENTITY_ID_MISSING", "error"))
                continue
            name = entity.get("canonical_name", entity.get("name"))
            if not isinstance(name, str) or not name.strip():
                entity_findings.append(_finding("entity_consistency", "ENTITY_NAME_MISSING", "error", subject_ref=identity))
                continue
            if identity in entity_map and _canonical(entity_map[identity]) != _canonical(entity):
                entity_findings.append(_finding("entity_consistency", "ENTITY_DUPLICATE", "error", subject_ref=identity))
                continue
            entity_map[identity] = entity
            key = " ".join(name.casefold().split())
            previous = canonical_names.get(key)
            if previous is not None and previous != identity:
                entity_findings.append(_finding("entity_consistency", "ENTITY_CANONICAL_CONFLICT", "error", subject_ref=identity, related_refs=(previous,)))
            canonical_names[key] = identity
            raw_state = entity.get("status")
            if raw_state is None:
                entity_findings.append(_finding("entity_consistency", "ENTITY_STATUS_MISSING", "warning", subject_ref=identity))
                state = "draft"
            else:
                state = _status(raw_state, "entity.status")
                if state not in _KNOWN_ENTITY_STATES:
                    entity_findings.append(_finding("entity_consistency", "ENTITY_STATUS_UNKNOWN", "warning", subject_ref=identity))
            if state in _BAD_STATES:
                entity_findings.append(_finding("entity_consistency", "ENTITY_NOT_ACTIVE", "error", subject_ref=identity))
            elif state in _REVIEW_STATES:
                entity_findings.append(_finding("entity_consistency", "ENTITY_REVIEW_REQUIRED", "warning", subject_ref=identity))

        expected_entities: list[str] = []
        if page is not None:
            if "entity_ids" not in page:
                entity_findings.append(_finding("entity_consistency", "ENTITY_DECLARATION_MISSING", "warning"))
                declared_entities = []
            else:
                raw_declared_entities = page.get("entity_ids")
                if raw_declared_entities is None:
                    entity_findings.append(_finding("entity_consistency", "ENTITY_DECLARATION_INVALID", "error"))
                    declared_entities = []
                else:
                    declared_entities = _sequence_values(raw_declared_entities, "page.entity_ids")
                    if not declared_entities:
                        entity_findings.append(_finding("entity_consistency", "ENTITY_DECLARATION_EMPTY", "warning"))
            for value in declared_entities:
                if value is None:
                    entity_findings.append(_finding("entity_consistency", "ENTITY_DECLARATION_INVALID", "error"))
                    continue
                expected_entities.append(_ref(value, "page.entity_ids[]"))
            if expected_entities:
                try:
                    visible_text = _page_body(page).casefold()
                except GeoContentError:
                    visible_text = ""
                for entity_id in expected_entities:
                    entity = entity_map.get(entity_id)
                    aliases = []
                    if entity is not None and "aliases" in entity:
                        aliases = _sequence_values(entity.get("aliases"), "entity.aliases")
                    names = [] if entity is None else [entity.get("canonical_name", entity.get("name")), *aliases]
                    names = [str(name).strip().casefold() for name in names if isinstance(name, str) and name.strip()]
                    visible = any(_entity_name_visible(name, visible_text) for name in names)
                    if entity is not None and names and not visible:
                        entity_findings.append(_finding("entity_consistency", "ENTITY_NOT_VISIBLE", "warning", subject_ref=entity_id))
        for claim in claims:
            entity_ids = _sequence_values(claim.get("entity_ids"), "claim.entity_ids") if "entity_ids" in claim else []
            for value in entity_ids:
                identity = _ref(value, "claim.entity_ids[]")
                if identity not in entity_map:
                    claim_findings.append(_finding("claim_traceability", "ENTITY_UNRESOLVED", "error", subject_ref=_ref(claim.get("id"), "claim.id"), related_refs=(identity,)))
        for expected in expected_entities:
            if expected not in entity_map:
                entity_findings.append(_finding("entity_consistency", "PAGE_ENTITY_UNRESOLVED", "error", related_refs=(expected,)))

        claim_map: dict[str, Mapping[str, Any]] = {}
        for claim in claims:
            identity = _ref(claim.get("id"), "claim.id") if claim.get("id") is not None else None
            if identity is None:
                claim_findings.append(_finding("claim_traceability", "CLAIM_ID_MISSING", "error"))
                continue
            if identity in claim_map:
                claim_findings.append(_finding("claim_traceability", "CLAIM_DUPLICATE", "error", subject_ref=identity))
                continue
            claim_map[identity] = claim
            if claim.get("status") is None:
                claim_findings.append(_finding("claim_traceability", "CLAIM_STATUS_MISSING", "warning", subject_ref=identity))
                state = "draft"
            else:
                state = _status(claim.get("status"), "claim.status")
                if state not in _KNOWN_CLAIM_STATES:
                    claim_findings.append(_finding("claim_traceability", "CLAIM_STATUS_UNKNOWN", "warning", subject_ref=identity))
            if claim.get("freshness_status") is None:
                freshness_findings.append(_finding("freshness", "CLAIM_FRESHNESS_MISSING", "warning", subject_ref=identity))
                freshness = "review_due"
            else:
                freshness = _status(claim.get("freshness_status"), "claim.freshness_status")
                if freshness not in _KNOWN_CLAIM_FRESHNESS:
                    freshness_findings.append(_finding("freshness", "CLAIM_FRESHNESS_UNKNOWN", "warning", subject_ref=identity))
            if state != "verified":
                claim_findings.append(_finding("claim_traceability", "CLAIM_NOT_VERIFIED", "error" if state in _BAD_STATES else "warning", subject_ref=identity))
            if freshness in _BAD_STATES:
                freshness_findings.append(_finding("freshness", "CLAIM_NOT_CURRENT", "error", subject_ref=identity))
            elif freshness in _REVIEW_STATES:
                freshness_findings.append(_finding("freshness", "CLAIM_REVIEW_DUE", "warning", subject_ref=identity))
            for field, scope_key in (("applicable_locales", "locale"), ("applicable_regions", "region"), ("applicable_versions", "version")):
                if field in claim:
                    allowed = _sequence_values(claim.get(field), f"claim.{field}")
                    if allowed:
                        if page_scope[scope_key] is None:
                            claim_findings.append(_finding("claim_traceability", "CLAIM_SCOPE_UNKNOWN", "error", subject_ref=identity))
                        elif page_scope[scope_key] not in allowed:
                            claim_findings.append(_finding("claim_traceability", "CLAIM_SCOPE_MISMATCH", "error", subject_ref=identity))
            self._time_findings(freshness_findings, "claim", identity, claim, now)

        snapshot_map = self._index_records(snapshots, "source_snapshot", tenant)
        for snapshot_id, snapshot in snapshot_map.items():
            missing = _missing_fields(snapshot, ("source_id", "captured_at", "content_hash", "storage_object_ref"))
            if missing:
                citation_findings.append(_finding("citation_readiness", "SOURCE_SNAPSHOT_INCOMPLETE", "error", subject_ref=snapshot_id, related_refs=missing))
                freshness_findings.append(_finding("freshness", "SOURCE_SNAPSHOT_INCOMPLETE", "error", subject_ref=snapshot_id, related_refs=missing))
            content_hash = snapshot.get("content_hash")
            if content_hash is not None and (not isinstance(content_hash, str) or not _HASH_RE.fullmatch(content_hash)):
                citation_findings.append(_finding("citation_readiness", "SOURCE_CONTENT_HASH_INVALID", "error", subject_ref=snapshot_id))
            storage_ref = snapshot.get("storage_object_ref")
            if storage_ref is not None and (not isinstance(storage_ref, str) or not storage_ref.startswith("private://") or len(storage_ref) <= len("private://")):
                citation_findings.append(_finding("citation_readiness", "SOURCE_STORAGE_REF_INVALID", "error", subject_ref=snapshot_id))
            captured_at = snapshot.get("captured_at")
            if captured_at is not None:
                try:
                    _time(captured_at, "source_snapshot.captured_at")
                except GeoContentError:
                    freshness_findings.append(_finding("freshness", "FRESHNESS_TIMESTAMP_INVALID", "error", subject_ref=snapshot_id))
            if snapshot.get("status") is None:
                freshness_findings.append(_finding("freshness", "SOURCE_STATUS_MISSING", "warning", subject_ref=snapshot_id))
                snapshot_status = "captured"
            else:
                snapshot_status = _status(snapshot.get("status"), "source_snapshot.status")
                if snapshot_status not in _KNOWN_SOURCE_STATES:
                    freshness_findings.append(_finding("freshness", "SOURCE_STATUS_UNKNOWN", "warning", subject_ref=snapshot_id))
            if snapshot_status in _BAD_STATES:
                freshness_findings.append(_finding("freshness", "SOURCE_NOT_CURRENT", "error", subject_ref=snapshot_id))
            elif snapshot_status in _REVIEW_STATES:
                freshness_findings.append(_finding("freshness", "SOURCE_REVIEW_DUE", "warning", subject_ref=snapshot_id))
            self._time_findings(freshness_findings, "source_snapshot", snapshot_id, snapshot, now)
        source_map = self._index_records(sources, "source", tenant)
        if source_map:
            for snapshot_id, snapshot in snapshot_map.items():
                parent_id = snapshot.get("source_id")
                if parent_id is None:
                    continue
                parent_ref = _ref(parent_id, "source_snapshot.source_id")
                if parent_ref not in source_map:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_PARENT_MISSING", "error", subject_ref=snapshot_id, related_refs=(parent_ref,)))
            for source_id, source_row in source_map.items():
                current_id = source_row.get("current_snapshot_id")
                if current_id is None:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_CURRENT_SNAPSHOT_MISSING", "error", subject_ref=source_id))
                    continue
                current_ref = _ref(current_id, "source.current_snapshot_id")
                current_snapshot = snapshot_map.get(current_ref)
                if current_snapshot is None:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_CURRENT_SNAPSHOT_MISSING", "error", subject_ref=source_id, related_refs=(current_ref,)))
                elif current_snapshot.get("source_id") is not None and _ref(current_snapshot.get("source_id"), "source_snapshot.source_id") != source_id:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_LINEAGE_MISMATCH", "error", subject_ref=source_id, related_refs=(current_ref,)))
        for source_id, source_row in source_map.items():
            raw_source_status = source_row.get("status")
            if raw_source_status is None:
                freshness_findings.append(_finding("freshness", "SOURCE_RECORD_STATUS_MISSING", "warning", subject_ref=source_id))
                source_status = "none"
            else:
                source_status = _status(raw_source_status, "source.status")
                if source_status not in {"none", "ingested", "quarantined", "usable", "expired", "revoked", "blocked"}:
                    freshness_findings.append(_finding("freshness", "SOURCE_RECORD_STATUS_UNKNOWN", "warning", subject_ref=source_id))
            if source_status in _BAD_STATES:
                freshness_findings.append(_finding("freshness", "SOURCE_RECORD_NOT_CURRENT", "error", subject_ref=source_id))
            elif source_status in _REVIEW_STATES or source_status in {"none", "ingested"}:
                freshness_findings.append(_finding("freshness", "SOURCE_RECORD_REVIEW_DUE", "warning", subject_ref=source_id))
            self._time_findings(freshness_findings, "source", source_id, source_row, now)
        rights_map = self._index_records(rights, "rights_record_version", tenant)
        for rights_id, rights_row in rights_map.items():
            missing = _missing_fields(rights_row, ("source_snapshot_ids", "rights_holder", "policy_rule_version", "snapshot_hash", "permitted_use"))
            if missing:
                citation_findings.append(_finding("citation_readiness", "RIGHTS_VERSION_INCOMPLETE", "error", subject_ref=rights_id, related_refs=missing))
            if str(rights_row.get("status", "")).lower() == "verified":
                verified_missing = _missing_fields(rights_row, ("verified_by", "verified_at"))
                if verified_missing:
                    citation_findings.append(_finding("citation_readiness", "RIGHTS_VERIFICATION_INCOMPLETE", "error", subject_ref=rights_id, related_refs=verified_missing))
            snapshot_ids = _sequence_values(rights_row.get("source_snapshot_ids"), "rights.source_snapshot_ids") if "source_snapshot_ids" in rights_row else []
            if not snapshot_ids:
                citation_findings.append(_finding("citation_readiness", "RIGHTS_SOURCE_MISSING", "error", subject_ref=rights_id))
            snapshot_hash = rights_row.get("snapshot_hash")
            if snapshot_hash is not None and (not isinstance(snapshot_hash, str) or not _HASH_RE.fullmatch(snapshot_hash)):
                citation_findings.append(_finding("citation_readiness", "RIGHTS_SNAPSHOT_HASH_INVALID", "error", subject_ref=rights_id))
            for field, scope_key in (("permitted_locales", "locale"), ("permitted_regions", "region")):
                if field in rights_row:
                    allowed = _sequence_values(rights_row.get(field), f"rights.{field}")
                    if allowed:
                        if page_scope[scope_key] is None:
                            citation_findings.append(_finding("citation_readiness", "RIGHTS_SCOPE_UNKNOWN", "error", subject_ref=rights_id))
                        elif page_scope[scope_key] not in allowed:
                            citation_findings.append(_finding("citation_readiness", "RIGHTS_SCOPE_MISMATCH", "error", subject_ref=rights_id))
            if rights_row.get("status") is None:
                freshness_findings.append(_finding("freshness", "RIGHTS_STATUS_MISSING", "warning", subject_ref=rights_id))
                rights_status = "pending"
            else:
                rights_status = _status(rights_row.get("status"), "rights.status")
                if rights_status not in _KNOWN_RIGHTS_STATES:
                    freshness_findings.append(_finding("freshness", "RIGHTS_STATUS_UNKNOWN", "warning", subject_ref=rights_id))
            if rights_status in _BAD_STATES:
                freshness_findings.append(_finding("freshness", "RIGHTS_NOT_CURRENT", "error", subject_ref=rights_id))
            elif rights_status in _REVIEW_STATES:
                freshness_findings.append(_finding("freshness", "RIGHTS_REVIEW_DUE", "warning", subject_ref=rights_id))
            self._time_findings(freshness_findings, "rights", rights_id, rights_row, now)
        evidence_map = self._index_records(evidences, "evidence", tenant)
        claim_evidence: dict[str, list[tuple[str, Mapping[str, Any]]]] = {identity: [] for identity in claim_map}
        claim_declared_evidence: dict[str, set[str]] = {}
        for claim_id, claim in claim_map.items():
            evidence_ids = _sequence_values(claim.get("evidence_ids"), "claim.evidence_ids") if "evidence_ids" in claim else []
            claim_declared_evidence[claim_id] = {_ref(value, "claim.evidence_ids[]") for value in evidence_ids}
            for evidence_id in sorted(claim_declared_evidence[claim_id] - set(evidence_map)):
                claim_findings.append(_finding("claim_traceability", "CLAIM_EVIDENCE_UNKNOWN", "error", subject_ref=claim_id, related_refs=(evidence_id,)))
        for evidence_id, evidence in evidence_map.items():
            linked: list[str] = []
            if evidence.get("claim_id") is not None:
                linked.append(_ref(evidence["claim_id"], "evidence.claim_id"))
            claim_ids = _sequence_values(evidence.get("claim_ids"), "evidence.claim_ids") if "claim_ids" in evidence else []
            linked.extend(_ref(value, "evidence.claim_ids[]") for value in claim_ids)
            declared_claim_ids = set(linked)
            for claim_id, claim in claim_map.items():
                if evidence_id in claim_declared_evidence.get(claim_id, set()):
                    linked.append(claim_id)
            for claim_id in sorted(set(linked)):
                if claim_id in claim_evidence:
                    claim_evidence[claim_id].append((evidence_id, evidence))
                    if claim_id not in declared_claim_ids:
                        claim_findings.append(_finding(
                            "claim_traceability", "EVIDENCE_CLAIM_MISMATCH", "error",
                            subject_ref=evidence_id, related_refs=(claim_id,),
                        ))
                    if evidence_id not in claim_declared_evidence.get(claim_id, set()):
                        claim_findings.append(_finding(
                            "claim_traceability", "CLAIM_EVIDENCE_MISMATCH", "error",
                            subject_ref=claim_id, related_refs=(evidence_id,),
                        ))
            for unknown_claim in sorted(set(linked) - set(claim_map)):
                claim_findings.append(_finding(
                    "claim_traceability", "EVIDENCE_CLAIM_UNKNOWN", "error",
                    subject_ref=evidence_id, related_refs=(unknown_claim,),
                ))
            if evidence.get("status") is None:
                freshness_findings.append(_finding("freshness", "EVIDENCE_STATUS_MISSING", "warning", subject_ref=evidence_id))
                status = "captured"
            else:
                status = _status(evidence.get("status"), "evidence.status")
                if status not in _KNOWN_EVIDENCE_STATES:
                    freshness_findings.append(_finding("freshness", "EVIDENCE_STATUS_UNKNOWN", "warning", subject_ref=evidence_id))
            if status in _BAD_STATES:
                freshness_findings.append(_finding("freshness", "EVIDENCE_NOT_CURRENT", "error", subject_ref=evidence_id))
            elif status in _REVIEW_STATES:
                freshness_findings.append(_finding("freshness", "EVIDENCE_REVIEW_DUE", "warning", subject_ref=evidence_id))
            self._time_findings(freshness_findings, "evidence", evidence_id, evidence, now)
            for field, scope_key in (("applicable_locales", "locale"), ("applicable_regions", "region"), ("applicable_versions", "version")):
                if field in evidence:
                    allowed = _sequence_values(evidence.get(field), f"evidence.{field}")
                    if allowed:
                        if page_scope[scope_key] is None:
                            citation_findings.append(_finding("citation_readiness", "EVIDENCE_SCOPE_UNKNOWN", "error", subject_ref=evidence_id))
                        elif page_scope[scope_key] not in allowed:
                            citation_findings.append(_finding("citation_readiness", "EVIDENCE_SCOPE_MISMATCH", "error", subject_ref=evidence_id))
            source_id = evidence.get("source_snapshot_id")
            if source_id is None or _ref(source_id, "evidence.source_snapshot_id") not in snapshot_map:
                citation_findings.append(_finding("citation_readiness", "SOURCE_SNAPSHOT_MISSING", "error", subject_ref=evidence_id))
            else:
                source_ref = _ref(source_id, "evidence.source_snapshot_id")
                snapshot = snapshot_map[source_ref]
                snapshot_parent = snapshot.get("source_id")
                if snapshot_parent is not None and sources and _ref(snapshot_parent, "source_snapshot.source_id") not in source_map:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_PARENT_MISSING", "error", subject_ref=evidence_id, related_refs=(_ref(snapshot_parent, "source_snapshot.source_id"),)))
                if snapshot.get("status") is None:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_STATUS_MISSING", "warning", subject_ref=evidence_id, related_refs=(_ref(source_id, "source_snapshot_id"),)))
                    source_status = "captured"
                else:
                    source_status = _status(snapshot.get("status"), "source_snapshot.status")
                    if source_status not in _KNOWN_SOURCE_STATES:
                        citation_findings.append(_finding("citation_readiness", "SOURCE_STATUS_UNKNOWN", "warning", subject_ref=evidence_id, related_refs=(_ref(source_id, "source_snapshot_id"),)))
                if source_status in _BAD_STATES:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_NOT_USABLE", "error", subject_ref=evidence_id, related_refs=(_ref(source_id, "source_snapshot_id"),)))
                elif source_status in _REVIEW_STATES:
                    citation_findings.append(_finding("citation_readiness", "SOURCE_REVIEW_REQUIRED", "warning", subject_ref=evidence_id, related_refs=(_ref(source_id, "source_snapshot_id"),)))
                self._time_findings(citation_findings, "source_snapshot", source_ref, snapshot, now, dimension="citation_readiness")
            rights_id = evidence.get("rights_record_version_id")
            if rights_id is None or _ref(rights_id, "evidence.rights_record_version_id") not in rights_map:
                citation_findings.append(_finding("citation_readiness", "RIGHTS_VERSION_MISSING", "error", subject_ref=evidence_id))
            else:
                rights_row = rights_map[_ref(rights_id, "evidence.rights_record_version_id")]
                if rights_row.get("status") is None:
                    citation_findings.append(_finding("citation_readiness", "RIGHTS_STATUS_MISSING", "error", subject_ref=evidence_id, related_refs=(_ref(rights_id, "rights_id"),)))
                    rights_status = "pending"
                else:
                    rights_status = _status(rights_row.get("status"), "rights.status")
                    if rights_status not in _KNOWN_RIGHTS_STATES:
                        citation_findings.append(_finding("citation_readiness", "RIGHTS_STATUS_UNKNOWN", "error", subject_ref=evidence_id, related_refs=(_ref(rights_id, "rights_id"),)))
                permitted = rights_row.get("permitted_use")
                if rights_status in _BAD_STATES or rights_status != "verified":
                    citation_findings.append(_finding("citation_readiness", "RIGHTS_NOT_VERIFIED", "error", subject_ref=evidence_id, related_refs=(_ref(rights_id, "rights_id"),)))
                elif permitted not in {"research", "derivative", "commercial"}:
                    citation_findings.append(_finding("citation_readiness", "RIGHTS_USE_NOT_ALLOWED", "error", subject_ref=evidence_id, related_refs=(_ref(rights_id, "rights_id"),)))
                rights_snapshot_ids = _sequence_values(rights_row.get("source_snapshot_ids"), "rights.source_snapshot_ids") if "source_snapshot_ids" in rights_row else []
                if source_id is not None and _ref(source_id, "evidence.source_snapshot_id") not in {_ref(value, "rights.source_snapshot_ids[]") for value in rights_snapshot_ids}:
                    citation_findings.append(_finding("citation_readiness", "RIGHTS_SOURCE_MISMATCH", "error", subject_ref=evidence_id, related_refs=(_ref(rights_id, "rights_id"), _ref(source_id, "evidence.source_snapshot_id"))))
                for field, scope_key in (("permitted_locales", "locale"), ("permitted_regions", "region")):
                    if field in rights_row:
                        allowed = _sequence_values(rights_row.get(field), f"rights.{field}")
                        if allowed:
                            if page_scope[scope_key] is None:
                                citation_findings.append(_finding("citation_readiness", "RIGHTS_SCOPE_UNKNOWN", "error", subject_ref=evidence_id))
                            elif page_scope[scope_key] not in allowed:
                                citation_findings.append(_finding("citation_readiness", "RIGHTS_SCOPE_MISMATCH", "error", subject_ref=evidence_id))
                self._time_findings(citation_findings, "rights", _ref(rights_id, "rights_id"), rights_row, now, dimension="citation_readiness")
            quote = evidence.get("quote")
            locator = evidence.get("locator")
            if not isinstance(quote, str) or not quote.strip():
                citation_findings.append(_finding("citation_readiness", "CITATION_QUOTE_MISSING", "error", subject_ref=evidence_id))
            if not isinstance(locator, str) or not locator.strip():
                citation_findings.append(_finding("citation_readiness", "CITATION_LOCATOR_MISSING", "error", subject_ref=evidence_id))

        for claim_id, claim in claim_map.items():
            links = claim_evidence.get(claim_id, [])
            if not links:
                claim_findings.append(_finding("claim_traceability", "CLAIM_NO_EVIDENCE", "error", subject_ref=claim_id))
            elif not any(item.get("status") is not None and _status(item.get("status"), "evidence.status") == "valid" for _, item in links):
                claim_findings.append(_finding("claim_traceability", "CLAIM_NO_VALID_EVIDENCE", "error", subject_ref=claim_id, related_refs=(item_id for item_id, _ in links)))

        linked_evidence_ids = {
            evidence_id for links in claim_evidence.values() for evidence_id, _ in links
        }
        for evidence_id in sorted(set(evidence_map) - linked_evidence_ids):
            claim_findings.append(_finding("claim_traceability", "ORPHAN_EVIDENCE", "error", subject_ref=evidence_id))

        if not claims:
            claim_findings.append(_finding("claim_traceability", "CLAIMS_MISSING", "warning"))
        if not evidences:
            citation_findings.append(_finding("citation_readiness", "EVIDENCE_MISSING", "warning"))

        if page is not None:
            self._crawlability(crawl_findings, freshness_findings, page, canonical, tenant, now)
        else:
            crawl_findings.append(_finding("crawlability", "PAGE_MISSING", "error"))
        dimensions = {
            "entity_consistency": _dimension("entity_consistency", entity_findings, len(entities)),
            "claim_traceability": _dimension("claim_traceability", claim_findings, len(claims)),
            "citation_readiness": _dimension("citation_readiness", citation_findings, len(evidences)),
            "freshness": _dimension("freshness", freshness_findings, len(claims) + len(evidences) + len(snapshots) + len(rights)),
            "crawlability": _dimension("crawlability", crawl_findings, 1 if page is not None else 0),
        }
        findings = entity_findings + claim_findings + citation_findings + freshness_findings + crawl_findings
        return dimensions, findings

    @staticmethod
    def _index_records(rows: Sequence[Mapping[str, Any]], kind: str, tenant: str) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            _tenant_guard(row, tenant, kind)
            if row.get("id") is None:
                raise GeoContentError("INVALID_GEO_CONTENT_INPUT", f"{kind}.id is required")
            identity = _ref(row["id"], f"{kind}.id")
            if identity in result and _canonical(result[identity]) != _canonical(row):
                raise GeoContentError("DUPLICATE_GEO_CONTENT_RECORD", f"duplicate {kind} projection")
            result[identity] = row
        return result

    @staticmethod
    def _time_findings(
        findings: list[dict[str, Any]], kind: str, identity: str, row: Mapping[str, Any], now: datetime,
        *, dimension: str = "freshness",
    ) -> None:
        for field in ("valid_from", "effective_at", "captured_at", "verified_at", "created_at", "published_at"):
            value = row.get(field)
            if value is None:
                continue
            try:
                starts = _time(value, f"{kind}.{field}")
            except GeoContentError:
                findings.append(_finding(dimension, "FRESHNESS_TIMESTAMP_INVALID", "error", subject_ref=identity))
                continue
            if starts > now:
                findings.append(_finding(dimension, "FRESHNESS_NOT_YET_VALID", "error", subject_ref=identity))
        for field in ("valid_to", "expires_at", "freshness_expires_at"):
            value = row.get(field)
            if value is None:
                continue
            try:
                expires = _time(value, f"{kind}.{field}")
            except GeoContentError:
                findings.append(_finding(dimension, "FRESHNESS_TIMESTAMP_INVALID", "error", subject_ref=identity))
                continue
            if expires <= now:
                findings.append(_finding(dimension, "FRESHNESS_EXPIRED", "error", subject_ref=identity))
        value = row.get("review_due_at")
        if value is not None:
            try:
                if _time(value, f"{kind}.review_due_at") <= now:
                    findings.append(_finding(dimension, "FRESHNESS_REVIEW_DUE", "warning", subject_ref=identity))
            except GeoContentError:
                findings.append(_finding(dimension, "FRESHNESS_TIMESTAMP_INVALID", "error", subject_ref=identity))

    @staticmethod
    def _crawlability(
        findings: list[dict[str, Any]], freshness_findings: list[dict[str, Any]],
        page: Mapping[str, Any], canonical: Mapping[str, Any] | None, tenant: str, now: datetime,
    ) -> None:
        if page.get("status") is None:
            findings.append(_finding("crawlability", "PAGE_STATUS_MISSING", "error"))
            state = "draft"
        else:
            state = _status(page.get("status"), "page.status")
        if state not in _PASSABLE_PAGE_STATES:
            findings.append(_finding("crawlability", "PAGE_NOT_PUBLIC", "error"))
        title = page.get("title")
        if not isinstance(title, str) or not title.strip():
            findings.append(_finding("crawlability", "PAGE_TITLE_MISSING", "error"))
        page_url: str | None = None
        try:
            page_url = _canonical_url(page)
            raw_page_url = page.get("canonical_url", page.get("url_path"))
            origin_value = _declared_origin(page)
            raw_parts = urlsplit(raw_page_url.strip()) if isinstance(raw_page_url, str) else None
            if raw_parts is not None and (raw_parts.scheme or raw_parts.netloc) and origin_value is None:
                findings.append(_finding("crawlability", "CANONICAL_ORIGIN_MISSING", "error"))
            if isinstance(raw_page_url, str) and raw_page_url.strip().startswith("/") and origin_value is None:
                findings.append(_finding("crawlability", "CANONICAL_ORIGIN_MISSING", "error"))
            # If both forms are present they describe one page and must
            # resolve to the same normalized path.
            if "url_path" in page and page.get("url_path") is not None and "canonical_url" in page:
                path_only = dict(page)
                path_only.pop("canonical_url", None)
                path_url = _canonical_url(path_only)
                if urlsplit(page_url).path != urlsplit(path_url).path:
                    findings.append(_finding("crawlability", "CANONICAL_URL_MISMATCH", "error"))
            if origin_value is not None:
                expected_origin = _origin(origin_value) if isinstance(origin_value, str) else None
                actual = urlsplit(page_url)
                actual_origin = _origin(f"{actual.scheme}://{actual.netloc}") if actual.scheme and actual.netloc else expected_origin
                if expected_origin is None or actual_origin != expected_origin:
                    findings.append(_finding("crawlability", "CANONICAL_ORIGIN_MISMATCH", "error"))
        except (ValueError, TypeError):
            findings.append(_finding("crawlability", "CANONICAL_URL_INVALID", "error"))
        if "url_path" in page and page.get("url_path") is not None:
            try:
                raw_path = page.get("url_path")
                if not isinstance(raw_path, str) or not raw_path.strip().startswith("/") or urlsplit(raw_path.strip()).scheme or urlsplit(raw_path.strip()).netloc:
                    raise ValueError("url_path")
                path_value = dict(page)
                path_value.pop("canonical_url", None)
                _canonical_url(path_value)
            except (ValueError, TypeError):
                findings.append(_finding("crawlability", "PAGE_URL_PATH_INVALID", "error"))
        locale = page.get("locale")
        if not isinstance(locale, str) or not _LOCALE_RE.fullmatch(locale):
            findings.append(_finding("crawlability", "PAGE_LOCALE_INVALID", "error"))
        try:
            if not _page_body(page).strip():
                findings.append(_finding("crawlability", "PAGE_BODY_EMPTY", "error"))
        except GeoContentError:
            findings.append(_finding("crawlability", "PAGE_BODY_INVALID", "error"))
        directives: list[str] = []
        for field in ("robots", "robots_meta", "x_robots_tag"):
            value = page.get(field)
            if isinstance(value, str):
                directives.extend(part.strip().lower() for part in value.split(","))
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                directives.extend(str(part).strip().lower() for part in value)
        if any(part == "noindex" or part.startswith("noindex:") for part in directives):
            findings.append(_finding("crawlability", "ROBOTS_NOINDEX", "error"))
        if any(part == "nofollow" or part.startswith("nofollow:") for part in directives):
            findings.append(_finding("crawlability", "ROBOTS_NOFOLLOW", "warning"))
        if page.get("sitemap_included") is False:
            findings.append(_finding("crawlability", "SITEMAP_OMITTED", "warning"))
        self_page_identity = _ref(page.get("id"), "page.id") if page.get("id") is not None else "page"
        self_status = page.get("status")
        if self_status is not None:
            GeoContentRuleService._time_findings(freshness_findings, "page", self_page_identity, page, now)
        if canonical is None:
            findings.append(_finding("crawlability", "CANONICAL_SNAPSHOT_MISSING", "warning"))
            freshness_findings.append(_finding("freshness", "CANONICAL_SNAPSHOT_MISSING", "warning"))
        else:
            # The caller already checked the canonical snapshot before any
            # fields were read.  Keep the guard here as well because this
            # helper is intentionally usable in isolation in contract tests.
            _tenant_guard(canonical, tenant, "canonical")
            canonical_url = None
            if page_url is not None and ("canonical_url" in canonical or "url_path" in canonical):
                try:
                    canonical_raw = canonical.get("canonical_url", canonical.get("url_path"))
                    canonical_origin_value = _declared_origin(canonical)
                    canonical_parts = urlsplit(canonical_raw.strip()) if isinstance(canonical_raw, str) else None
                    if canonical_parts is not None and (canonical_parts.scheme or canonical_parts.netloc) and canonical_origin_value is None:
                        findings.append(_finding("crawlability", "CANONICAL_SNAPSHOT_ORIGIN_MISSING", "error"))
                    if isinstance(canonical_raw, str) and canonical_raw.strip().startswith("/") and canonical_origin_value is None:
                        findings.append(_finding("crawlability", "CANONICAL_SNAPSHOT_ORIGIN_MISSING", "error"))
                    canonical_url = _canonical_url(canonical)
                except (ValueError, TypeError):
                    findings.append(_finding("crawlability", "CANONICAL_SNAPSHOT_URL_INVALID", "error"))
                else:
                    if urlsplit(canonical_url).path != urlsplit(page_url).path:
                        findings.append(_finding("crawlability", "CANONICAL_SNAPSHOT_URL_MISMATCH", "error"))
                    page_parts = urlsplit(page_url)
                    snapshot_parts = urlsplit(canonical_url)
                    if page_parts.netloc and snapshot_parts.netloc:
                        page_origin = _origin(f"{page_parts.scheme}://{page_parts.netloc}")
                        snapshot_origin = _origin(f"{snapshot_parts.scheme}://{snapshot_parts.netloc}")
                        if page_origin != snapshot_origin:
                            findings.append(_finding("crawlability", "CANONICAL_SNAPSHOT_ORIGIN_MISMATCH", "error"))
            page_canonical_id = page.get("canonical_content_version_id")
            canonical_id_value = canonical.get("id")
            if page_canonical_id is None or canonical_id_value is None:
                findings.append(_finding("crawlability", "CANONICAL_VERSION_ID_MISSING", "error"))
            else:
                if _ref(page_canonical_id, "page.canonical_content_version_id") != _ref(canonical_id_value, "canonical.id"):
                    findings.append(_finding("crawlability", "CANONICAL_VERSION_MISMATCH", "error"))
            freshness = canonical.get("freshness_status")
            canonical_id = _ref(canonical.get("id"), "canonical.id") if canonical.get("id") is not None else "canonical"
            if freshness is None:
                findings.append(_finding("crawlability", "CANONICAL_FRESHNESS_MISSING", "warning", subject_ref=canonical_id))
                freshness_findings.append(_finding("freshness", "CANONICAL_FRESHNESS_MISSING", "warning", subject_ref=canonical_id))
                freshness = "__missing__"
            else:
                freshness = _status(freshness, "canonical.freshness_status")
            if freshness in _BAD_STATES:
                findings.append(_finding("crawlability", "CANONICAL_NOT_CURRENT", "error"))
            elif freshness in _REVIEW_STATES:
                findings.append(_finding("crawlability", "CANONICAL_REVIEW_REQUIRED", "warning"))
            elif freshness not in _FRESH_STATES and freshness != "__missing__":
                findings.append(_finding("crawlability", "CANONICAL_FRESHNESS_UNKNOWN", "warning", subject_ref=canonical_id))
            if freshness in _BAD_STATES:
                freshness_findings.append(_finding("freshness", "CANONICAL_NOT_CURRENT", "error", subject_ref=canonical_id))
            elif freshness in _REVIEW_STATES:
                freshness_findings.append(_finding("freshness", "CANONICAL_REVIEW_DUE", "warning", subject_ref=canonical_id))
            elif freshness not in _FRESH_STATES and freshness != "__missing__":
                freshness_findings.append(_finding("freshness", "CANONICAL_FRESHNESS_UNKNOWN", "warning", subject_ref=canonical_id))
            canonical_status = canonical.get("status")
            if canonical_status is not None:
                canonical_status = _status(canonical_status, "canonical.status")
                if canonical_status in _BAD_STATES:
                    findings.append(_finding("crawlability", "CANONICAL_NOT_CURRENT", "error", subject_ref=canonical_id))
                    freshness_findings.append(_finding("freshness", "CANONICAL_NOT_CURRENT", "error", subject_ref=canonical_id))
                elif canonical_status not in {"draft", "evidence_pending", "fact_checked", "approved", "published", "ready", "active"}:
                    findings.append(_finding("crawlability", "CANONICAL_STATUS_UNKNOWN", "warning", subject_ref=canonical_id))
                    freshness_findings.append(_finding("freshness", "CANONICAL_STATUS_UNKNOWN", "warning", subject_ref=canonical_id))
            GeoContentRuleService._time_findings(freshness_findings, "canonical", canonical_id, canonical, now)

    def audit_for(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        return tuple(deepcopy(row) for row in self.audit if row.get("org_id") == tenant)


__all__ = ["GeoContentError", "GeoContentRuleService", "InMemoryGeoContentStore"]
