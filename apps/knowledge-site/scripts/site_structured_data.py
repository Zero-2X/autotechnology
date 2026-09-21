"""Deterministic JSON-LD projections for SITE-003.

The structured-data boundary consumes an already validated ``SitePageVersion``
snapshot and emits JSON-LD that describes the same visible page.  It is kept
free of SQL, network calls, credential access, and publishing side effects.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit
from uuid import UUID


_ALLOWED_SCHEMES = frozenset({"http", "https"})
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_HASH_RE = re.compile(r"^[A-Fa-f0-9]{64}$")
_RENDERABLE = frozenset({"ready", "published"})
_VIDEO_TYPES = frozenset({"video", "videoobject", "video_asset"})
_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class StructuredDataError(ValueError):
    """Stable error code for SITE-003 generation commands."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class InMemoryStructuredDataStore:
    """Small command/audit port used by local tests and offline builds."""

    def __init__(self) -> None:
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def get_command(self, *, org_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        with self._lock:
            value = self.commands.get((org_id, idempotency_key))
            return None if value is None else deepcopy(value)

    def save_command(self, *, org_id: str, idempotency_key: str, request_hash: str, response: Mapping[str, Any]) -> None:
        with self._lock:
            key = (org_id, idempotency_key)
            if key in self.commands:
                raise StructuredDataError("IDEMPOTENCY_KEY_REUSED", "structured-data command already exists")
            self.commands[key] = {"request_hash": request_hash, "response": deepcopy(dict(response))}

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
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "input must be JSON serializable") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, required: bool = True, maximum: int = 4096) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} must be non-empty")
    if len(result) > maximum:
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} exceeds {maximum} characters")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} contains an invalid control character")
    return result


def _tenant(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StructuredDataError("INVALID_TENANT_CONTEXT", "org_id must be non-empty text")
    result = value.strip()
    if len(result) > 128:
        raise StructuredDataError("INVALID_TENANT_CONTEXT", "org_id exceeds 128 characters")
    if any(char.isspace() for char in result):
        raise StructuredDataError("INVALID_TENANT_CONTEXT", "org_id cannot contain whitespace")
    return result


def _uuid_or_text(value: Any, field: str, *, maximum: int = 256) -> str:
    """Accept SITE-001 UUIDs and deterministic local fixture identifiers."""

    result = _text(value, field, maximum=maximum)
    try:
        return str(UUID(result))
    except (ValueError, AttributeError):
        return result


def _locale(value: Any) -> str:
    result = _text(value, "locale", maximum=32)
    if not _LOCALE_RE.fullmatch(result):
        raise StructuredDataError("INVALID_LOCALE", "locale must use a BCP-47-like form")
    pieces = result.split("-")
    normalized = [pieces[0].lower()]
    normalized.extend(piece.title() if len(piece) == 4 and piece.isalpha() else piece.upper() if len(piece) in {2, 3} else piece for piece in pieces[1:])
    return "-".join(normalized)


def _time(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} must be ISO-8601") from exc
    elif default is not None:
        parsed = default
    else:
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _origin(value: Any) -> str:
    result = _text(value, "base_origin", maximum=512)
    parsed = urlsplit(result)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise StructuredDataError("INVALID_ORIGIN", "base_origin must use http or https and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise StructuredDataError("INVALID_ORIGIN", "base_origin must not include credentials, path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise StructuredDataError("INVALID_ORIGIN", "base_origin has an invalid port") from exc
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def _absolute(origin: str, value: Any, field: str = "canonical_url") -> str:
    result = _text(value, field, maximum=2048)
    parsed = urlsplit(result)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise StructuredDataError("INVALID_CANONICAL_URL", f"{field} must be a same-origin URL")
        try:
            supplied_origin = _origin(f"{parsed.scheme}://{parsed.netloc}")
        except StructuredDataError as exc:
            raise StructuredDataError("INVALID_CANONICAL_URL", f"{field} has an invalid origin") from exc
        if supplied_origin != origin:
            raise StructuredDataError("CANONICAL_ORIGIN_MISMATCH", f"{field} is outside base_origin")
        path = parsed.path or "/"
    else:
        if not result.startswith("/") or "?" in result or "#" in result:
            raise StructuredDataError("INVALID_CANONICAL_URL", f"{field} must be an absolute path without query or fragment")
        path = result
    if _PERCENT_RE.search(path) or "//" in path or any(ord(char) < 0x21 for char in path):
        raise StructuredDataError("INVALID_CANONICAL_URL", f"{field} contains invalid path syntax")
    decoded = unquote(path)
    if ("//" in decoded or any(part in {".", ".."} for part in decoded.split("/"))
            or "\\" in decoded or any(ord(char) < 0x21 or ord(char) == 0x7F for char in decoded)
            or any(char in "?#" for char in decoded)):
        raise StructuredDataError("INVALID_CANONICAL_URL", f"{field} cannot contain traversal segments")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return origin + path


def _safe_url(value: Any, field: str, *, origin: str | None = None) -> str:
    result = _text(value, field, maximum=2048)
    parsed = urlsplit(result)
    if not parsed.scheme and not parsed.netloc and origin is not None:
        return _absolute(origin, result, field)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname or parsed.username or parsed.password:
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} must be an http(s) URL")
    return result


def _unwrap_page(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "page_version must be an object")
    for key in ("page_version", "site_page_version", "version"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            result = dict(nested)
            for carry in ("page", "organization", "site_identity"):
                if carry in value and carry not in result:
                    result[carry] = value[carry]
            return result
    result = dict(value)
    if isinstance(result.get("version"), Mapping):
        result = dict(result["version"])
    return result


def _extract_page(page_version: Mapping[str, Any] | None, predecessor_artifacts: Any) -> dict[str, Any]:
    if page_version is not None:
        return _unwrap_page(page_version)
    source = predecessor_artifacts
    if isinstance(source, Mapping):
        for key in ("page_version", "site_page_version", "version"):
            if isinstance(source.get(key), Mapping):
                return _unwrap_page(source[key])
        manifest = source.get("manifest")
        if isinstance(manifest, Mapping) and isinstance(manifest.get("page_version"), Mapping):
            return _unwrap_page(manifest["page_version"])
        if isinstance(source.get("pages"), Sequence) and source.get("pages"):
            first = source["pages"][0]
            if isinstance(first, Mapping):
                return _unwrap_page(first)
        return _unwrap_page(source)
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes)) and source and isinstance(source[0], Mapping):
        return _unwrap_page(source[0])
    raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "page_version or predecessor_artifacts is required")


