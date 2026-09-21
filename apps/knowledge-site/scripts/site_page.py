"""Tenant-scoped, immutable SitePageVersion projections for SITE-001.

The knowledge-site directory is a build boundary.  This module deliberately
does not open a database or write a domain table.  ``SitePageRepository`` is a
small public projection port; the application can provide a database-backed
adapter later while the normalization, tenant, version and idempotency rules
remain deterministic and testable offline.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "packages" / "contracts" / "jsonschema" / "site-page-version.schema.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(CONTRACT, format_checker=FormatChecker())
HASH_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
PAGE_KEY_RE = re.compile(r"^[a-z][a-z0-9._/-]{1,127}$")
LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
EVIDENCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
RESERVED_PATHS = frozenset({"/api", "/internal", "/admin", "/health", "/robots.txt", "/sitemap.xml"})


class SitePageError(ValueError):
    """Stable error code for SITE-001 commands and reads."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SitePageRepository(Protocol):
    """Public projection port used by the site application."""

    def get_command(self, *, org_id: str, idempotency_key: str) -> Mapping[str, Any] | None: ...

    def save_command(self, *, org_id: str, idempotency_key: str, request_hash: str, response: Mapping[str, Any]) -> None: ...

    def get_page_by_key(self, *, org_id: str, page_key: str) -> Mapping[str, Any] | None: ...

    def get_page(self, *, org_id: str, page_id: str) -> Mapping[str, Any] | None: ...

    def save_page(self, page: Mapping[str, Any]) -> None: ...

    def save_version(self, version: Mapping[str, Any]) -> None: ...

    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any] | None: ...

    def list_versions(self, *, org_id: str, site_page_id: str) -> Sequence[Mapping[str, Any]]: ...


