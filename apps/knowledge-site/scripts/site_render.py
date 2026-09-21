"""Deterministic SSR/feed projections for SITE-002.

This module is a pure application boundary.  It consumes approved
SitePageVersion mappings and emits HTML/XML/text artifacts without SQL,
network access, or JSON-LD.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from email.utils import format_datetime
from hashlib import sha256
import html
import json
import re
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit
from xml.sax.saxutils import escape as xml_escape

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_RENDERABLE = frozenset({"ready", "published"})
_RESERVED = frozenset({"/api", "/internal", "/admin", "/health", "/robots.txt", "/sitemap.xml"})
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
_PERCENT_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class SiteRenderError(ValueError):
    """Stable error code for SITE-002 render commands."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class InMemorySiteRenderStore:
    """Optional in-memory command/audit port for idempotent local builds."""

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
                raise SiteRenderError("IDEMPOTENCY_KEY_REUSED", "render command already exists")
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
        raise SiteRenderError("INVALID_RENDER_INPUT", "render input must be JSON serializable") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, field: str, *, required: bool = True, maximum: int = 20000) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} must be non-empty")
    if len(result) > maximum:
        raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} exceeds {maximum} characters")
    if any(ord(c) < 0x20 and c not in "\t\n\r" for c in result):
        raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} contains an invalid control character")
    return result


def _tenant(value: Any) -> str:
    result = _text(value, "org_id", maximum=128)
    if any(c.isspace() for c in result):
        raise SiteRenderError("INVALID_TENANT_CONTEXT", "org_id cannot contain whitespace")
    return result


def _locale(value: Any) -> str:
    result = _text(value, "locale", maximum=32)
    if not _LOCALE_RE.fullmatch(result):
        raise SiteRenderError("INVALID_LOCALE", "locale must use a BCP-47-like form")
    parts = result.split("-")
    out = [parts[0].lower()]
    for part in parts[1:]:
        out.append(part.title() if len(part) == 4 and part.isalpha() else part.upper() if len(part) in {2, 3} else part)
    return "-".join(out)