def _person(value: Any, field: str, *, origin: str, tenant: str) -> tuple[dict[str, Any], str]:
    if not isinstance(value, Mapping):
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field} must be an object")
    nested_tenant = value.get("org_id", value.get("tenant_id"))
    if nested_tenant is not None and _tenant(nested_tenant) != tenant:
        raise StructuredDataError("TENANT_SCOPE_VIOLATION", f"{field} is outside this organization")
    identity = _uuid_or_text(value.get("id", value.get("ref")), f"{field}.id")
    name = _text(value.get("name"), f"{field}.name", maximum=256)
    supplied_url = value.get("url")
    url = None if supplied_url is None else _safe_url(supplied_url, f"{field}.url", origin=origin)
    person_id = url or f"{origin}/#person-{_hash({'org_id': tenant, 'id': identity})[:20]}"
    node: dict[str, Any] = {"@type": "Person", "@id": person_id, "name": name}
    if url:
        node["url"] = url
    same_as = value.get("sameAs", value.get("same_as"))
    if same_as is not None:
        if isinstance(same_as, (str, bytes)) or not isinstance(same_as, Sequence):
            raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", f"{field}.sameAs must be an array")
        node["sameAs"] = sorted({_safe_url(item, f"{field}.sameAs[]") for item in same_as})
    return node, person_id