class InMemorySitePageRepository:
    """Deterministic repository fixture and default local projection store."""

    def __init__(self) -> None:
        self.pages: dict[str, dict[str, Any]] = {}
        self.pages_by_key: dict[tuple[str, str], str] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.versions_by_page: dict[tuple[str, str], list[str]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def get_command(self, *, org_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self.commands.get((org_id, idempotency_key))
            return None if value is None else deepcopy(value)

    def save_command(self, *, org_id: str, idempotency_key: str, request_hash: str, response: Mapping[str, Any]) -> None:
        with self._lock:
            key = (org_id, idempotency_key)
            if key in self.commands:
                raise SitePageError("IDEMPOTENCY_KEY_REUSED", "idempotency command already exists")
            self.commands[key] = {
                "request_hash": request_hash,
                "response": deepcopy(dict(response)),
            }

    def get_page_by_key(self, *, org_id: str, page_key: str) -> Mapping[str, Any] | None:
        with self._lock:
            page_id = self.pages_by_key.get((org_id, page_key))
            return None if page_id is None else deepcopy(self.pages[page_id])

    def get_page(self, *, org_id: str, page_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self.pages.get(page_id)
            if value is None or value["org_id"] != org_id:
                return None
            return deepcopy(value)

    def save_page(self, page: Mapping[str, Any]) -> None:
        with self._lock:
            value = deepcopy(dict(page))
            page_id = str(value["id"])
            key = (str(value["org_id"]), str(value["page_key"]))
            existing = self.pages_by_key.get(key)
            if existing is not None and existing != page_id:
                raise SitePageError("PAGE_KEY_CONFLICT", "page_key already belongs to another page")
            self.pages[page_id] = value
            self.pages_by_key[key] = page_id

    def save_version(self, version: Mapping[str, Any]) -> None:
        with self._lock:
            value = deepcopy(dict(version))
            version_id = str(value["id"])
            if version_id in self.versions:
                raise SitePageError("VERSION_IMMUTABLE", "site page version already exists")
            key = (str(value["org_id"]), str(value["site_page_id"]))
            numbers = self.versions_by_page.setdefault(key, [])
            if any(self.versions[item]["version_no"] == value["version_no"] for item in numbers):
                raise SitePageError("VERSION_CONFLICT", "version number already exists")
            self.versions[version_id] = value
            numbers.append(version_id)
            numbers.sort(key=lambda item: (self.versions[item]["version_no"], item))

    def get_version(self, *, org_id: str, version_id: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self.versions.get(version_id)
            if value is None or value["org_id"] != org_id:
                return None
            return deepcopy(value)

    def list_versions(self, *, org_id: str, site_page_id: str) -> Sequence[Mapping[str, Any]]:
        with self._lock:
            ids = self.versions_by_page.get((org_id, site_page_id), [])
            return tuple(deepcopy(self.versions[item]) for item in ids)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SitePageError("INVALID_SITE_PAGE", "site page metadata must be JSON serializable") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _uuid(value: object, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SitePageError("INVALID_SITE_PAGE_CONTEXT", f"{field} must be a UUID") from exc


def _text(value: object, field: str, *, maximum: int = 4096, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must be text")
    result = value.strip()
    if (required and not result) or len(result) > maximum:
        qualifier = "non-empty " if required else ""
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must be {qualifier}text up to {maximum} characters")
    return result


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _time(value: object, field: str, *, default: str | None = None) -> str:
    if value is None:
        if default is None:
            raise SitePageError("INVALID_SITE_PAGE", f"{field} is required")
        return default
    if not isinstance(value, str):
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must include a timezone")
    return _stamp(parsed)


def _sequence(value: object, field: str, *, allow_none: bool = False) -> list[Any]:
    if value is None and allow_none:
        return []
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must be an array")
    return list(value)


def _page_key(value: object) -> str:
    result = _text(value, "page_key", maximum=128).lower()
    if not PAGE_KEY_RE.fullmatch(result) or "//" in result or ".." in result:
        raise SitePageError("INVALID_SITE_PAGE", "page_key has an invalid format")
    return result


def _url_path(value: object) -> str:
    result = _text(value, "url_path", maximum=2048)
    if not result.startswith("/") or "?" in result or "#" in result or any(ord(char) < 32 for char in result):
        raise SitePageError("INVALID_CANONICAL_URL", "url_path must be an absolute path without query or fragment")
    if "//" in result:
        raise SitePageError("INVALID_CANONICAL_URL", "url_path cannot contain duplicate slashes")
    decoded = unquote(result)
    if "//" in decoded:
        raise SitePageError("INVALID_CANONICAL_URL", "url_path cannot contain encoded duplicate slashes")
    parts = decoded.split("/")
    if any(part in {".", ".."} for part in parts):
        raise SitePageError("INVALID_CANONICAL_URL", "url_path cannot contain dot segments")
    if result != "/" and result.endswith("/"):
        result = result[:-1]
    if result in RESERVED_PATHS or any(result.startswith(item + "/") for item in RESERVED_PATHS if item.startswith("/")):
        raise SitePageError("INVALID_CANONICAL_URL", "url_path is reserved for an application endpoint")
    return result


def _locale(value: object) -> str:
    result = _text(value, "locale", maximum=32)
    if not LOCALE_RE.fullmatch(result):
        raise SitePageError("INVALID_SITE_PAGE", "locale must use a BCP-47-like form")
    pieces = result.split("-")
    return "-".join([pieces[0].lower(), *[piece.upper() if len(piece) in {2, 3} else piece for piece in pieces[1:]]])


def _person(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SitePageError("INVALID_SITE_PAGE", f"{field} must be an object")
    identity = value.get("id", value.get("ref"))
    result = {
        "id": _text(identity, f"{field}.id", maximum=256),
        "name": _text(value.get("name"), f"{field}.name", maximum=256),
        "url": None,
    }
    if value.get("url") is not None:
        url = _text(value.get("url"), f"{field}.url", maximum=2048)
        parsed = urlsplit(url)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise SitePageError("INVALID_SITE_PAGE", f"{field}.url must use http or https")
        result["url"] = url
    return result


def _methodology(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        summary = value.get("summary")
        steps = value.get("steps", [])
        version = value.get("version")
    else:
        summary = None
        steps = value
        version = None
    normalized_steps = [_text(item, "methodology.steps[]", maximum=2000) for item in _sequence(steps, "methodology.steps")]
    if not normalized_steps:
        raise SitePageError("INVALID_SITE_PAGE", "methodology requires at least one step")
    if len(set(normalized_steps)) != len(normalized_steps):
        raise SitePageError("INVALID_SITE_PAGE", "methodology steps must be unique")
    if summary is None:
        summary = normalized_steps[0]
    result = {
        "summary": _text(summary, "methodology.summary", maximum=4000),
        "steps": normalized_steps,
        "version": None if version is None else _text(version, "methodology.version", maximum=128),
    }
    return result


def _evidence(value: object) -> list[dict[str, Any]]:
    rows = _sequence(value, "evidence")
    if not rows:
        raise SitePageError("EVIDENCE_REQUIRED", "at least one evidence reference is required")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if isinstance(item, Mapping):
            ref = _text(item.get("ref", item.get("id")), "evidence.ref", maximum=512)
            kind = _text(item.get("type", "source"), "evidence.type", maximum=128).lower()
            locator = None if item.get("locator") is None else _text(item.get("locator"), "evidence.locator", maximum=1024)
            snapshot_hash = item.get("snapshot_hash")
        else:
            ref = _text(item, "evidence.ref", maximum=512)
            kind, locator, snapshot_hash = "source", None, None
        if not EVIDENCE_TYPE_RE.fullmatch(kind):
            raise SitePageError("INVALID_SITE_PAGE", "evidence.type has an invalid format")
        if ref in seen:
            raise SitePageError("INVALID_SITE_PAGE", "evidence references must be unique")
        seen.add(ref)
        if snapshot_hash is not None:
            snapshot_hash = _text(snapshot_hash, "evidence.snapshot_hash", maximum=64)
            if not HASH_RE.fullmatch(snapshot_hash):
                raise SitePageError("INVALID_SITE_PAGE", "evidence.snapshot_hash must be SHA-256")
            snapshot_hash = snapshot_hash.lower()
        result.append({"ref": ref, "type": kind, "locator": locator, "snapshot_hash": snapshot_hash})
    return result


def _limitations(value: object) -> list[str]:
    result: list[str] = []
    for item in _sequence(value, "limitations", allow_none=True):
        if isinstance(item, Mapping):
            item = item.get("text", item.get("description"))
        text = _text(item, "limitations[]", maximum=2000)
        if text not in result:
            result.append(text)
    return result


def _faq(value: object) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _sequence(value, "faq", allow_none=True):
        if not isinstance(item, Mapping):
            raise SitePageError("INVALID_SITE_PAGE", "faq entries must be objects")
        question = _text(item.get("question"), "faq.question", maximum=1000)
        answer = _text(item.get("answer"), "faq.answer", maximum=10000)
        key = question.casefold()
        if key in seen:
            raise SitePageError("INVALID_SITE_PAGE", "faq questions must be unique")
        seen.add(key)
        refs = [_text(ref, "faq.evidence_refs[]", maximum=512) for ref in _sequence(item.get("evidence_refs", []), "faq.evidence_refs")]
        if len(set(refs)) != len(refs):
            raise SitePageError("INVALID_SITE_PAGE", "faq evidence references must be unique")
        result.append({"question": question, "answer": answer, "evidence_refs": refs})
    return result


def _visible_content(value: object) -> dict[str, Any]:
    if value is None:
        return {"blocks": []}
    if not isinstance(value, Mapping):
        raise SitePageError("INVALID_SITE_PAGE", "visible_content must be an object")
    rows = _sequence(value.get("blocks", []), "visible_content.blocks")
    result: list[dict[str, str]] = []
    keys: set[str] = set()
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, Mapping):
            raise SitePageError("INVALID_SITE_PAGE", "visible_content blocks must be objects")
        key = _text(item.get("key", item.get("id", f"block-{index}")), "visible_content.blocks.key", maximum=256)
        kind = _text(item.get("type", "paragraph"), "visible_content.blocks.type", maximum=64)
        text = _text(item.get("text", item.get("content")), "visible_content.blocks.text", maximum=20000)
        if key in keys:
            raise SitePageError("INVALID_SITE_PAGE", "visible_content block keys must be unique")
        keys.add(key)
        result.append({"key": key, "type": kind, "text": text})
    return {"blocks": result}


def _uuid_array(value: object, field: str) -> list[str]:
    result: list[str] = []
    for item in _sequence(value, field, allow_none=True):
        identity = _uuid(item, field)
        if identity not in result:
            result.append(identity)
    return result


class SitePageService:
    """Create and read tenant-scoped immutable page version projections."""

    def __init__(
        self,
        repository: SitePageRepository | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        canonical_version_port: Any | None = None,
        variant_version_port: Any | None = None,
        region_version_port: Any | None = None,
    ) -> None:
        self.repository = repository or InMemorySitePageRepository()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.canonical_version_port = canonical_version_port
        self.variant_version_port = variant_version_port
        self.region_version_port = region_version_port
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def create_version(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        page_key: str | None = None,
        site_page_id: UUID | str | None = None,
        version_no: int,
        expected_previous_version: int = 0,
        canonical_content_version_id: UUID | str,
        region_profile_version_id: UUID | str,
        locale: str,
        url_path: str,
        title: str,
        author: Mapping[str, Any],
        reviewer: Mapping[str, Any] | None = None,
        methodology: Mapping[str, Any] | Sequence[str] = (),
        evidence: Sequence[Mapping[str, Any] | str] = (),
        limitations: Sequence[Mapping[str, Any] | str] = (),
        faq: Sequence[Mapping[str, Any]] = (),
        summary: str = "",
        visible_content: Mapping[str, Any] | None = None,
        source_snapshot_refs: Sequence[UUID | str] = (),
        variant_version_id: UUID | str | None = None,
        render_mode: str = "ssr",
        status: str = "draft",
        updated_at: str | None = None,
        published_at: str | None = None,
    ) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _text(trace_id, "trace_id", maximum=256)
        key = _text(idempotency_key, "idempotency_key", maximum=200)
        if len(key) < 8:
            raise SitePageError("INVALID_SITE_PAGE_CONTEXT", "idempotency_key length must be 8..200")
        if isinstance(version_no, bool) or not isinstance(version_no, int) or version_no < 1:
            raise SitePageError("INVALID_VERSION", "version_no must be a positive integer")
        if isinstance(expected_previous_version, bool) or not isinstance(expected_previous_version, int) or expected_previous_version < 0:
            raise SitePageError("INVALID_VERSION", "expected_previous_version must be a non-negative integer")
        normalized_key = _page_key(page_key) if page_key is not None else None
        canonical_id = _uuid(canonical_content_version_id, "canonical_content_version_id")
        region_id = _uuid(region_profile_version_id, "region_profile_version_id")
        variant_id = None if variant_version_id is None else _uuid(variant_version_id, "variant_version_id")
        normalized_locale = _locale(locale)
        normalized_path = _url_path(url_path)
        if render_mode not in {"ssr", "static"}:
            raise SitePageError("INVALID_SITE_PAGE", "render_mode must be ssr or static")
        if status not in {"draft", "ready", "published", "superseded", "rolled_back"}:
            raise SitePageError("INVALID_SITE_PAGE", "status is invalid")
        if status != "draft":
            raise SitePageError("INVALID_SITE_PAGE_STATE", "new page versions must start in draft")
        normalized_author = _person(author, "author")
        normalized_reviewer = None if reviewer is None else _person(reviewer, "reviewer")
        normalized_methodology = _methodology(methodology)
        normalized_evidence = _evidence(evidence)
        normalized_limitations = _limitations(limitations)
        normalized_faq = _faq(faq)
        evidence_refs = {item["ref"] for item in normalized_evidence}
        for item in normalized_faq:
            if not set(item["evidence_refs"]).issubset(evidence_refs):
                raise SitePageError("INVALID_SITE_PAGE", "faq evidence references must point to page evidence")
        normalized_content = _visible_content(visible_content)
        normalized_sources = _uuid_array(source_snapshot_refs, "source_snapshot_refs")
        normalized_summary = _text(summary, "summary", maximum=10000, required=False)
        normalized_title = _text(title, "title", maximum=512)
        normalized_updated = _time(updated_at, "updated_at", default=self._now())
        normalized_published = None if published_at is None else _time(published_at, "published_at")
        if normalized_published is not None:
            raise SitePageError("INVALID_SITE_PAGE_STATE", "draft page versions cannot have published_at")

        with self._lock:
            page = self._resolve_page(tenant, normalized_key, site_page_id)
            if page is not None:
                normalized_key = page["page_key"]
                if normalized_locale != page["locale"] or normalized_path != page["url_path"]:
                    raise SitePageError("PAGE_IDENTITY_CONFLICT", "locale and canonical URL cannot change for a page")
            elif normalized_key is None:
                raise SitePageError("INVALID_SITE_PAGE", "page_key is required when site_page_id is unknown")
            else:
                page = {
                    "id": str(uuid4()),
                    "org_id": tenant,
                    "page_key": normalized_key,
                    "locale": normalized_locale,
                    "url_path": normalized_path,
                    "current_version_id": None,
                    "created_by": actor,
                    "created_at": self._now(),
                    "updated_at": self._now(),
                }

            body = {
                "command": "create_site_page_version",
                "page_key": normalized_key,
                "site_page_id": page["id"],
                "version_no": version_no,
                "expected_previous_version": expected_previous_version,
                "canonical_content_version_id": canonical_id,
                "variant_version_id": variant_id,
                "region_profile_version_id": region_id,
                "locale": normalized_locale,
                "url_path": normalized_path,
                "render_mode": render_mode,
                "title": normalized_title,
                "summary": normalized_summary,
                "author": normalized_author,
                "reviewer": normalized_reviewer,
                "updated_at": normalized_updated,
                "methodology": normalized_methodology,
                "evidence": normalized_evidence,
                "limitations": normalized_limitations,
                "faq": normalized_faq,
                "visible_content": normalized_content,
                "source_snapshot_refs": normalized_sources,
            }
            request_hash = _hash(body)
            prior = self.repository.get_command(org_id=tenant, idempotency_key=key)
            if prior is not None:
                if prior.get("request_hash") != request_hash:
                    raise SitePageError("IDEMPOTENCY_KEY_REUSED", "command payload differs from prior request")
                return deepcopy(dict(prior["response"]))

            self._validate_source(tenant, canonical_id, self.canonical_version_port, "canonical", {"approved"})
            if variant_id is not None:
                self._validate_source(tenant, variant_id, self.variant_version_port, "variant", {"approved"})
            self._validate_source(tenant, region_id, self.region_version_port, "region", {"active"})

            previous = list(self.repository.list_versions(org_id=tenant, site_page_id=page["id"]))
            current = max((int(item["version_no"]) for item in previous), default=0)
            if expected_previous_version != current or version_no != current + 1:
                raise SitePageError("VERSION_CONFLICT", "expected_previous_version or version_no is stale")
            if any(item.get("snapshot_hash") == "" for item in previous):
                raise SitePageError("VERSION_CONFLICT", "invalid prior page version")

            created_at = self._now()
            snapshot_material = {key: value for key, value in body.items() if key not in {"command", "expected_previous_version"}}
            snapshot_hash = _hash(snapshot_material)
            version = {
                "id": str(uuid4()),
                "org_id": tenant,
                "site_page_id": page["id"],
                "page_key": normalized_key,
                "version_no": version_no,
                "canonical_content_version_id": canonical_id,
                "variant_version_id": variant_id,
                "locale": normalized_locale,
                "region_profile_version_id": region_id,
                "url_path": normalized_path,
                "canonical_url": normalized_path,
                "render_mode": render_mode,
                "status": "draft",
                "title": normalized_title,
                "summary": normalized_summary,
                "author": normalized_author,
                "reviewer": normalized_reviewer,
                "updated_at": normalized_updated,
                "methodology": normalized_methodology,
                "evidence": normalized_evidence,
                "limitations": normalized_limitations,
                "faq": normalized_faq,
                "visible_content": normalized_content,
                "source_snapshot_refs": normalized_sources,
                "snapshot_hash": snapshot_hash,
                "published_at": None,
                "created_by": actor,
                "created_at": created_at,
            }
            try:
                VALIDATOR.validate(version)
            except ValidationError as exc:
                raise SitePageError("SITE_PAGE_CONTRACT_INVALID", "site page version failed its contract") from exc
            self.repository.save_page({**page, "current_version_id": version["id"], "updated_at": created_at})
            self.repository.save_version(version)
            response = {"page": {**page, "current_version_id": version["id"], "updated_at": created_at}, "version": deepcopy(version)}
            self.repository.save_command(org_id=tenant, idempotency_key=key, request_hash=request_hash, response=response)
            self.audit.append({
                "event_type": "site.page_version.created",
                "org_id": tenant,
                "actor_id": actor,
                "trace_id": trace,
                "subject_id": version["id"],
                "site_page_id": page["id"],
                "version_no": version_no,
                "snapshot_hash": snapshot_hash,
                "request_hash": request_hash,
            })
            return deepcopy(response)

    def get_version(self, *, org_id: UUID | str, version_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        identity = _uuid(version_id, "version_id")
        value = self.repository.get_version(org_id=tenant, version_id=identity)
        if value is None:
            raise SitePageError("TENANT_SCOPE_VIOLATION", "site page version is not in this organization")
        return deepcopy(dict(value))

    def list_versions(self, *, org_id: UUID | str, site_page_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        page_id = _uuid(site_page_id, "site_page_id")
        page = self.repository.get_page(org_id=tenant, page_id=page_id)
        if page is None:
            raise SitePageError("TENANT_SCOPE_VIOLATION", "site page is not in this organization")
        return tuple(deepcopy(dict(item)) for item in self.repository.list_versions(org_id=tenant, site_page_id=page_id))

    def get_page(self, *, org_id: UUID | str, page_id: UUID | str) -> dict[str, Any]:
        tenant = _uuid(org_id, "org_id")
        identity = _uuid(page_id, "page_id")
        page = self.repository.get_page(org_id=tenant, page_id=identity)
        if page is None:
            raise SitePageError("TENANT_SCOPE_VIOLATION", "site page is not in this organization")
        return {
            "page": deepcopy(dict(page)),
            "versions": [deepcopy(dict(item)) for item in self.repository.list_versions(org_id=tenant, site_page_id=identity)],
        }

    def audit_for(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        return tuple(deepcopy(item) for item in self.audit if item["org_id"] == tenant)

    def _resolve_page(self, tenant: str, page_key: str | None, page_id: object | None) -> Mapping[str, Any] | None:
        if page_id is not None:
            identity = _uuid(page_id, "site_page_id")
            page = self.repository.get_page(org_id=tenant, page_id=identity)
            if page is None:
                raise SitePageError("TENANT_SCOPE_VIOLATION", "site page is not in this organization")
            if page_key is not None and _page_key(page_key) != page["page_key"]:
                raise SitePageError("PAGE_IDENTITY_CONFLICT", "page_key does not match site_page_id")
            return page
        if page_key is None:
            return None
        return self.repository.get_page_by_key(org_id=tenant, page_key=page_key)

    @staticmethod
    def _validate_source(tenant: str, identity: str, port: Any | None, label: str, accepted: set[str]) -> None:
        if port is None:
            return
        try:
            if hasattr(port, "get_version"):
                value = port.get_version(org_id=tenant, version_id=identity)
            elif hasattr(port, "get"):
                value = port.get(org_id=tenant, version_id=identity)
            elif callable(port):
                value = port(org_id=tenant, version_id=identity)
            else:
                value = None
        except Exception as exc:
            raise SitePageError("TENANT_SCOPE_VIOLATION", f"{label} version is unavailable") from exc
        if not isinstance(value, Mapping) or str(value.get("org_id")) != tenant or str(value.get("id")) != identity:
            raise SitePageError("TENANT_SCOPE_VIOLATION", f"{label} version is not in this organization")
        if value.get("status") is not None and value.get("status") not in accepted:
            raise SitePageError("SOURCE_VERSION_NOT_READY", f"{label} version is not ready for a site page")

    def _now(self) -> str:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise SitePageError("INVALID_CLOCK", "clock must return a timezone-aware datetime")
        return _stamp(value)


__all__ = ["InMemorySitePageRepository", "SitePageError", "SitePageRepository", "SitePageService"]