def _time(value: Any, field: str = "updated_at") -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} must be an ISO-8601 timestamp") from exc
    else:
        parsed = datetime(1970, 1, 1, tzinfo=timezone.utc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _origin(value: Any) -> str:
    result = _text(value, "base_origin", maximum=512)
    parsed = urlsplit(result)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise SiteRenderError("INVALID_ORIGIN", "base_origin must use http or https and include a host")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise SiteRenderError("INVALID_ORIGIN", "base_origin must be an origin without credentials, path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SiteRenderError("INVALID_ORIGIN", "base_origin has an invalid port") from exc
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}" + (f":{port}" if port is not None else "")


def _path(value: Any, *, origin: str, field: str = "url_path") -> str:
    result = _text(value, field, maximum=2048)
    parsed = urlsplit(result)
    if parsed.scheme or parsed.netloc:
        # SITE-001 stores canonical_url as a relative path.  Reject absolute
        # values so a caller cannot accidentally bypass origin normalization.
        raise SiteRenderError("INVALID_CANONICAL_URL", f"{field} must be a relative path")
    if not result.startswith("/") or "?" in result or "#" in result or _PERCENT_RE.search(result):
        raise SiteRenderError("INVALID_CANONICAL_URL", f"{field} must be an absolute path without query or fragment")
    if any(ord(c) < 0x21 for c in result) or "//" in result:
        raise SiteRenderError("INVALID_CANONICAL_URL", f"{field} contains whitespace or duplicate slashes")
    decoded = unquote(result)
    if ("//" in decoded or any(part in {".", ".."} for part in decoded.split("/"))
            or any(ord(char) < 0x21 or ord(char) == 0x7F for char in decoded)
            or any(char in "?#\\" for char in decoded)):
        raise SiteRenderError("INVALID_CANONICAL_URL", f"{field} cannot contain traversal segments")
    if result != "/" and result.endswith("/"):
        result = result[:-1]
    if result in _RESERVED or any(result.startswith(item + "/") for item in _RESERVED):
        raise SiteRenderError("INVALID_CANONICAL_URL", f"{field} is reserved for an application endpoint")
    return result


def _absolute(origin: str, path: str) -> str:
    return origin + (path if path.startswith("/") else "/" + path)


def _html(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _xml(value: Any) -> str:
    return xml_escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _unwrap(value: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value.get("version"), Mapping):
        result = dict(value["version"])
        page = value.get("page")
        if isinstance(page, Mapping):
            for key in ("page_key", "locale", "url_path", "org_id"):
                if key not in result and key in page:
                    result[key] = page[key]
            if "site_page_id" not in result and page.get("id") is not None:
                result["site_page_id"] = page["id"]
        return result
    return dict(value)


def _identity(page: Mapping[str, Any], *, path: str, locale: str) -> str:
    value = page.get("id", page.get("version_id"))
    if value is not None:
        return _text(value, "page_version.id", maximum=256)
    return "derived-" + _hash({"path": path, "locale": locale, "title": page.get("title", "")})[:24]


def _version_no(value: Any) -> int:
    if type(value) is not int or value < 1:
        raise SiteRenderError("INVALID_RENDER_INPUT", "version_no must be a positive integer")
    return value


class SiteRenderService:
    """Render tenant-scoped page versions into deterministic public artifacts."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        store: InMemorySiteRenderStore | None = None,
        eligibility_port: Any = None,
        region_filter: Any = None,
    ):
        if eligibility_port is not None and region_filter is not None and eligibility_port is not region_filter:
            raise SiteRenderError("INVALID_RENDER_INPUT", "configure only one eligibility filter port")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.store = store or InMemorySiteRenderStore()
        self.eligibility_port = eligibility_port if eligibility_port is not None else region_filter
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def render_page(
        self,
        *,
        page_version: Mapping[str, Any] | None = None,
        version: Mapping[str, Any] | None = None,
        org_id: str | None = None,
        base_origin: str,
        locale_variants: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        default_locale: str | None = None,
        x_default_locale: str | None = None,
        x_default_url: str | None = None,
        site_title: str = "Knowledge Site",
        site_description: str = "",
        actor_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        eligibility_port: Any = None,
        region_filter: Any = None,
        eligibility_evaluated_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        selected = page_version if page_version is not None else version
        if selected is None:
            raise SiteRenderError("INVALID_RENDER_INPUT", "page_version is required")
        return self.render_site(
            page_versions=[selected], org_id=org_id, base_origin=base_origin,
            locale_variants=locale_variants, default_locale=default_locale,
            x_default_locale=x_default_locale, x_default_url=x_default_url,
            site_title=site_title, site_description=site_description,
            actor_id=actor_id, trace_id=trace_id, idempotency_key=idempotency_key,
            eligibility_port=eligibility_port, region_filter=region_filter,
            eligibility_evaluated_at=eligibility_evaluated_at,
            _single_page=True,
        )

    def render_site(
        self,
        *,
        page_versions: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        pages: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        versions: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        org_id: str | None = None,
        base_origin: str,
        locale_variants: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        default_locale: str | None = None,
        x_default_locale: str | None = None,
        x_default_url: str | None = None,
        site_title: str = "Knowledge Site",
        site_description: str = "",
        actor_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        eligibility_port: Any = None,
        region_filter: Any = None,
        eligibility_evaluated_at: datetime | str | None = None,
        _single_page: bool = False,
    ) -> dict[str, Any]:
        if eligibility_port is not None and region_filter is not None and eligibility_port is not region_filter:
            raise SiteRenderError("INVALID_RENDER_INPUT", "configure only one eligibility filter port")
        configured_filter = eligibility_port if eligibility_port is not None else region_filter
        if configured_filter is None:
            configured_filter = self.eligibility_port
        origin = _origin(base_origin)
        normalized_default = None if default_locale is None else _locale(default_locale)
        normalized_x_default = None if x_default_locale is None else _locale(x_default_locale)
        raw = page_versions if page_versions is not None else pages if pages is not None else versions
        raw_items = self._coerce(raw if raw is not None else [])
        raw_items += self._variants(locale_variants)
        if not raw_items and _single_page:
            raise SiteRenderError("INVALID_RENDER_INPUT", "page_version is required")
        inferred = next(
            (
                str(item.get("org_id"))
                if item.get("org_id") is not None
                else str(item["version"].get("org_id"))
                for item in raw_items
                if isinstance(item, Mapping)
                and (item.get("org_id") is not None or isinstance(item.get("version"), Mapping) and item["version"].get("org_id") is not None)
            ),
            None,
        )
        tenant = _tenant(org_id if org_id is not None else inferred) if (org_id is not None or inferred is not None) else None
        if tenant is None:
            raise SiteRenderError("INVALID_TENANT_CONTEXT", "org_id is required when page versions have no tenant")
        pages_n = [self._normalize(item, tenant=tenant, origin=origin) for item in raw_items]
        primary_source = pages_n[0]["id"] if pages_n else None
        eligibility_evidence: list[dict[str, str]] = []
        if configured_filter is not None:
            pages_n, eligibility_evidence = self._filter_region_pages(
                pages_n,
                port=configured_filter,
                tenant=tenant,
                evaluated_at=eligibility_evaluated_at,
                actor_id=actor_id,
                trace_id=trace_id,
            )
        # A route may have historical drafts/superseded rows.  Only public
        # states participate in selection; published wins over ready, then the
        # highest version_no wins.  A tie is an ambiguous public route.
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in pages_n:
            grouped.setdefault((item["group_key"], item["locale"]), []).append(item)
        selected: list[dict[str, Any]] = []
        for key, rows in grouped.items():
            public = [row for row in rows if row["status"] in _RENDERABLE]
            if not public:
                continue
            published = [row for row in public if row["status"] == "published"]
            pool = published or public
            highest = max(row["version_no"] for row in pool)
            winners = [row for row in pool if row["version_no"] == highest]
            if len(winners) > 1:
                hashes = {_hash(row["source"]) for row in winners}
                if len(hashes) > 1:
                    raise SiteRenderError("DUPLICATE_PUBLIC_ROUTE", "multiple public versions use the same page and locale")
            selected.append(sorted(winners, key=lambda row: (row["canonical_url"], row["id"]))[0])
        pages_n = sorted(selected, key=lambda p: (p["group_key"], p["locale"], p["canonical_url"], p["id"]))
        if not _single_page:
            primary_source = pages_n[0]["id"] if pages_n else None
        routes: dict[tuple[str, str], dict[str, Any]] = {}
        for item in pages_n:
            route = (item["locale"].casefold(), item["canonical_url"])
            prior_route = routes.get(route)
            if prior_route is not None and prior_route["group_key"] != item["group_key"]:
                raise SiteRenderError("DUPLICATE_PUBLIC_ROUTE", "multiple public pages use the same locale and URL")
            routes[route] = item
        if _single_page and (not pages_n or not any(item["id"] == primary_source for item in pages_n)):
            raise SiteRenderError("PAGE_NOT_RENDERABLE", "page version is not ready or published")
        selected_locales = {item["locale"].casefold() for item in pages_n}
        for label, value in (("default_locale", normalized_default), ("x_default_locale", normalized_x_default)):
            if configured_filter is None and value is not None and value.casefold() not in selected_locales:
                raise SiteRenderError("INVALID_LOCALE", f"{label} is not represented by a public page version")
        request = {"org_id": tenant, "base_origin": origin, "pages": [p["source"] for p in pages_n],
                   "default_locale": normalized_default, "x_default_locale": normalized_x_default,
                   "x_default_url": x_default_url, "site_title": site_title, "site_description": site_description}
        if configured_filter is not None:
            request["region_eligibility"] = eligibility_evidence
        request_hash = _hash(request)
        idem = None
        if idempotency_key is not None:
            idem = _text(idempotency_key, "idempotency_key", maximum=200)
            if len(idem) < 2:
                raise SiteRenderError("INVALID_RENDER_INPUT", "idempotency_key length must be 2..200")
            prior = self.store.get_command(org_id=tenant, idempotency_key=idem)
            if prior is not None:
                if prior.get("request_hash") != request_hash:
                    raise SiteRenderError("IDEMPOTENCY_KEY_REUSED", "render payload differs from prior request")
                return deepcopy(dict(prior["response"]))
        generated_at = _time(self.clock(), "generated_at")
        artifacts = self._artifacts(
            pages_n, origin=origin, default_locale=normalized_default,
            x_default_locale=normalized_x_default, x_default_url=x_default_url,
            title=_text(site_title, "site_title", maximum=512),
            description=_text(site_description, "site_description", required=False, maximum=4000),
            primary_id=primary_source,
            regional_default=configured_filter is not None,
        )
        hashes = {name: _hash(text) for name, text in artifacts.items()}
        sizes = {name: len(text.encode("utf-8")) for name, text in artifacts.items()}
        output_hash = _hash(hashes)
        published = [p for p in pages_n if p["status"] == "published"]
        short_hashes = {
            "html": hashes["html"], "sitemap": hashes["sitemap.xml"],
            "rss": hashes["rss.xml"], "atom": hashes["atom.xml"], "robots": hashes["robots.txt"],
        }
        generated = _stamp(generated_at)
        request_hash = request_hash
        publications = [self._publication(
            page, tenant=tenant, request_hash=request_hash,
            artifact_hashes=short_hashes, generated_at=generated,
            actor_id=actor_id, trace_id=trace_id, idempotency_key=idem,
            x_default_locale=normalized_x_default or normalized_default,
            hreflang=self._publication_links(page, pages_n, origin=origin,
                                              default_locale=normalized_default,
                                              x_default_locale=normalized_x_default,
                                              x_default_url=x_default_url,
                                              regional_default=configured_filter is not None),
        ) for page in pages_n]
        manifest = {
            "schema_version": "site-002.v1", "org_id": tenant, "base_origin": origin,
            "page_count": len(pages_n), "published_count": len(published),
            "page_version_ids": [p["id"] for p in pages_n], "artifact_hashes": short_hashes,
            "artifact_sizes": sizes, "hash": output_hash, "request_hash": request_hash,
            "renderer_version": "site-002.v1", "generated_at": generated,
            "publications": publications,
        }
        actor = None if actor_id is None else _text(actor_id, "actor_id", maximum=256)
        evidence = {
            "event_type": "site.render.completed", "org_id": tenant,
            "trace_id": "site-render" if trace_id is None else _text(trace_id, "trace_id", maximum=256),
            "actor_id": actor, "input_version_ids": [p["id"] for p in pages_n],
            "output_hash": output_hash, "published_count": len(published), "status": "succeeded",
        }
        result = {
            "org_id": tenant, "base_origin": origin, "artifacts": deepcopy(artifacts),
            "html": artifacts["html"], "sitemap": artifacts["sitemap.xml"],
            "rss": artifacts["rss.xml"], "atom": artifacts["atom.xml"], "robots": artifacts["robots.txt"],
            "sitemap_xml": artifacts["sitemap.xml"], "rss_xml": artifacts["rss.xml"],
            "atom_xml": artifacts["atom.xml"], "robots_txt": artifacts["robots.txt"],
            "hashes": deepcopy(hashes), "manifest": manifest, "manifest_hash": output_hash,
            "audit_evidence": evidence,
        }
        audit_row = {**evidence, "duration_ms": 0, "cost": 0, "policy_snapshot": "site-002.v1"}
        with self._lock:
            self.audit.append(deepcopy(audit_row))
            self.store.append_audit(audit_row)
            if idem is not None:
                self.store.save_command(org_id=tenant, idempotency_key=idem, request_hash=request_hash, response=result)
        return deepcopy(result)

    def render(self, **kwargs: Any) -> dict[str, Any]:
        return self.render_page(**kwargs) if kwargs.get("page_version") is not None or kwargs.get("version") is not None else self.render_site(**kwargs)

    def audit_for(self, *, org_id: str) -> tuple[dict[str, Any], ...]:
        tenant = _tenant(org_id)
        return tuple(deepcopy(row) for row in self.audit if row.get("org_id") == tenant)

    def _filter_region_pages(
        self,
        pages: Sequence[dict[str, Any]],
        *,
        port: Any,
        tenant: str,
        evaluated_at: datetime | str | None,
        actor_id: str | None,
        trace_id: str | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Fail closed before any page reaches a public artifact.

        The preferred port is ``check_page`` (the GEO_REGION-002 service).
        A batch ``filter_pages`` port is also accepted for deployment adapters.
        The renderer only consumes a decision; it never mutates the immutable
        page snapshot returned by SITE-001.
        """

        snapshots: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for page in pages:
            snapshot = deepcopy(dict(page["source"]))
            snapshot.update({
                "id": page["id"],
                "page_version_id": page["id"],
                "org_id": tenant,
                "page_key": page["group_key"],
                "locale": page["locale"],
                "canonical_url": page["canonical_url"],
                "status": page["status"],
            })
            snapshots.append((page, snapshot))

        batch = getattr(port, "filter_pages", None)
        if callable(batch):
            kwargs: dict[str, Any] = {"pages": [item for _, item in snapshots], "org_id": tenant}
            if evaluated_at is not None:
                kwargs["evaluated_at"] = _time(evaluated_at, "eligibility_evaluated_at")
            if actor_id is not None:
                kwargs["actor_id"] = actor_id
            if trace_id is not None:
                kwargs["trace_id"] = trace_id
            try:
                outcome = batch(**kwargs)
                if isinstance(outcome, Mapping):
                    outcome = outcome.get("eligible_pages", outcome.get("pages", outcome.get("allowed_ids", outcome)))
                if isinstance(outcome, Mapping):
                    allowed_ids = {str(key) for key, value in outcome.items() if value is True}
                elif isinstance(outcome, Sequence) and not isinstance(outcome, (str, bytes)):
                    allowed_ids = {
                        str(item.get("page_version_id", item.get("id"))) if isinstance(item, Mapping) else str(item)
                        for item in outcome
                    }
                else:
                    allowed_ids = set()
            except Exception:
                allowed_ids = set()
            kept = [page for page, _ in snapshots if page["id"] in allowed_ids]
            evidence = [
                {
                    "page_version_id": page["id"],
                    "region_profile_version_id": str(snapshot.get("region_profile_version_id", "")),
                    "decision": "eligible" if page["id"] in allowed_ids else "deny",
                    "status": "eligible" if page["id"] in allowed_ids else "blocked",
                }
                for page, snapshot in snapshots
            ]
            return kept, sorted(evidence, key=lambda item: item["page_version_id"])

        checker = getattr(port, "check_page", None)
        if not callable(checker):
            checker = getattr(port, "evaluate_page", None)
        if not callable(checker) and callable(port):
            checker = port
        if not callable(checker):
            raise SiteRenderError("INVALID_RENDER_INPUT", "eligibility port must provide check_page or filter_pages")

        kept: list[dict[str, Any]] = []
        evidence: list[dict[str, str]] = []
        normalized_at = None if evaluated_at is None else _time(evaluated_at, "eligibility_evaluated_at")
        for page, snapshot in snapshots:
            material = {"page": snapshot, "evaluated_at": _stamp(normalized_at) if normalized_at else None}
            kwargs = {
                "org_id": tenant,
                "region_profile_version_id": snapshot.get("region_profile_version_id", snapshot.get("region_version_id")),
                "market": snapshot.get("market", snapshot.get("region")),
                "idempotency_key": "site-render:" + _hash(material)[:48],
            }
            if normalized_at is not None:
                kwargs["evaluated_at"] = normalized_at
            if actor_id is not None:
                kwargs["actor_id"] = actor_id
            if trace_id is not None:
                kwargs["trace_id"] = trace_id
            try:
                result = checker(snapshot, **kwargs)
                value = result.as_contract() if hasattr(result, "as_contract") else result
                if isinstance(value, Mapping):
                    decision = str(value.get("decision", value.get("status", "deny"))).lower()
                    status = str(value.get("status", "eligible" if decision == "eligible" else "blocked")).lower()
                    decision_hash = value.get("decision_hash")
                    eligible = decision == "eligible" and status == "eligible"
                elif isinstance(value, bool):
                    eligible = value
                    decision, status, decision_hash = ("eligible", "eligible", None) if value else ("deny", "blocked", None)
                else:
                    eligible, decision, status, decision_hash = False, "deny", "blocked", None
                code = ""
            except Exception as exc:
                eligible, decision, status, decision_hash = False, "deny", "blocked", None
                code = str(getattr(exc, "code", "REGION_ELIGIBILITY_FAILED"))[:128]
            if eligible:
                kept.append(page)
            row = {
                "page_version_id": page["id"],
                "region_profile_version_id": str(snapshot.get("region_profile_version_id", "")),
                "decision": decision,
                "status": status,
            }
            if isinstance(decision_hash, str) and len(decision_hash) == 64:
                row["decision_hash"] = decision_hash
            if code:
                row["code"] = code
            evidence.append(row)
        return kept, sorted(evidence, key=lambda item: item["page_version_id"])

    def _coerce(self, raw: Any) -> list[Mapping[str, Any]]:
        if isinstance(raw, Mapping):
            if isinstance(raw.get("page_versions"), (Mapping, Sequence)) and not isinstance(raw.get("page_versions"), (str, bytes)):
                return self._coerce(raw["page_versions"])
            if {"id", "version_id", "title", "url_path", "canonical_url", "status", "version"}.intersection(raw):
                return [raw]
            out = []
            for locale, value in raw.items():
                if not isinstance(value, Mapping):
                    raise SiteRenderError("INVALID_RENDER_INPUT", "page mapping values must be objects")
                clone = dict(value); clone.setdefault("locale", str(locale)); out.append(clone)
            return out
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise SiteRenderError("INVALID_RENDER_INPUT", "page_versions must be an array or object")
        if any(not isinstance(item, Mapping) for item in raw):
            raise SiteRenderError("INVALID_RENDER_INPUT", "page_versions entries must be objects")
        return list(raw)

    def _variants(self, raw: Any) -> list[Mapping[str, Any]]:
        if raw is None:
            return []
        if isinstance(raw, Mapping):
            out = []
            for locale, value in raw.items():
                if locale in {"x-default", "x_default"} and isinstance(value, str):
                    continue
                values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)) else [value]
                for item in values:
                    if not isinstance(item, Mapping):
                        raise SiteRenderError("INVALID_RENDER_INPUT", "locale variants must contain page objects")
                    clone = dict(item); clone.setdefault("locale", str(locale)); out.append(clone)
            return out
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or any(not isinstance(i, Mapping) for i in raw):
            raise SiteRenderError("INVALID_RENDER_INPUT", "locale_variants must be an object or array")
        return list(raw)

    def _normalize(self, value: Mapping[str, Any], *, tenant: str, origin: str) -> dict[str, Any]:
        source = _unwrap(value)
        given = source.get("org_id")
        if given is not None and _tenant(given) != tenant:
            raise SiteRenderError("TENANT_SCOPE_VIOLATION", "page version is not in this organization")
        source["org_id"] = tenant
        if source.get("status") is None:
            raise SiteRenderError("INVALID_RENDER_INPUT", "page version status is required")
        status = str(source.get("status")).strip().lower()
        if status not in {"draft", "ready", "published", "superseded", "rolled_back"}:
            raise SiteRenderError("UNSUPPORTED_STATUS", "page version status is not supported")
        locale = _locale(source.get("locale", "en-US"))
        raw_path = source.get("url_path", source.get("canonical_url", source.get("path")))
        if raw_path is None:
            raise SiteRenderError("INVALID_CANONICAL_URL", "page version requires url_path or canonical_url")
        path = _path(raw_path, origin=origin)
        if source.get("canonical_url") is not None and _path(source["canonical_url"], origin=origin, field="canonical_url") != path:
            raise SiteRenderError("CANONICAL_URL_MISMATCH", "canonical_url must match url_path")
        title = _text(source.get("title"), "title", maximum=512)
        summary = _text(source.get("summary", ""), "summary", required=False, maximum=10000)
        updated = _time(source.get("updated_at"))
        version_no = _version_no(source.get("version_no", 1))
        group = str(source.get("page_key") or source.get("site_page_id") or source.get("variant_group") or path)
        author = source.get("author")
        author_name = _text(author.get("name", author.get("id", "")), "author.name", required=False, maximum=256) if isinstance(author, Mapping) else _text(author, "author", required=False, maximum=256) if author is not None else ""
        reviewer = source.get("reviewer")
        reviewer_name = _text(reviewer.get("name", reviewer.get("id", "")), "reviewer.name", required=False, maximum=256) if isinstance(reviewer, Mapping) else _text(reviewer, "reviewer", required=False, maximum=256) if reviewer is not None else ""
        identity = _identity(source, path=path, locale=locale)
        return {
            "id": identity, "org_id": tenant, "group_key": group, "locale": locale,
            "path": path, "canonical_url": _absolute(origin, path), "status": status,
            "version_no": version_no,
            "title": title, "summary": summary, "updated_at": updated,
            "author": author_name, "reviewer": reviewer_name,
            "blocks": self._blocks(source.get("visible_content")),
            "methodology": self._steps(source.get("methodology")),
            "limitations": self._strings(source.get("limitations"), "limitations"),
            "evidence": self._evidence(source.get("evidence")),
            "faq": self._faq(source.get("faq")), "source": source,
        }

    @staticmethod
    def _blocks(value: Any) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, str):
            return [{"type": "paragraph", "text": _text(value, "visible_content", maximum=20000)}]
        if not isinstance(value, Mapping) or isinstance(value.get("blocks", []), (str, bytes)) or not isinstance(value.get("blocks", []), Sequence):
            raise SiteRenderError("INVALID_RENDER_INPUT", "visible_content.blocks must be an array")
        out = []
        for item in value.get("blocks", []):
            if isinstance(item, Mapping):
                out.append({"type": _text(item.get("type", "paragraph"), "visible_content.blocks.type", maximum=64).lower(),
                            "text": _text(item.get("text", item.get("content", "")), "visible_content.blocks.text", maximum=20000)})
            else:
                out.append({"type": "paragraph", "text": _text(item, "visible_content.blocks[]", maximum=20000)})
        return out

    @staticmethod
    def _steps(value: Any) -> list[str]:
        if value is None:
            return []
        value = value.get("steps", []) if isinstance(value, Mapping) else value
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise SiteRenderError("INVALID_RENDER_INPUT", "methodology.steps must be an array")
        return [_text(item, "methodology.steps[]", maximum=2000) for item in value]

    @staticmethod
    def _strings(value: Any, field: str) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise SiteRenderError("INVALID_RENDER_INPUT", f"{field} must be an array")
        return [_text(item.get("text", item.get("description", "")) if isinstance(item, Mapping) else item, f"{field}[]", maximum=2000) for item in value]

    @staticmethod
    def _evidence(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise SiteRenderError("INVALID_RENDER_INPUT", "evidence must be an array")
        return [_text(item.get("ref", item.get("id", "")) if isinstance(item, Mapping) else item, "evidence.ref", maximum=512) for item in value]

    @staticmethod
    def _faq(value: Any) -> list[dict[str, str]]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise SiteRenderError("INVALID_RENDER_INPUT", "faq must be an array")
        out = []
        for item in value:
            if not isinstance(item, Mapping):
                raise SiteRenderError("INVALID_RENDER_INPUT", "faq entries must be objects")
            out.append({"question": _text(item.get("question"), "faq.question", maximum=1000),
                        "answer": _text(item.get("answer"), "faq.answer", maximum=10000)})
        return out

    def _artifacts(
        self,
        pages: Sequence[Mapping[str, Any]],
        *,
        origin: str,
        default_locale: str | None,
        x_default_locale: str | None,
        x_default_url: str | None,
        title: str,
        description: str,
        primary_id: str | None = None,
        regional_default: bool = False,
    ) -> dict[str, str]:
        renderable = [p for p in pages if p["status"] in _RENDERABLE]
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for page in renderable:
            groups.setdefault(page["group_key"], []).append(page)
        for rows in groups.values():
            rows.sort(key=lambda p: (p["locale"], p["canonical_url"], p["id"]))
        html_page = ""
        if renderable:
            first = next((p for p in renderable if p["id"] == primary_id), renderable[0])
            html_page = self._html_page(
                first, group=groups[first["group_key"]], origin=origin,
                default_locale=default_locale, x_default_locale=x_default_locale,
                x_default_url=x_default_url,
                regional_default=regional_default,
            )
        published = [p for p in renderable if p["status"] == "published"]
        return {
            "html": html_page,
            "sitemap.xml": self._sitemap(published),
            "rss.xml": self._rss(published, origin=origin, title=title, description=description),
            "atom.xml": self._atom(published, origin=origin, title=title, description=description),
            "robots.txt": self._robots(origin),
        }

    @staticmethod
    def _publication(
        page: Mapping[str, Any],
        *,
        tenant: str,
        request_hash: str,
        artifact_hashes: Mapping[str, str],
        generated_at: str,
        actor_id: str | None,
        trace_id: str | None,
        idempotency_key: str | None,
        x_default_locale: str | None,
        hreflang: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        source = page["source"]
        snapshot = source.get("snapshot_hash")
        if not isinstance(snapshot, str) or len(snapshot) != 64:
            snapshot = _hash(source)
        # A SitePageVersion id is already a stable UUID in the normal path.
        # For lightweight fixtures, retain a deterministic publication id.
        publication_id = source.get("publication_id", page["id"])
        page_id = source.get("site_page_id", source.get("page_id", page["id"]))
        page_key = source.get("page_key", page["group_key"])
        version_no = source.get("version_no", 1)
        created_by = source.get("created_by", actor_id)
        created_at = source.get("created_at", generated_at)
        actor = actor_id
        trace = "site-render" if trace_id is None else trace_id
        return {
            "id": publication_id, "org_id": tenant, "site_page_id": page_id,
            "site_page_version_id": page["id"], "page_key": page_key,
            "version_no": version_no, "locale": page["locale"],
            "canonical_url": page["canonical_url"], "status": "rendered",
            "snapshot_hash": snapshot, "renderer_version": "site-002.v1",
            "request_hash": request_hash, "artifact_hashes": dict(artifact_hashes),
            "hreflang": [dict(item) for item in hreflang], "x_default_locale": x_default_locale or page["locale"],
            "generated_at": generated_at, "created_by": created_by,
            "created_at": created_at, "actor_id": actor, "trace_id": trace,
            "idempotency_key": idempotency_key or "render",
        }

    def _publication_links(
        self,
        page: Mapping[str, Any],
        pages: Sequence[Mapping[str, Any]],
        *,
        origin: str,
        default_locale: str | None,
        x_default_locale: str | None,
        x_default_url: str | None,
        regional_default: bool = False,
    ) -> list[dict[str, str]]:
        group = [item for item in pages if item["group_key"] == page["group_key"]]
        return [{"locale": locale, "url": url} for locale, url in self._alternates(
            page, group, origin=origin, default_locale=default_locale,
            x_default_locale=x_default_locale, x_default_url=x_default_url,
            regional_default=regional_default,
        )]

    def _alternates(
        self,
        page: Mapping[str, Any],
        group: Sequence[Mapping[str, Any]],
        *,
        origin: str,
        default_locale: str | None,
        x_default_locale: str | None,
        x_default_url: str | None,
        regional_default: bool = False,
    ) -> list[tuple[str, str]]:
        rows = [p for p in group if p["status"] in _RENDERABLE] or [page]
        by_locale = {p["locale"].casefold(): p for p in rows}
        preferred = x_default_locale or default_locale
        chosen = by_locale.get(preferred.casefold()) if preferred else None
        if regional_default:
            chosen = chosen or sorted(rows, key=lambda p: (p["locale"].casefold(), p["canonical_url"], p["id"]))[0]
        else:
            chosen = chosen or by_locale.get("en-us") or by_locale.get("en") or sorted(rows, key=lambda p: p["locale"])[0]
        if x_default_url is None or regional_default:
            default_url = chosen["canonical_url"]
        else:
            default_url = _absolute(origin, _path(x_default_url, origin=origin, field="x_default_url"))
        links = [(p["locale"], p["canonical_url"]) for p in sorted(rows, key=lambda p: (p["locale"], p["canonical_url"]))]
        links.append(("x-default", default_url))
        seen: set[str] = set()
        out = []
        for locale, url in links:
            key = locale.casefold()
            if key not in seen:
                seen.add(key)
                out.append((locale, url))
        return out

    def _html_page(
        self,
        page: Mapping[str, Any],
        *,
        group: Sequence[Mapping[str, Any]],
        origin: str,
        default_locale: str | None,
        x_default_locale: str | None,
        x_default_url: str | None,
        regional_default: bool = False,
    ) -> str:
        links = self._alternates(
            page, group, origin=origin, default_locale=default_locale,
            x_default_locale=x_default_locale, x_default_url=x_default_url,
            regional_default=regional_default,
        )
        head = [
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f'<title>{_html(page["title"])}</title>',
            f'<meta name="description" content="{_html(page["summary"])}">',
            f'<link rel="canonical" href="{_html(page["canonical_url"])}">',
        ]
        if page["status"] != "published":
            head.append('<meta name="robots" content="noindex,follow">')
        head.extend(f'<link rel="alternate" hreflang="{_html(locale)}" href="{_html(url)}">' for locale, url in links)
        body = [f'<main data-site-page-version="{_html(page["id"])}">', f'<h1>{_html(page["title"])}</h1>']
        if page["summary"]:
            body.append(f'<p class="summary">{_html(page["summary"])}</p>')
        if page["author"]:
            body.append(f'<p class="author">By {_html(page["author"])}</p>')
        for block in page["blocks"]:
            tag = {"heading": "h2", "subheading": "h3", "quote": "blockquote", "pre": "pre"}.get(block["type"], "p")
            body.append(f'<{tag}>{_html(block["text"])}</{tag}>')
        if page["methodology"]:
            body.extend(["<section><h2>Methodology</h2><ol>", *[f"<li>{_html(x)}</li>" for x in page["methodology"]], "</ol></section>"])
        if page["limitations"]:
            body.extend(["<section><h2>Limitations</h2><ul>", *[f"<li>{_html(x)}</li>" for x in page["limitations"]], "</ul></section>"])
        if page["faq"]:
            body.append("<section><h2>FAQ</h2>")
            body.extend(f'<details><summary>{_html(x["question"])}</summary><p>{_html(x["answer"])}</p></details>' for x in page["faq"])
            body.append("</section>")
        body.append("</main>")
        return (
            f'<!doctype html>\n<html lang="{_html(page["locale"])}">\n<head>\n'
            + "\n".join(head)
            + "\n</head>\n<body>\n"
            + "\n".join(body)
            + "\n</body>\n</html>\n"
        )

    @staticmethod
    def _sitemap(pages: Sequence[Mapping[str, Any]]) -> str:
        unique = {p["canonical_url"]: p for p in pages}
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for url, page in sorted(unique.items()):
            lines.append(f'  <url><loc>{_xml(url)}</loc><lastmod>{_xml(_stamp(page["updated_at"]))}</lastmod></url>')
        lines.extend(["</urlset>", ""])
        return "\n".join(lines)

    @staticmethod
    def _rss(pages: Sequence[Mapping[str, Any]], *, origin: str, title: str, description: str) -> str:
        rows = sorted(pages, key=lambda p: (-p["updated_at"].timestamp(), p["canonical_url"]))
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', "  <channel>",
            f"    <title>{_xml(title)}</title>", f"    <link>{_xml(origin + '/')}</link>",
            f"    <description>{_xml(description)}</description>",
        ]
        for page in rows:
            url = page["canonical_url"]
            lines.extend([
                "    <item>", f"      <title>{_xml(page['title'])}</title>",
                f"      <link>{_xml(url)}</link>",
                f'      <guid isPermaLink="true">{_xml(url)}</guid>',
                f"      <pubDate>{_xml(format_datetime(page['updated_at'], usegmt=True))}</pubDate>",
                f"      <description>{_xml(page['summary'])}</description>", "    </item>",
            ])
        lines.extend(["  </channel>", "</rss>", ""])
        return "\n".join(lines)

    @staticmethod
    def _atom(pages: Sequence[Mapping[str, Any]], *, origin: str, title: str, description: str) -> str:
        rows = sorted(pages, key=lambda p: (-p["updated_at"].timestamp(), p["canonical_url"]))
        latest = rows[0]["updated_at"] if rows else datetime(1970, 1, 1, tzinfo=timezone.utc)
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<feed xmlns="http://www.w3.org/2005/Atom">',
            f"  <title>{_xml(title)}</title>", f"  <id>{_xml(origin + '/')}</id>",
            f"  <updated>{_xml(_stamp(latest))}</updated>",
            f'  <link href="{_xml(origin + "/")}" rel="alternate"/>',
        ]
        if description:
            lines.append(f"  <subtitle>{_xml(description)}</subtitle>")
        for page in rows:
            url = page["canonical_url"]
            lines.extend([
                "  <entry>", f"    <title>{_xml(page['title'])}</title>",
                f"    <id>{_xml(url)}</id>", f'    <link href="{_xml(url)}"/>',
                f"    <updated>{_xml(_stamp(page['updated_at']))}</updated>",
                f'    <summary type="text">{_xml(page["summary"])}</summary>', "  </entry>",
            ])
        lines.extend(["</feed>", ""])
        return "\n".join(lines)

    @staticmethod
    def _robots(origin: str) -> str:
        return "\n".join([
            "User-agent: *", "Disallow: /api/", "Disallow: /internal/",
            "Disallow: /admin/", "Disallow: /health", f"Sitemap: {origin}/sitemap.xml", "",
        ])


__all__ = ["InMemorySiteRenderStore", "SiteRenderError", "SiteRenderService"]