def _visible_body(page: Mapping[str, Any]) -> str:
    rows: list[str] = []
    visible = page.get("visible_content")
    if isinstance(visible, Mapping):
        blocks = visible.get("blocks", [])
        if isinstance(blocks, Sequence) and not isinstance(blocks, (str, bytes)):
            for item in blocks:
                if isinstance(item, Mapping):
                    text = item.get("text", item.get("content"))
                else:
                    text = item
                if text is not None:
                    rows.append(_text(text, "visible_content.blocks.text", maximum=20000))
    elif isinstance(visible, str):
        rows.append(_text(visible, "visible_content", maximum=20000))
    # These fields are rendered visibly by SITE-002.  Include them in the
    # article body so structured data cannot silently omit visible material.
    methodology = page.get("methodology")
    steps = methodology.get("steps", []) if isinstance(methodology, Mapping) else methodology
    if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)):
        rows.extend(_text(item, "methodology.steps[]", maximum=2000) for item in steps)
    limitations = page.get("limitations", [])
    if isinstance(limitations, Sequence) and not isinstance(limitations, (str, bytes)):
        for item in limitations:
            rows.append(_text(item.get("text", item.get("description", "")) if isinstance(item, Mapping) else item, "limitations[]", maximum=2000))
    faq = page.get("faq", [])
    if isinstance(faq, Sequence) and not isinstance(faq, (str, bytes)):
        for item in faq:
            if isinstance(item, Mapping):
                rows.append(_text(item.get("question"), "faq.question", maximum=1000))
                rows.append(_text(item.get("answer"), "faq.answer", maximum=10000))
    return "\n\n".join(row for row in rows if row)


def _article_type(page: Mapping[str, Any], requested: Any) -> str:
    value = requested if requested is not None else page.get("article_type", page.get("content_type"))
    if value is None and page.get("is_technical") is True:
        value = "TechArticle"
    if value is None:
        value = "Article"
    normalized = str(value).strip().lower().replace("_", "")
    if normalized in {"article", "newsarticle", "blogposting"}:
        return "Article"
    if normalized in {"techarticle", "technicalarticle"}:
        return "TechArticle"
    raise StructuredDataError("INVALID_ARTICLE_TYPE", "article_type must be Article or TechArticle")


def _phase(value: Any) -> int:
    if value is None:
        return 5
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "phase must be a positive integer")
    return value


