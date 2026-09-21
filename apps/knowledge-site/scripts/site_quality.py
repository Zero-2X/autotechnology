"""Offline deterministic SITE-004 quality audit.

The service consumes immutable page/render snapshots plus caller supplied
observations.  It does not open a socket, launch a browser, mutate a page, or
persist raw HTML.  Only bounded checks, metrics and hashes cross the boundary.
"""
from __future__ import annotations

from collections.abc import Mapping as ABCMapping
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from threading import RLock
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads(
    (ROOT / "packages/contracts/jsonschema/site-quality-report.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
RULE_VERSION = "site-004.v1"
SYSTEM_ACTOR = UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_THRESHOLDS = {
    "lcp_ms": 2500.0,
    "cls": 0.1,
    "inp_ms": 200.0,
    "ttfb_ms": 800.0,
    "max_total_bytes": 1_500_000,
    "max_redirects": 1,
}
METRIC_KEYS = ("lcp_ms", "cls", "inp_ms", "ttfb_ms", "total_bytes")
CATEGORY_ORDER = {name: index for index, name in enumerate(
    ("http", "link", "redirect", "performance", "alt", "caption", "dynamic")
)}
URL_ATTRS = {
    "a": "href", "area": "href", "link": "href", "img": "src",
    "script": "src", "iframe": "src", "video": "src", "audio": "src",
    "source": "src", "track": "src",
}
TENANT_KEYS = frozenset({"org_id", "tenant_id", "organization_id"})
RAW_KEYS = frozenset({"html", "body", "content", "payload", "dom", "response_body", "headers", "cookies"})
SPACE_RE = re.compile(r"\s+")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
HASH_RE = re.compile(r"^[A-Fa-f0-9]{64}$")


class SiteQualityError(ValueError):
    """Stable error raised at the SITE-004 application boundary."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


class SiteQualityReport(ABCMapping[str, Any]):
    """Read-only mapping facade for a validated report projection."""

    def __init__(self, value: Mapping[str, Any]) -> None:
        self._value = deepcopy(dict(value))

    def as_contract(self) -> dict[str, Any]:
        return deepcopy(self._value)

    def __getitem__(self, key: str) -> Any:
        return self._value[key]

    def __iter__(self):
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def get(self, key: str, default: Any = None) -> Any:
        return self._value.get(key, default)

    def __getattr__(self, name: str) -> Any:
        if name in self._value:
            return self._value[name]
        raise AttributeError(name)


class InMemorySiteQualityStore:
    """Append-only local report/idempotency fixture."""

    def __init__(self) -> None:
        self.reports: dict[str, dict[str, Any]] = {}
        self.commands: dict[tuple[str, str], dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = RLock()

    def get_command(self, *, org_id: str, idempotency_key: str) -> Mapping[str, Any] | None:
        with self._lock:
            row = self.commands.get((org_id, idempotency_key))
            return None if row is None else deepcopy(row)

    def save_command(
        self,
        *,
        org_id: str,
        idempotency_key: str,
        request_hash: str,
        response: Mapping[str, Any],
    ) -> None:
        with self._lock:
            key = (org_id, idempotency_key)
            prior = self.commands.get(key)
            if prior is not None:
                if prior["request_hash"] != request_hash:
                    raise SiteQualityError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
                return
            self.commands[key] = {"request_hash": request_hash, "response": deepcopy(dict(response))}

    def save_report(self, report: Mapping[str, Any]) -> None:
        with self._lock:
            identity = str(report["id"])
            if identity in self.reports:
                raise SiteQualityError("REPORT_IMMUTABLE", "site quality report already exists")
            self.reports[identity] = deepcopy(dict(report))


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", "input must be finite JSON") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _uuid(value: Any, field: str) -> str:
    try:
        return str(value if isinstance(value, UUID) else UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise SiteQualityError("INVALID_SITE_QUALITY_CONTEXT", f"{field} must be a UUID") from exc


def _text(value: Any, field: str, *, maximum: int = 4096, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} must be text")
    result = value.strip()
    if (required and not result) or len(result) > maximum:
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} has an invalid length")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in result):
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} contains a control character")
    return result


def _time(value: Any, field: str, *, default: datetime | None = None) -> datetime:
    if value is None:
        if default is None:
            raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} is required")
        parsed = default
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} must be ISO-8601") from exc
    else:
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} must be ISO-8601")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _stamp(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if str(key).lower() not in RAW_KEYS
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _guard_tenant(value: Any, tenant: str, field: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in TENANT_KEYS and item is not None and _uuid(item, f"{field}.{key}") != tenant:
                raise SiteQualityError("TENANT_SCOPE_VIOLATION", f"{field} is outside this organization")
            _guard_tenant(item, tenant, f"{field}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _guard_tenant(item, tenant, f"{field}[{index}]")


def _normal_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def _stable_code(value: Any, default: str) -> str:
    candidate = str(value).strip().upper() if value is not None else ""
    return candidate if CODE_RE.fullmatch(candidate) else default


class _AuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.canonicals: list[str] = []
        self.ids: set[str] = set()
        self.images: list[dict[str, str]] = []
        self.media: list[dict[str, Any]] = []
        self._media_stack: list[int] = []
        self._main_depth = 0
        self._h1_depth = 0
        self._title_depth = 0
        self._ignore_depth = 0
        self.main_text: list[str] = []
        self.h1_texts: list[list[str]] = []
        self.title_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        data = {key.lower(): "" if value is None else value for key, value in attrs}
        identity = data.get("id") or (data.get("name") if name == "a" else None)
        if identity:
            self.ids.add(identity)
        attribute = URL_ATTRS.get(name)
        if attribute and data.get(attribute):
            self.links.append((name, data[attribute]))
        if name == "link" and "canonical" in data.get("rel", "").lower().split() and data.get("href"):
            self.canonicals.append(data["href"])
        if name == "img":
            self.images.append(data)
        if name in {"video", "audio"}:
            self.media.append({"tag": name, "src": data.get("src", ""), "captions": []})
            self._media_stack.append(len(self.media) - 1)
        elif name == "track" and self._media_stack and data.get("kind", "").lower() == "captions":
            self.media[self._media_stack[-1]]["captions"].append({
                "src": data.get("src", ""), "srclang": data.get("srclang", "")
            })
        if name in {"script", "style", "noscript"}:
            self._ignore_depth += 1
        if name == "main":
            self._main_depth += 1
        if name == "h1":
            self._h1_depth += 1
            self.h1_texts.append([])
        if name == "title":
            self._title_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in {"video", "audio"} and self._media_stack:
            self._media_stack.pop()
        if name == "main" and self._main_depth:
            self._main_depth -= 1
        if name == "h1" and self._h1_depth:
            self._h1_depth -= 1
        if name == "title" and self._title_depth:
            self._title_depth -= 1
        if name in {"script", "style", "noscript"} and self._ignore_depth:
            self._ignore_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        value = _normal_text(data)
        if not value:
            return
        if self._main_depth:
            self.main_text.append(value)
        if self._h1_depth and self.h1_texts:
            self.h1_texts[-1].append(value)
        if self._title_depth:
            self.title_text.append(value)


def _parse_html(value: Any, field: str) -> tuple[str, _AuditParser]:
    if not isinstance(value, str) or not value.strip() or len(value) > 2_000_000:
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} must be non-empty text up to 2000000 characters")
    if any(ord(char) < 0x20 and char not in "\t\n\r" for char in value):
        raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", f"{field} contains a control character")
    # Preserve exact input bytes for the evidence hash; HTMLParser receives
    # the same snapshot that the caller supplied.
    html = value
    parser = _AuditParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:
        raise SiteQualityError("INVALID_SITE_HTML", f"{field} cannot be parsed") from exc
    return html, parser


def _normalise_http_url(value: Any, *, base: str, field: str) -> tuple[str, str]:
    raw = _text(value, field, maximum=4096)
    resolved = urljoin(base, raw)
    parts = urlsplit(resolved)
    scheme = parts.scheme.lower()
    if scheme in {"mailto", "tel"}:
        return scheme, raw
    if scheme not in {"http", "https"}:
        raise SiteQualityError("UNSAFE_URL", f"{field} uses an unsupported scheme")
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise SiteQualityError("UNSAFE_URL", f"{field} must be an http(s) URL without credentials")
    try:
        port = parts.port
    except ValueError as exc:
        raise SiteQualityError("UNSAFE_URL", f"{field} has an invalid port") from exc
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parts.path or "/"
    normalized = urlunsplit((scheme, netloc, path, parts.query, ""))
    return "http", normalized


def _safe_target(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme in {"http", "https"}:
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", "", ""))
    return parts.scheme or value[:128]


def _check(
    code: str,
    category: str,
    status: str,
    target: str | None,
    observed: Any,
    expected: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "category": category,
        "status": status,
        "severity": "error" if status == "fail" else "warning" if status == "review" else "info",
        "target": target,
        "observed": _json_safe(observed),
        "expected": _json_safe(expected),
        "message": message[:512],
    }


class SiteQualityService:
    """Audit one public page snapshot without network or browser side effects."""

    def __init__(
        self,
        *,
        store: InMemorySiteQualityStore | None = None,
        clock: Callable[[], datetime] | None = None,
        link_probe_port: Any = None,
    ) -> None:
        self.store = store or InMemorySiteQualityStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.link_probe_port = link_probe_port
        self.audit_log = self.store.audit
        self._lock = RLock()

    @staticmethod
    def _context(
        page: Mapping[str, Any],
        *,
        org_id: Any,
        tenant_context: Mapping[str, Any] | None,
        actor_id: Any,
        trace_id: Any,
    ) -> tuple[str, str, str]:
        context = tenant_context or {}
        context_org = context.get("org_id", context.get("tenant_id"))
        page_org = page.get("org_id", page.get("tenant_id"))
        selected = org_id if org_id is not None else context_org if context_org is not None else page_org
        tenant = _uuid(selected, "org_id")
        for candidate in (context_org, page_org):
            if candidate is not None and _uuid(candidate, "org_id") != tenant:
                raise SiteQualityError("TENANT_SCOPE_VIOLATION", "page and tenant context differ")
        actor_raw = actor_id if actor_id is not None else context.get("actor_id", SYSTEM_ACTOR)
        actor = _uuid(actor_raw, "actor_id")
        trace_raw = trace_id if trace_id is not None else context.get("trace_id", "site-quality")
        trace = _text(trace_raw, "trace_id", maximum=256)
        return tenant, actor, trace

    @staticmethod
    def _thresholds(value: Any, tenant: str) -> tuple[dict[str, float | int], str]:
        result: dict[str, float | int] = dict(DEFAULT_THRESHOLDS)
        version = "site-performance-v1"
        if value is None:
            return result, version
        if not isinstance(value, Mapping):
            raise SiteQualityError("INVALID_PERFORMANCE_THRESHOLDS", "thresholds must be an object")
        _guard_tenant(value, tenant, "thresholds")
        allowed = set(DEFAULT_THRESHOLDS) | {"version", "threshold_version", "org_id", "tenant_id"}
        unknown = sorted(str(key) for key in value if str(key) not in allowed)
        if unknown:
            raise SiteQualityError("INVALID_PERFORMANCE_THRESHOLDS", "thresholds contain unknown fields")
        version_raw = value.get("threshold_version", value.get("version"))
        if version_raw is not None:
            version = _text(version_raw, "threshold_version", maximum=128)
        for key in DEFAULT_THRESHOLDS:
            if key not in value:
                continue
            raw = value[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)) or raw < 0:
                raise SiteQualityError("INVALID_PERFORMANCE_THRESHOLDS", f"{key} must be a finite non-negative number")
            if key in {"max_total_bytes", "max_redirects"}:
                if type(raw) is not int or (key == "max_total_bytes" and raw < 1) or (key == "max_redirects" and raw > 20):
                    raise SiteQualityError("INVALID_PERFORMANCE_THRESHOLDS", f"{key} must be a supported integer")
                result[key] = raw
            else:
                result[key] = float(raw)
        return result, version

    @staticmethod
    def _metrics(value: Any) -> dict[str, float | int | None]:
        if value is None:
            return {key: None for key in METRIC_KEYS}
        if not isinstance(value, Mapping):
            raise SiteQualityError("INVALID_PERFORMANCE_METRICS", "performance_metrics must be an object")
        unknown = sorted(str(key) for key in value if str(key) not in METRIC_KEYS)
        if unknown:
            raise SiteQualityError("INVALID_PERFORMANCE_METRICS", "performance_metrics contain unknown fields")
        result: dict[str, float | int | None] = {}
        for key in METRIC_KEYS:
            raw = value.get(key)
            if raw is None:
                result[key] = None
                continue
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)) or raw < 0:
                raise SiteQualityError("INVALID_PERFORMANCE_METRICS", f"{key} must be a finite non-negative number")
            if key == "total_bytes":
                if type(raw) is not int:
                    raise SiteQualityError("INVALID_PERFORMANCE_METRICS", "total_bytes must be an integer")
                result[key] = raw
            else:
                result[key] = float(raw)
        return result

    @staticmethod
    def _observations(value: Any, *, base: str, tenant: str) -> dict[str, dict[str, Any]]:
        if value is None:
            return {}
        _guard_tenant(value, tenant, "link_observations")
        if isinstance(value, Mapping):
            if "url" in value and ({"status_code", "error", "error_code"} & set(value)):
                rows = [value]
            else:
                rows = []
                for key, item in value.items():
                    if isinstance(item, Mapping):
                        rows.append({**dict(item), "url": key})
                    elif type(item) is int:
                        rows.append({"url": key, "status_code": item})
                    else:
                        raise SiteQualityError("INVALID_LINK_OBSERVATION", "link observation values must be objects")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            rows = list(value)
        else:
            raise SiteQualityError("INVALID_LINK_OBSERVATION", "link_observations must be an object or array")
        result: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(rows):
            if not isinstance(raw, Mapping):
                raise SiteQualityError("INVALID_LINK_OBSERVATION", f"link_observations[{index}] must be an object")
            kind, url = _normalise_http_url(raw.get("url"), base=base, field=f"link_observations[{index}].url")
            if kind != "http":
                continue
            status = raw.get("status_code")
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                raise SiteQualityError("INVALID_LINK_OBSERVATION", "status_code must be an integer from 100 to 599")
            final_url = None
            if raw.get("final_url") is not None:
                final_kind, final_url = _normalise_http_url(raw["final_url"], base=url, field="final_url")
                if final_kind != "http":
                    raise SiteQualityError("INVALID_LINK_OBSERVATION", "final_url must use http or https")
            chain_raw = raw.get("redirect_chain", [])
            if isinstance(chain_raw, (str, bytes, Mapping)) or not isinstance(chain_raw, Sequence):
                raise SiteQualityError("INVALID_LINK_OBSERVATION", "redirect_chain must be an array")
            chain: list[str] = []
            for hop in chain_raw:
                hop_kind, hop_url = _normalise_http_url(hop, base=url, field="redirect_chain[]")
                if hop_kind != "http":
                    raise SiteQualityError("INVALID_LINK_OBSERVATION", "redirect_chain must contain http(s) URLs")
                chain.append(hop_url)
            error_code = raw.get("error_code")
            if error_code is None and raw.get("error") is not None:
                error_code = "LINK_PROBE_ERROR"
            row = {
                "status_code": status,
                "final_url": final_url,
                "redirect_chain": chain,
                "error_code": None if error_code is None else _stable_code(error_code, "LINK_PROBE_ERROR"),
            }
            prior = result.get(url)
            if prior is not None and prior != row:
                raise SiteQualityError("DUPLICATE_LINK_OBSERVATION", "conflicting observations use the same URL")
            result[url] = row
        return result

    def _probe(self, url: str, *, tenant: str, base: str) -> dict[str, Any] | None:
        port = self.link_probe_port
        if port is None:
            return None
        probe = getattr(port, "probe", None)
        if not callable(probe) and callable(port):
            probe = port
        if not callable(probe):
            raise SiteQualityError("INVALID_LINK_PROBE_PORT", "link probe port must be callable")
        try:
            raw = probe(url=url, org_id=tenant)
            values = self._observations({url: raw if isinstance(raw, Mapping) else {"status_code": raw}}, base=base, tenant=tenant)
            return values.get(url)
        except SiteQualityError:
            raise
        except Exception as exc:
            return {
                "status_code": None,
                "final_url": None,
                "redirect_chain": [],
                "error_code": _stable_code(getattr(exc, "code", None), "LINK_PROBE_FAILED"),
            }

    def audit(
        self,
        page_version: Mapping[str, Any] | None = None,
        *,
        page: Mapping[str, Any] | None = None,
        rendered_html: str | None = None,
        html: str | None = None,
        page_status_code: int | None = None,
        link_observations: Any = None,
        performance_metrics: Mapping[str, Any] | None = None,
        dynamic_html: str | None = None,
        thresholds: Mapping[str, Any] | None = None,
        base_origin: str | None = None,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        predecessor_artifacts: Mapping[str, Any] | None = None,
        evaluated_at: datetime | str | None = None,
        actor_id: Any = None,
        trace_id: Any = None,
        idempotency_key: Any = None,
    ) -> SiteQualityReport:
        source_page = page_version if page_version is not None else page
        if not isinstance(source_page, Mapping):
            raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", "page_version is required")
        if isinstance(source_page.get("version"), Mapping):
            merged = dict(source_page["version"])
            parent = source_page.get("page")
            if isinstance(parent, Mapping):
                for name in ("org_id", "page_key", "canonical_url", "url_path"):
                    merged.setdefault(name, parent.get(name))
            source_page = merged
        tenant, actor, trace = self._context(
            source_page, org_id=org_id, tenant_context=tenant_context,
            actor_id=actor_id, trace_id=trace_id,
        )
        _guard_tenant(source_page, tenant, "page_version")
        _guard_tenant(predecessor_artifacts, tenant, "predecessor_artifacts")
        page_id = _uuid(source_page.get("id", source_page.get("page_version_id")), "site_page_version_id")
        page_key = _text(source_page.get("page_key", source_page.get("key", page_id)), "page_key", maximum=512)
        state = str(source_page.get("status", "")).strip().lower()
        if state not in {"ready", "published"}:
            raise SiteQualityError("PAGE_NOT_AUDITABLE", "page version must be ready or published")
        render_mode = source_page.get("render_mode")
        if render_mode is not None and str(render_mode).lower() not in {"ssr", "static"}:
            raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", "render_mode must be ssr or static")
        snapshot_hash = source_page.get("snapshot_hash")
        if snapshot_hash is not None and (not isinstance(snapshot_hash, str) or not HASH_RE.fullmatch(snapshot_hash)):
            raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", "page snapshot_hash must be SHA-256")
        source_html, parsed = _parse_html(rendered_html if rendered_html is not None else html, "rendered_html")

        candidates = []
        explicit_canonical = source_page.get("canonical_url")
        if isinstance(explicit_canonical, str) and explicit_canonical.strip():
            candidates.append(explicit_canonical.strip())
        candidates.extend(parsed.canonicals)
        origin = base_origin
        if origin is None:
            origin = next((item for item in candidates if urlsplit(item).scheme.lower() in {"http", "https"}), None)
        if origin is None:
            raise SiteQualityError("INVALID_CANONICAL_URL", "an absolute canonical URL or base_origin is required")
        origin_parts = urlsplit(_text(origin, "base_origin", maximum=2048))
        if origin_parts.scheme.lower() not in {"http", "https"} or not origin_parts.hostname:
            raise SiteQualityError("INVALID_CANONICAL_URL", "base_origin must use http or https")
        origin_value = urlunsplit((origin_parts.scheme.lower(), origin_parts.netloc.lower(), "/", "", ""))
        canonical_raw = explicit_canonical or (parsed.canonicals[0] if parsed.canonicals else source_page.get("url_path"))
        canonical_kind, canonical_url = _normalise_http_url(canonical_raw, base=origin_value, field="canonical_url")
        if canonical_kind != "http":
            raise SiteQualityError("INVALID_CANONICAL_URL", "canonical_url must use http or https")
        if urlsplit(canonical_url).query:
            raise SiteQualityError("INVALID_CANONICAL_URL", "canonical_url cannot contain a query")

        normalized_thresholds, threshold_version = self._thresholds(thresholds, tenant)
        normalized_metrics = self._metrics(performance_metrics)
        observations = self._observations(link_observations, base=canonical_url, tenant=tenant)
        dynamic_source: str | None = None
        dynamic_parsed: _AuditParser | None = None
        if dynamic_html is not None:
            dynamic_source, dynamic_parsed = _parse_html(dynamic_html, "dynamic_html")
        # SITE-002 hashes text through the repository canonical-JSON helper;
        # reuse that convention so quality evidence joins its artifact hash.
        source_hash = _hash(source_html)
        dynamic_hash = None if dynamic_source is None else _hash(dynamic_source)
        expected_html_hash = None
        if isinstance(predecessor_artifacts, Mapping):
            artifact_hashes = predecessor_artifacts.get("artifact_hashes", predecessor_artifacts.get("hashes"))
            if isinstance(artifact_hashes, Mapping):
                expected_html_hash = artifact_hashes.get("html")
        if expected_html_hash is not None:
            if not isinstance(expected_html_hash, str) or not HASH_RE.fullmatch(expected_html_hash):
                raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", "predecessor HTML hash must be SHA-256")
            if expected_html_hash.lower() != source_hash:
                raise SiteQualityError("ARTIFACT_HASH_MISMATCH", "rendered HTML does not match predecessor evidence")
        at = _time(evaluated_at, "evaluated_at", default=self.clock())
        key = (
            _text(idempotency_key, "idempotency_key", maximum=200)
            if idempotency_key is not None
            else f"site-quality:{page_id}:{source_hash[:24]}"
        )
        if len(key) < 2:
            raise SiteQualityError("INVALID_SITE_QUALITY_INPUT", "idempotency_key length must be 2..200")
        observation_material = {
            url: {
                "status_code": row["status_code"],
                "final_url": row["final_url"],
                "redirect_chain": row["redirect_chain"],
                "error_code": row["error_code"],
            }
            for url, row in sorted(observations.items())
        }
        request_material = {
            "org_id": tenant,
            "site_page_version_id": page_id,
            "page_key": page_key,
            "canonical_url": canonical_url,
            "page_status": state,
            "page_snapshot_hash": snapshot_hash,
            "page_metadata_hash": _hash(_json_safe(source_page)),
            "page_status_code": page_status_code,
            "source_html_hash": source_hash,
            "dynamic_html_hash": dynamic_hash,
            "link_observations": observation_material,
            "performance_metrics": normalized_metrics,
            "thresholds": normalized_thresholds,
            "threshold_version": threshold_version,
            "dynamic_required": source_page.get("dynamic_required") is True,
            "predecessor_hash": None if predecessor_artifacts is None else _hash(_json_safe(predecessor_artifacts)),
            "evaluated_at": _stamp(at) if evaluated_at is not None else None,
        }
        request_hash = _hash(request_material)
        prior = self.store.get_command(org_id=tenant, idempotency_key=key)
        if prior is not None:
            if prior.get("request_hash") != request_hash:
                raise SiteQualityError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return SiteQualityReport(prior["response"])

        checks: list[dict[str, Any]] = []
        status_code = page_status_code if page_status_code is not None else source_page.get("http_status")
        if status_code is None:
            canonical_observation = observations.get(canonical_url)
            status_code = None if canonical_observation is None else canonical_observation.get("status_code")
        if status_code is None:
            checks.append(_check("PAGE_HTTP_STATUS_UNKNOWN", "http", "review", canonical_url, None, 200, "page HTTP status is unavailable"))
        elif type(status_code) is not int or not 100 <= status_code <= 599:
            raise SiteQualityError("INVALID_HTTP_STATUS", "page_status_code must be an integer from 100 to 599")
        elif status_code == 200:
            checks.append(_check("PAGE_HTTP_STATUS_OK", "http", "pass", canonical_url, status_code, 200, "public page returns HTTP 200"))
        else:
            checks.append(_check("PAGE_HTTP_STATUS_INVALID", "http", "fail", canonical_url, status_code, 200, "public page must return HTTP 200"))

        # Validate same-document anchors before fragment removal and collect a
        # deterministic unique set of network resources.
        network_urls: set[str] = set()
        skipped_schemes: set[str] = set()
        unsafe_links: list[tuple[str, str]] = []
        broken_anchors: set[str] = set()
        canonical_base = urlunsplit((*urlsplit(canonical_url)[:3], "", ""))
        for tag, raw_url in parsed.links:
            raw_value = raw_url.strip()
            raw_parts = urlsplit(urljoin(canonical_url, raw_value))
            if raw_parts.fragment and urlunsplit((raw_parts.scheme, raw_parts.netloc, raw_parts.path or "/", "", "")) == canonical_base:
                if raw_parts.fragment not in parsed.ids:
                    broken_anchors.add(raw_parts.fragment)
                continue
            try:
                kind, normalized = _normalise_http_url(raw_value, base=canonical_url, field=f"{tag}.url")
            except SiteQualityError as exc:
                unsafe_links.append((str(getattr(exc, "code", "UNSAFE_URL")), urlsplit(raw_value).scheme.lower() or "relative"))
                continue
            if kind in {"mailto", "tel"}:
                skipped_schemes.add(kind)
            else:
                network_urls.add(normalized)
        for anchor in sorted(broken_anchors):
            checks.append(_check("BROKEN_FRAGMENT", "link", "fail", f"#{anchor}"[:2048], anchor, "existing element id", "same-document fragment target is missing"))
        if not broken_anchors:
            checks.append(_check("FRAGMENTS_VALID", "link", "pass", canonical_url, len(parsed.ids), "all referenced ids exist", "same-document fragments are valid"))
        for code, scheme in sorted(set(unsafe_links)):
            checks.append(_check(code, "link", "fail", scheme, scheme, ["http", "https", "mailto", "tel"], "link uses an unsafe or unsupported URL"))
        for scheme in sorted(skipped_schemes):
            checks.append(_check("NON_HTTP_LINK_SKIPPED", "link", "pass", scheme, scheme, ["mailto", "tel"], "non-HTTP contact link is outside probe scope"))

        if canonical_url in network_urls and status_code is not None:
            observations.setdefault(canonical_url, {
                "status_code": status_code, "final_url": canonical_url,
                "redirect_chain": [], "error_code": None,
            })
        for url in sorted(network_urls):
            observation = observations.get(url)
            if observation is None:
                observation = self._probe(url, tenant=tenant, base=canonical_url)
                if observation is not None:
                    observations[url] = deepcopy(observation)
            target = _safe_target(url)
            if observation is None:
                checks.append(_check("LINK_STATUS_UNKNOWN", "link", "review", target, None, "HTTP observation", "link status is unavailable"))
                continue
            if observation.get("error_code"):
                checks.append(_check("LINK_PROBE_ERROR", "link", "review", target, observation["error_code"], "successful probe", "link probe result requires review"))
                continue
            code = observation.get("status_code")
            if code is None:
                checks.append(_check("LINK_STATUS_UNKNOWN", "link", "review", target, None, "HTTP observation", "link status is unavailable"))
            elif 200 <= code < 300:
                checks.append(_check("LINK_OK", "link", "pass", target, code, "2xx", "link returned a successful status"))
            elif 300 <= code < 400:
                final_url = observation.get("final_url")
                chain = list(observation.get("redirect_chain") or [])
                if final_url is None or not chain:
                    checks.append(_check("REDIRECT_TARGET_MISSING", "redirect", "fail", target, {"status_code": code, "hops": len(chain)}, "final_url and redirect_chain", "redirect evidence is incomplete"))
                    continue
                hops = len(chain) - 1 if chain and chain[0] == url else len(chain)
                looped = len(set(chain)) != len(chain) or (len(chain) > 1 and chain[-1] in chain[:-1])
                if looped:
                    checks.append(_check("REDIRECT_LOOP", "redirect", "fail", target, len(chain), "acyclic redirect chain", "redirect chain contains a loop"))
                elif hops > int(normalized_thresholds["max_redirects"]):
                    checks.append(_check("REDIRECT_CHAIN_TOO_LONG", "redirect", "fail", target, hops, normalized_thresholds["max_redirects"], "redirect chain exceeds the configured hop limit"))
                elif chain[-1] != final_url:
                    checks.append(_check("REDIRECT_TARGET_MISMATCH", "redirect", "fail", target, _safe_target(chain[-1]), _safe_target(final_url), "redirect chain does not end at final_url"))
                else:
                    checks.append(_check("REDIRECT_VALID", "redirect", "pass", target, hops, normalized_thresholds["max_redirects"], "redirect chain is complete and bounded"))
            elif 400 <= code < 600:
                checks.append(_check("BROKEN_LINK", "link", "fail", target, code, "2xx or bounded 3xx", "link returned an error status"))
            else:
                checks.append(_check("LINK_STATUS_UNKNOWN", "link", "review", target, code, "final HTTP status", "link status is not final"))
        if not network_urls:
            checks.append(_check("NO_HTTP_LINKS", "link", "pass", canonical_url, 0, ">= 0", "page has no HTTP resources to probe"))

        metric_threshold = {
            "lcp_ms": "lcp_ms", "cls": "cls", "inp_ms": "inp_ms",
            "ttfb_ms": "ttfb_ms", "total_bytes": "max_total_bytes",
        }
        for metric in METRIC_KEYS:
            observed = normalized_metrics[metric]
            limit = normalized_thresholds[metric_threshold[metric]]
            if observed is None:
                checks.append(_check("PERFORMANCE_METRIC_MISSING", "performance", "review", metric, None, limit, f"{metric} is unavailable"))
            elif observed <= limit:
                checks.append(_check("PERFORMANCE_BUDGET_OK", "performance", "pass", metric, observed, limit, f"{metric} is within budget"))
            else:
                checks.append(_check("PERFORMANCE_BUDGET_EXCEEDED", "performance", "fail", metric, observed, limit, f"{metric} exceeds budget"))

        for index, image in enumerate(sorted(parsed.images, key=lambda item: (item.get("src", ""), item.get("alt", "")))):
            decorative = (
                image.get("role", "").lower() in {"presentation", "none"}
                or image.get("aria-hidden", "").lower() == "true"
                or image.get("data-decorative", "").lower() == "true"
            )
            alt = image.get("alt")
            target = _safe_target(urljoin(canonical_url, image.get("src", ""))) if image.get("src") else f"image:{index}"
            if decorative and (alt is None or not alt.strip()):
                checks.append(_check("DECORATIVE_IMAGE_ALT_OK", "alt", "pass", target, "", "empty alt", "decorative image has empty alt text"))
            elif alt is None or not alt.strip():
                checks.append(_check("IMAGE_ALT_MISSING", "alt", "fail", target, None if alt is None else "", "non-empty alt", "non-decorative image requires alt text"))
            elif len(alt.strip()) > 250:
                checks.append(_check("IMAGE_ALT_TOO_LONG", "alt", "fail", target, len(alt.strip()), "<= 250", "image alt text is too long"))
            else:
                checks.append(_check("IMAGE_ALT_OK", "alt", "pass", target, len(alt.strip()), "1..250", "image has bounded alt text"))
        if not parsed.images:
            checks.append(_check("IMAGE_ALT_NOT_REQUIRED", "alt", "pass", None, 0, ">= 0", "page has no images"))

        for index, media in enumerate(parsed.media):
            valid_tracks = [track for track in media["captions"] if track.get("src") and track.get("srclang")]
            target = _safe_target(urljoin(canonical_url, media.get("src", ""))) if media.get("src") else f"{media['tag']}:{index}"
            if valid_tracks:
                checks.append(_check("CAPTIONS_PRESENT", "caption", "pass", target, len(valid_tracks), ">= 1", "media has a captions track with src and srclang"))
            else:
                checks.append(_check("CAPTIONS_MISSING", "caption", "fail", target, 0, ">= 1", "media requires a captions track with src and srclang"))
        if not parsed.media:
            checks.append(_check("CAPTIONS_NOT_REQUIRED", "caption", "pass", None, 0, ">= 0", "page has no audio or video"))

        source_canonicals: list[str] = []
        for item in parsed.canonicals:
            try:
                item_kind, item_url = _normalise_http_url(item, base=canonical_url, field="link.canonical")
            except SiteQualityError:
                continue
            if item_kind == "http":
                source_canonicals.append(item_url)
        if len(source_canonicals) != 1:
            checks.append(_check("CANONICAL_COUNT_INVALID", "dynamic", "fail", canonical_url, len(source_canonicals), 1, "rendered page must contain exactly one canonical link"))
        elif source_canonicals[0] != canonical_url:
            checks.append(_check("CANONICAL_MISMATCH", "dynamic", "fail", canonical_url, _safe_target(source_canonicals[0]), _safe_target(canonical_url), "rendered canonical differs from page canonical"))
        else:
            checks.append(_check("CANONICAL_OK", "dynamic", "pass", canonical_url, 1, 1, "rendered canonical matches the page"))
        source_h1 = [_normal_text(" ".join(parts)) for parts in parsed.h1_texts if _normal_text(" ".join(parts))]
        source_main = _normal_text(" ".join(parsed.main_text))
        if len(source_h1) != 1:
            checks.append(_check("VISIBLE_TITLE_INVALID", "dynamic", "fail", canonical_url, len(source_h1), 1, "rendered page must contain one visible h1"))
        else:
            checks.append(_check("VISIBLE_TITLE_OK", "dynamic", "pass", canonical_url, source_h1[0], "one visible h1", "rendered page has one visible title"))
        if not source_main:
            checks.append(_check("SSR_MAIN_EMPTY", "dynamic", "fail", canonical_url, 0, "> 0", "rendered main content is empty"))
        else:
            checks.append(_check("SSR_MAIN_PRESENT", "dynamic", "pass", canonical_url, len(source_main), "> 0", "rendered main content is visible without client execution"))
        if dynamic_parsed is None:
            if source_page.get("dynamic_required") is True:
                checks.append(_check("DYNAMIC_RENDER_UNKNOWN", "dynamic", "review", canonical_url, None, "dynamic DOM snapshot", "page requires a dynamic-render snapshot"))
            else:
                checks.append(_check("DYNAMIC_RENDER_NOT_REQUIRED", "dynamic", "pass", canonical_url, state, ["ready", "published"], "SSR/static snapshot contains the public content"))
        else:
            dynamic_canonicals: list[str] = []
            for item in dynamic_parsed.canonicals:
                try:
                    item_kind, item_url = _normalise_http_url(item, base=canonical_url, field="dynamic.canonical")
                except SiteQualityError:
                    continue
                if item_kind == "http":
                    dynamic_canonicals.append(item_url)
            dynamic_h1 = [_normal_text(" ".join(parts)) for parts in dynamic_parsed.h1_texts if _normal_text(" ".join(parts))]
            dynamic_main = _normal_text(" ".join(dynamic_parsed.main_text))
            source_tokens = set(source_main.casefold().split())
            dynamic_tokens = set(dynamic_main.casefold().split())
            retention = 1.0 if not source_tokens else len(source_tokens & dynamic_tokens) / len(source_tokens)
            if dynamic_canonicals != [canonical_url] or dynamic_h1 != source_h1 or retention < 0.9:
                checks.append(_check("DYNAMIC_RENDER_MISMATCH", "dynamic", "fail", canonical_url, {"canonical_count": len(dynamic_canonicals), "title_count": len(dynamic_h1), "text_retention": round(retention, 6)}, {"canonical": canonical_url, "title": source_h1, "text_retention": ">= 0.9"}, "dynamic DOM does not preserve canonical, title and main content"))
            else:
                checks.append(_check("DYNAMIC_RENDER_MATCH", "dynamic", "pass", canonical_url, round(retention, 6), ">= 0.9", "dynamic DOM preserves canonical, title and main content"))

        checks.sort(key=lambda item: (
            CATEGORY_ORDER[item["category"]], item["code"], item["target"] or "", _canonical(item["observed"])
        ))
        failed = sum(item["status"] == "fail" for item in checks)
        review = sum(item["status"] == "review" for item in checks)
        passed = sum(item["status"] == "pass" for item in checks)
        report_status = "blocked" if failed else "manual_review" if review else "passed"
        findings = [
            {
                "code": item["code"], "category": item["category"],
                "severity": item["severity"], "target": item["target"], "message": item["message"],
            }
            for item in checks if item["status"] != "pass"
        ]
        input_snapshot_hash = _hash({
            "page": {
                "id": page_id, "org_id": tenant, "page_key": page_key,
                "canonical_url": canonical_url, "status": state,
                "snapshot_hash": snapshot_hash,
            },
            "request": request_material,
            "effective_link_observations": {
                url: {
                    "status_code": row.get("status_code"),
                    "final_url": row.get("final_url"),
                    "redirect_chain": row.get("redirect_chain", []),
                    "error_code": row.get("error_code"),
                }
                for url, row in sorted(observations.items())
            },
        })
        report: dict[str, Any] = {
            "org_id": tenant,
            "site_page_version_id": page_id,
            "page_key": page_key,
            "canonical_url": canonical_url,
            "status": report_status,
            "rule_version": RULE_VERSION,
            "threshold_version": threshold_version,
            "input_snapshot_hash": input_snapshot_hash,
            "source_html_hash": source_hash,
            "dynamic_html_hash": dynamic_hash,
            "thresholds": normalized_thresholds,
            "metrics": normalized_metrics,
            "checks": checks,
            "findings": findings,
            "summary": {"total": len(checks), "passed": passed, "failed": failed, "review": review},
            "request_hash": request_hash,
            "idempotency_key": key,
            "evaluated_at": _stamp(at),
            "actor_id": actor,
            "trace_id": trace,
            "created_at": _stamp(at),
        }
        report_hash_material = dict(report)
        for field in ("request_hash", "idempotency_key", "evaluated_at", "actor_id", "trace_id", "created_at"):
            report_hash_material.pop(field, None)
        report["report_hash"] = _hash(report_hash_material)
        report["id"] = str(uuid5(NAMESPACE_URL, f"site-quality:{tenant}:{page_id}:{request_hash}"))
        errors = sorted(VALIDATOR.iter_errors(report), key=lambda item: list(item.path))
        if errors:
            location = ".".join(str(part) for part in errors[0].path) or "report"
            raise SiteQualityError("SITE_QUALITY_REPORT_INVALID", f"{location}: {errors[0].message}")
        self.store.save_command(org_id=tenant, idempotency_key=key, request_hash=request_hash, response=report)
        self.store.save_report(report)
        audit = {
            "task_id": "SITE-004", "event_type": "site.quality.audited",
            "org_id": tenant, "site_page_version_id": page_id,
            "status": report_status, "input_hash": input_snapshot_hash,
            "output_hash": report["report_hash"], "actor_id": actor,
            "trace_id": trace, "idempotency_key": key,
            "duration_ms": 0, "cost_cents": 0, "created_at": _stamp(at),
        }
        with self._lock:
            self.store.audit.append(audit)
        return SiteQualityReport(report)

    check = audit
    inspect = audit

    def get_report(
        self,
        report_id: Any,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
    ) -> SiteQualityReport:
        identity = _uuid(report_id, "report_id")
        context_org = None if tenant_context is None else tenant_context.get("org_id", tenant_context.get("tenant_id"))
        tenant = _uuid(org_id if org_id is not None else context_org, "org_id")
        row = self.store.reports.get(identity)
        if row is None:
            raise SiteQualityError("SITE_QUALITY_REPORT_NOT_FOUND", "site quality report was not found")
        if row["org_id"] != tenant:
            raise SiteQualityError("TENANT_SCOPE_VIOLATION", "site quality report is outside this organization")
        return SiteQualityReport(row)

    def list_reports(
        self,
        *,
        org_id: Any = None,
        tenant_context: Mapping[str, Any] | None = None,
        site_page_version_id: Any = None,
    ) -> tuple[SiteQualityReport, ...]:
        context_org = None if tenant_context is None else tenant_context.get("org_id", tenant_context.get("tenant_id"))
        tenant = _uuid(org_id if org_id is not None else context_org, "org_id")
        page_filter = None if site_page_version_id is None else _uuid(site_page_version_id, "site_page_version_id")
        rows = [
            row for row in self.store.reports.values()
            if row["org_id"] == tenant and (page_filter is None or row["site_page_version_id"] == page_filter)
        ]
        rows.sort(key=lambda item: (item["evaluated_at"], item["id"]))
        return tuple(SiteQualityReport(row) for row in rows)

    def audit_for(self, *, org_id: Any) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        return tuple(deepcopy(row) for row in self.store.audit if row.get("org_id") == tenant)


__all__ = [
    "DEFAULT_THRESHOLDS",
    "InMemorySiteQualityStore",
    "SiteQualityError",
    "SiteQualityReport",
    "SiteQualityService",
]