class SiteStructuredDataService:
    """Generate tenant-scoped, deterministic JSON-LD for a site page."""

    renderer_version = "site-003.v1"

    def __init__(self, *, clock: Callable[[], datetime] | None = None, store: InMemoryStructuredDataStore | None = None):
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = store or InMemoryStructuredDataStore()
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def generate(
        self,
        *,
        page_version: Mapping[str, Any] | None = None,
        version: Mapping[str, Any] | None = None,
        predecessor_artifacts: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        org_id: str | None = None,
        actor_id: str | None = None,
        trace_id: str | None = None,
        base_origin: str | None = None,
        organization: Mapping[str, Any] | None = None,
        site_identity: Mapping[str, Any] | None = None,
        article_type: str | None = None,
        phase: int = 5,
        video_asset: Mapping[str, Any] | None = None,
        approved_video_asset: Mapping[str, Any] | None = None,
        policy_snapshot: Any = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        page_arg = page_version if page_version is not None else version
        source_ids: list[str] = []
        context_org = tenant_context.get("org_id") if isinstance(tenant_context, Mapping) else None
        context_trace = tenant_context.get("trace_id") if isinstance(tenant_context, Mapping) else None
        tenant_for_audit = str(org_id or context_org or "unknown")
        try:
            if tenant_context is not None and not isinstance(tenant_context, Mapping):
                raise StructuredDataError("INVALID_TENANT_CONTEXT", "tenant_context must be an object")
            page = _extract_page(page_arg, predecessor_artifacts)
            if page.get("id") is not None:
                source_ids.append(_text(page["id"], "page_version.id", maximum=256))
            context = dict(tenant_context or {})
            inferred = page.get("org_id")
            tenant = _tenant(org_id if org_id is not None else context.get("org_id", inferred))
            tenant_for_audit = tenant
            nested_org = page.get("org_id")
            if nested_org is not None and _tenant(nested_org) != tenant:
                raise StructuredDataError("TENANT_SCOPE_VIOLATION", "page version is outside this organization")
            actor_value = actor_id if actor_id is not None else context.get("actor_id")
            actor = None if actor_value is None else _uuid_or_text(actor_value, "actor_id")
            trace_value = trace_id if trace_id is not None else context.get("trace_id")
            trace = "site-structured-data" if trace_value is None else _text(trace_value, "trace_id", maximum=256)
            phase_value = _phase(phase)
            status = _text(page.get("status"), "page_version.status", maximum=32).lower()
            if status not in _RENDERABLE:
                raise StructuredDataError("PAGE_NOT_RENDERABLE", "JSON-LD requires a ready or published page version")
            origin = None
            raw_canonical = page.get("canonical_url", page.get("url_path"))
            if base_origin is not None:
                origin = _origin(base_origin)
                canonical = _absolute(origin, raw_canonical, "canonical_url")
                raw_path = page.get("url_path")
                if raw_path is not None and _absolute(origin, raw_path, "url_path") != canonical:
                    raise StructuredDataError("CANONICAL_URL_MISMATCH", "canonical_url must match url_path")
            else:
                parsed = urlsplit(_text(raw_canonical, "canonical_url", maximum=2048))
                if not parsed.scheme or not parsed.netloc:
                    raise StructuredDataError("INVALID_ORIGIN", "base_origin is required for relative canonical URLs")
                origin = _origin(f"{parsed.scheme}://{parsed.netloc}")
                canonical = _absolute(origin, raw_canonical, "canonical_url")
            locale = _locale(page.get("locale", "en-US"))
            title = _text(page.get("title"), "title", maximum=512)
            summary = _text(page.get("summary", ""), "summary", required=False, maximum=10000)
            updated = _time(page.get("updated_at"), "updated_at")
            published_value = page.get("published_at")
            published = None if published_value in (None, "") else _time(published_value, "published_at")
            page_id = _uuid_or_text(page.get("id", page.get("version_id")), "page_version.id")
            snapshot = page.get("snapshot_hash")
            if snapshot is None:
                snapshot = _hash(page)
            elif not isinstance(snapshot, str) or not _HASH_RE.fullmatch(snapshot):
                raise StructuredDataError("INVALID_SNAPSHOT_HASH", "page version snapshot_hash must be SHA-256")
            snapshot = snapshot.lower()
            selected_article_type = _article_type(page, article_type)
            identity = organization if organization is not None else site_identity
            if identity is None and isinstance(page.get("organization"), Mapping):
                identity = page["organization"]
            org_node, org_ref = self._organization(identity, origin=origin, tenant=tenant)
            author_node, author_ref = _person(page.get("author"), "author", origin=origin, tenant=tenant)
            reviewer_ref = None
            reviewer_node = None
            if page.get("reviewer") is not None:
                reviewer_node, reviewer_ref = _person(page["reviewer"], "reviewer", origin=origin, tenant=tenant)
            body = _visible_body(page)
            if not body:
                raise StructuredDataError("VISIBLE_CONTENT_REQUIRED", "page version must contain visible article content")
            article_ref = f"{canonical}#article"
            article: dict[str, Any] = {
                "@type": selected_article_type,
                "@id": article_ref,
                "url": canonical,
                "mainEntityOfPage": {"@id": canonical},
                "headline": title,
                "inLanguage": locale,
                "dateModified": _stamp(updated),
                "author": {"@id": author_ref},
                "publisher": {"@id": org_ref},
                "articleBody": body,
            }
            if summary:
                article["description"] = summary
            if published is not None:
                article["datePublished"] = _stamp(published)
            if reviewer_ref is not None:
                article["reviewedBy"] = {"@id": reviewer_ref}
            keywords = page.get("keywords", page.get("about_keywords"))
            if keywords is not None:
                if isinstance(keywords, (str, bytes)) or not isinstance(keywords, Sequence):
                    raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "keywords must be an array")
                article["keywords"] = sorted({_text(item, "keywords[]", maximum=128) for item in keywords})
            graph: list[dict[str, Any]] = [article, org_node, author_node]
            if reviewer_node is not None and reviewer_node["@id"] != author_node["@id"]:
                graph.append(reviewer_node)
            selected_video = approved_video_asset if approved_video_asset is not None else video_asset
            video_node = self._video(selected_video, phase=phase_value, tenant=tenant, origin=origin, article=article)
            if video_node is not None:
                article["video"] = {"@id": video_node["@id"]}
                graph.append(video_node)
            document = {"@context": "https://schema.org", "@graph": graph}
            # Escaping '<', '>', and '&' keeps JSON safe inside a script element
            # while preserving the decoded JSON-LD object exactly.
            jsonld_text = _canonical(document).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            script = f'<script type="application/ld+json">{jsonld_text}</script>'
            request = {
                "org_id": tenant, "base_origin": origin, "page": page,
                "organization": identity, "article_type": selected_article_type,
                "phase": phase_value, "video_asset": selected_video,
                "policy_snapshot": policy_snapshot, "actor_id": actor, "trace_id": trace,
                "renderer_version": self.renderer_version,
            }
            request_hash = _hash(request)
            idem = None
            if idempotency_key is not None:
                idem = _text(idempotency_key, "idempotency_key", maximum=200)
                if len(idem) < 2:
                    raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "idempotency_key length must be 2..200")
                prior = self.store.get_command(org_id=tenant, idempotency_key=idem)
                if prior is not None:
                    if prior.get("request_hash") != request_hash:
                        raise StructuredDataError("IDEMPOTENCY_KEY_REUSED", "structured-data payload differs from prior request")
                    return deepcopy(dict(prior["response"]))
            generated_at = _stamp(_time(self.clock(), "generated_at"))
            output_hash = _hash({
                "jsonld": jsonld_text,
                "script": script,
                "snapshot_hash": snapshot,
                "renderer_version": self.renderer_version,
            })
            audit = {
                "event_type": "site.structured_data.generated",
                "org_id": tenant,
                "actor_id": actor,
                "trace_id": trace,
                "input_version_ids": [page_id],
                "source_snapshot_hash": snapshot,
                "request_hash": request_hash,
                "output_hash": output_hash,
                "renderer_version": self.renderer_version,
                "policy_snapshot": policy_snapshot,
                "video_included": video_node is not None,
                "status": "succeeded",
                "generated_at": generated_at,
                "duration_ms": 0,
                "cost": 0,
            }
            manifest = {
                "schema_version": "site-003.v1",
                "org_id": tenant,
                "site_page_version_id": page_id,
                "canonical_url": canonical,
                "locale": locale,
                "source_snapshot_hash": snapshot,
                "renderer_version": self.renderer_version,
                "article_type": selected_article_type,
                "node_types": [str(node["@type"]) for node in graph],
                "video_included": video_node is not None,
                "generated_at": generated_at,
                "request_hash": request_hash,
                "hash": output_hash,
            }
            result = {
                "schema_version": "site-003.v1",
                "org_id": tenant,
                "site_page_version_id": page_id,
                "canonical_url": canonical,
                "locale": locale,
                "source_snapshot_hash": snapshot,
                "renderer_version": self.renderer_version,
                "article_type": selected_article_type,
                "video_included": video_node is not None,
                "generated_at": generated_at,
                "request_hash": request_hash,
                "hash": output_hash,
                "jsonld": document,
                "jsonld_text": jsonld_text,
                "script": script,
                "manifest": manifest,
                "audit_evidence": audit,
            }
            with self._lock:
                self.audit.append(deepcopy(audit))
                self.store.append_audit(audit)
                if idem is not None:
                    self.store.save_command(org_id=tenant, idempotency_key=idem, request_hash=request_hash, response=result)
            return deepcopy(result)
        except StructuredDataError as exc:
            rejection = {
                "event_type": "site.structured_data.rejected",
                "org_id": tenant_for_audit,
                "trace_id": str(trace_id or context_trace or "site-structured-data"),
                "input_version_ids": source_ids,
                "error_code": exc.code,
                "status": "rejected",
            }
            with self._lock:
                self.audit.append(deepcopy(rejection))
                self.store.append_audit(rejection)
            raise

    # Public aliases make the application port easy to integrate without
    # creating several subtly different implementations.
    generate_jsonld = generate
    render = generate
    build = generate

    def audit_for(self, *, org_id: str) -> tuple[dict[str, Any], ...]:
        tenant = _tenant(org_id)
        return tuple(deepcopy(row) for row in self.audit if row.get("org_id") == tenant)

    @staticmethod
    def _organization(identity: Mapping[str, Any] | None, *, origin: str, tenant: str) -> tuple[dict[str, Any], str]:
        if identity is not None and not isinstance(identity, Mapping):
            raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "organization must be an object")
        value = dict(identity or {})
        nested_tenant = value.get("org_id", value.get("tenant_id"))
        if nested_tenant is not None and _tenant(nested_tenant) != tenant:
            raise StructuredDataError("TENANT_SCOPE_VIOLATION", "organization is outside this organization")
        name = _text(value.get("name", value.get("legal_name", "Knowledge Site")), "organization.name", maximum=512)
        raw_url = value.get("url", origin + "/")
        url = _safe_url(raw_url, "organization.url", origin=origin)
        org_ref = value.get("@id", value.get("id"))
        if org_ref is None:
            org_ref = origin + "/#organization"
        else:
            org_ref = _safe_url(org_ref, "organization.id") if str(org_ref).startswith(("http://", "https://")) else f"{origin}/#organization-{_hash({'org_id': tenant, 'id': str(org_ref)})[:20]}"
        node: dict[str, Any] = {"@type": "Organization", "@id": org_ref, "name": name, "url": url, "identifier": tenant}
        if value.get("logo") is not None:
            node["logo"] = _safe_url(value["logo"], "organization.logo", origin=origin)
        same_as = value.get("sameAs", value.get("same_as"))
        if same_as is not None:
            if isinstance(same_as, (str, bytes)) or not isinstance(same_as, Sequence):
                raise StructuredDataError("INVALID_STRUCTURED_DATA_INPUT", "organization.sameAs must be an array")
            node["sameAs"] = sorted({_safe_url(item, "organization.sameAs[]") for item in same_as})
        return node, org_ref

    @staticmethod
    def _video(value: Mapping[str, Any] | None, *, phase: int, tenant: str, origin: str, article: Mapping[str, Any]) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, Mapping):
            raise StructuredDataError("INVALID_VIDEO_ASSET", "video_asset must be an object")
        nested_tenant = value.get("org_id", value.get("tenant_id"))
        if nested_tenant is not None and _tenant(nested_tenant) != tenant:
            raise StructuredDataError("TENANT_SCOPE_VIOLATION", "video asset is outside this organization")
        asset_phase = value.get("phase", value.get("stage", phase))
        if isinstance(asset_phase, bool) or not isinstance(asset_phase, int):
            raise StructuredDataError("INVALID_VIDEO_ASSET", "video asset phase must be an integer")
        status = str(value.get("status", value.get("approval_status", ""))).strip().lower()
        kind = str(value.get("type", value.get("asset_type", "video"))).strip().lower()
        approved = value.get("approved") is True or status == "approved"
        if phase < 6 or asset_phase < 6 or kind not in _VIDEO_TYPES or not approved:
            return None
        if nested_tenant is None:
            raise StructuredDataError("INVALID_VIDEO_ASSET", "approved video asset requires org_id")
        url_value = value.get("contentUrl", value.get("content_url", value.get("url")))
        if url_value is None:
            raise StructuredDataError("INVALID_VIDEO_ASSET", "approved video asset requires contentUrl")
        content_url = _safe_url(url_value, "video_asset.contentUrl")
        video_id = value.get("@id", value.get("id"))
        if video_id is None:
            video_id = f"{article['@id']}#video"
        elif str(video_id).startswith(("http://", "https://")):
            video_id = _safe_url(video_id, "video_asset.id")
        else:
            video_id = f"{origin}/#video-{_hash({'org_id': tenant, 'id': str(video_id)})[:20]}"
        name = _text(value.get("name", article.get("headline", "Video")), "video_asset.name", maximum=512)
        description = _text(value.get("description", ""), "video_asset.description", required=False, maximum=4000)
        node: dict[str, Any] = {"@type": "VideoObject", "@id": video_id, "name": name, "contentUrl": content_url, "uploadDate": _stamp(_time(value.get("uploadDate", value.get("uploaded_at")), "video_asset.uploadDate"))}
        if description:
            node["description"] = description
        for source, target in (("embedUrl", "embedUrl"), ("thumbnailUrl", "thumbnailUrl")):
            if value.get(source) is not None:
                node[target] = _safe_url(value[source], f"video_asset.{source}")
        if value.get("duration") is not None:
            node["duration"] = _text(value["duration"], "video_asset.duration", maximum=64)
        return node


__all__ = ["InMemoryStructuredDataStore", "SiteStructuredDataService", "StructuredDataError"]
