"""Request correlation, API errors, and dependency-free structured logging.

This module deliberately stays at the foundation boundary.  It does not import
an ORM, a telemetry SDK, or a provider client; applications may later bridge
the emitted JSON records to those systems without changing request semantics.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
import time
from typing import Any, Iterator, Mapping, MutableMapping
from uuid import uuid4


_MAX_ID_LENGTH = 256
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_SECRET_KEY_RE = re.compile(
    r"(?i)(?:secret|token|password|credential|authorization|private[_-]?key|cookie|set-cookie)"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:bearer\s+[^\s,;]+|(?:api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+|-----BEGIN[^-]*PRIVATE KEY-----)"
)
_CORRELATION_HEADER_NAMES = {
    "x-trace-id": "trace_id",
    "x-request-id": "request_id",
    "x-org-id": "org_id",
    "x-actor-id": "actor_id",
}
_CORRELATION_RESPONSE_HEADERS = {
    "trace_id": "X-Trace-Id",
    "request_id": "X-Request-Id",
    "org_id": "X-Org-Id",
    "actor_id": "X-Actor-Id",
}


class CorrelationContextError(ValueError):
    """Raised when a request correlation value is unsafe or malformed."""

    code = "INVALID_CORRELATION_CONTEXT"


def _safe_id(value: object, name: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise CorrelationContextError(f"{name} is required")
        return None
    normalized = str(value).strip()
    if not normalized:
        if required:
            raise CorrelationContextError(f"{name} must not be empty")
        return None
    if len(normalized) > _MAX_ID_LENGTH or _CONTROL_RE.search(normalized):
        raise CorrelationContextError(f"{name} contains an invalid value")
    return normalized


@dataclass(frozen=True)
class TenantContext:
    """Immutable request-scoped identity and correlation values.

    ``org_id`` and ``actor_id`` remain optional until the IAM task supplies an
    authenticated identity.  The foundation layer still validates their shape
    and never trusts control characters or unbounded header values.
    """

    trace_id: str
    request_id: str
    org_id: str | None = None
    actor_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _safe_id(self.trace_id, "trace_id", required=True))
        object.__setattr__(self, "request_id", _safe_id(self.request_id, "request_id", required=True))
        object.__setattr__(self, "org_id", _safe_id(self.org_id, "org_id"))
        object.__setattr__(self, "actor_id", _safe_id(self.actor_id, "actor_id"))

    @classmethod
    def new(cls) -> "TenantContext":
        return cls(trace_id=str(uuid4()), request_id=str(uuid4()))

    @classmethod
    def from_headers(cls, headers: Mapping[str, object] | None = None) -> "TenantContext":
        values: dict[str, object] = {}
        traceparent: str | None = None
        for key, value in (headers or {}).items():
            normalized_key = str(key).lower()
            field = _CORRELATION_HEADER_NAMES.get(normalized_key)
            if field:
                values[field] = value
            elif normalized_key == "traceparent":
                traceparent = _safe_id(value, "traceparent", required=True)
        parent_trace_id: str | None = None
        if traceparent is not None:
            match = _TRACEPARENT_RE.fullmatch(traceparent.lower())
            if not match or match.group(1) == "0" * 32 or match.group(2) == "0" * 16:
                raise CorrelationContextError("traceparent contains an invalid value")
            parent_trace_id = match.group(1)
        def header_id(name: str, *, generated: bool = False) -> str | None:
            if name not in values:
                if name == "trace_id" and parent_trace_id:
                    return parent_trace_id
                return str(uuid4()) if generated else None
            return _safe_id(values[name], name, required=True)

        trace_id = header_id("trace_id", generated=True) or str(uuid4())
        if parent_trace_id and re.fullmatch(r"[0-9a-fA-F]{32}", trace_id) and trace_id.lower() != parent_trace_id:
            raise CorrelationContextError("trace_id conflicts with traceparent")
        return cls(
            trace_id=trace_id,
            request_id=header_id("request_id", generated=True) or str(uuid4()),
            org_id=header_id("org_id"),
            actor_id=header_id("actor_id"),
        )

    def as_dict(self) -> dict[str, str | None]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "org_id": self.org_id,
            "actor_id": self.actor_id,
        }


_context: ContextVar[TenantContext | None] = ContextVar("tenant_context", default=None)


def get_tenant_context() -> TenantContext | None:
    return _context.get()


def get_correlation_context() -> TenantContext | None:
    return get_tenant_context()


def set_tenant_context(context: TenantContext) -> Token[TenantContext | None]:
    return _context.set(context)


def reset_tenant_context(token: Token[TenantContext | None]) -> None:
    _context.reset(token)


@contextmanager
def tenant_context_scope(context: TenantContext) -> Iterator[TenantContext]:
    token = set_tenant_context(context)
    try:
        yield context
    finally:
        reset_tenant_context(token)


def _redact(value: Any, *, key: str | None = None) -> Any:
    if key and _SECRET_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = _CONTROL_RE.sub(" ", value)
        value = _SECRET_VALUE_RE.sub("[REDACTED]", value)
        return value[:4096]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact(str(value))


def redact(value: Any) -> Any:
    """Return a bounded, JSON-safe value with secret-like fields removed."""

    return _redact(value)


def _retryable_status(status_code: int) -> bool:
    return status_code >= 500 or status_code in {408, 425, 429}


class ApiError(Exception):
    """Stable, serializable API error independent of a transport framework."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: Mapping[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        normalized_code = _safe_id(code, "code", required=True)
        normalized_message = _safe_id(message, "message", required=True)
        if status_code < 400 or status_code > 599:
            raise ValueError("status_code must be between 400 and 599")
        self.code = normalized_code
        self.message = normalized_message
        self.status_code = status_code
        self.details = dict(details or {})
        self.retryable = _retryable_status(status_code) if retryable is None else bool(retryable)
        super().__init__(self.message)

    def as_dict(self, context: TenantContext | None = None) -> dict[str, Any]:
        current = context or get_tenant_context() or TenantContext.new()
        return {
            "code": self.code,
            "message": redact(self.message),
            "details": redact(self.details),
            **current.as_dict(),
            "retryable": self.retryable,
        }


def api_error_from_http_exception(exc: Any) -> ApiError:
    """Translate a FastAPI/Starlette HTTPException without leaking its detail."""

    status = int(getattr(exc, "status_code", 500))
    detail = getattr(exc, "detail", None)
    if isinstance(detail, Mapping):
        code = str(detail.get("code") or f"HTTP_{status}")
        message = str(detail.get("message") or "request rejected")
        details = {str(k): v for k, v in detail.items() if k not in {"code", "message"}}
    elif detail is None:
        code, message, details = f"HTTP_{status}", "request rejected", {}
    else:
        code, message, details = f"HTTP_{status}", str(detail), {}
    return ApiError(code, message, status_code=status, details=details)


def structured_log(
    event: str,
    *,
    level: str = "INFO",
    service: str = "api",
    context: TenantContext | None = None,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    duration_ms: int | None = None,
    error_type: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = context or get_tenant_context() or TenantContext.new()
    value: dict[str, Any] = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level.upper(),
        "service": service,
        **current.as_dict(),
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }
    if error_type:
        value["error_type"] = error_type
    if fields:
        reserved = {"event", "timestamp", "level", "service", "trace_id", "request_id", "org_id", "actor_id"}
        value.update({key: redact(item) for key, item in fields.items() if str(key) not in reserved})
    return redact(value)


def structured_log_json(*args: Any, **kwargs: Any) -> str:
    return json.dumps(structured_log(*args, **kwargs), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class JsonLogFormatter(logging.Formatter):
    """Formatter that guarantees one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.msg, Mapping):
            payload = redact(dict(record.msg))
        else:
            try:
                candidate = json.loads(record.getMessage())
            except (TypeError, ValueError):
                candidate = {"event": "log", "message": record.getMessage()}
            payload = redact(candidate if isinstance(candidate, Mapping) else {"event": "log", "message": candidate})
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
        payload.setdefault("level", record.levelname)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


StructuredLogFormatter = JsonLogFormatter


def configure_structured_logging(logger: logging.Logger | None = None, *, level: int = logging.INFO) -> logging.Logger:
    target = logger or logging.getLogger("ai_workflow")
    target.setLevel(level)
    if not any(getattr(handler, "_ai_workflow_json", False) for handler in target.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        handler._ai_workflow_json = True  # type: ignore[attr-defined]
        target.addHandler(handler)
    return target


def _header_bytes(context: TenantContext) -> list[tuple[bytes, bytes]]:
    return [
        (header.encode("ascii"), str(value).encode("utf-8"))
        for field, header in _CORRELATION_RESPONSE_HEADERS.items()
        if (value := getattr(context, field)) is not None
    ]


def _with_correlation_headers(headers: list[tuple[bytes, bytes]], context: TenantContext) -> list[tuple[bytes, bytes]]:
    correlation_names = {name.lower() for name, _ in _header_bytes(context)}
    result = [(name, value) for name, value in headers if name.lower() not in correlation_names]
    result.extend(_header_bytes(context))
    return result


async def _send_json_error(send: Any, error: ApiError, context: TenantContext) -> None:
    payload = {"detail": error.as_dict(context)}
    payload.update(context.as_dict())
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))]
    headers.extend(_header_bytes(context))
    await send({"type": "http.response.start", "status": error.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class CorrelationMiddleware:
    """Pure ASGI middleware that scopes IDs and enriches JSON responses/logs."""

    def __init__(self, app: Any, *, logger: logging.Logger | None = None, service: str = "api") -> None:
        self.app = app
        self.logger = logger or logging.getLogger("ai_workflow.api")
        self.service = service

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = {
            key.decode("latin1"): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        try:
            context = TenantContext.from_headers(raw_headers)
        except CorrelationContextError as exc:
            context = TenantContext.new()
            started = time.perf_counter()
            await _send_json_error(send, ApiError(exc.code, str(exc), status_code=400), context)
            self.logger.info(
                structured_log_json(
                    "http.request.completed",
                    service=self.service,
                    context=context,
                    method=str(scope.get("method", "")),
                    path=str(scope.get("path", "")),
                    status_code=400,
                    duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                    error_type=type(exc).__name__,
                )
            )
            return

        scope.setdefault("state", {})["tenant_context"] = context
        token = set_tenant_context(context)
        started = time.perf_counter()
        response_started = False
        response_sent = False
        status_code = 500
        logged = False
        response_start: MutableMapping[str, Any] | None = None
        body_parts: list[bytes] = []
        buffer_json = False
        try:
            async def send_wrapper(message: MutableMapping[str, Any]) -> None:
                nonlocal response_started, response_sent, status_code, logged, response_start, body_parts, buffer_json
                if message.get("type") == "http.response.start":
                    response_started = True
                    status_code = int(message.get("status", 200))
                    response_start = dict(message)
                    headers = list(response_start.get("headers", []))
                    content_type = next(
                        (value.decode("latin1") for name, value in headers if name.lower() == b"content-type"),
                        "",
                    )
                    buffer_json = "json" in content_type.lower()
                    if not buffer_json:
                        response_start["headers"] = _with_correlation_headers(headers, context)
                        await send(response_start)
                        response_sent = True
                    return
                if message.get("type") != "http.response.body":
                    await send(message)
                    return
                if not buffer_json:
                    if not response_sent:
                        start = response_start or {
                            "type": "http.response.start",
                            "status": status_code,
                            "headers": _with_correlation_headers([], context),
                        }
                        await send(start)
                        response_sent = True
                    await send(message)
                    if not message.get("more_body", False) and not logged:
                        logged = True
                        self.logger.info(
                            structured_log_json(
                                "http.request.completed",
                                service=self.service,
                                context=context,
                                method=str(scope.get("method", "")),
                                path=str(scope.get("path", "")),
                                status_code=status_code,
                                duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                                error_type=scope.get("state", {}).get("error_type"),
                            )
                        )
                    return
                body_parts.append(bytes(message.get("body", b"")))
                if message.get("more_body", False):
                    return
                start = response_start or {"type": "http.response.start", "status": status_code, "headers": []}
                headers = list(start.get("headers", []))
                body = b"".join(body_parts)
                content_type = next(
                    (value.decode("latin1") for name, value in headers if name.lower() == b"content-type"),
                    "",
                )
                if body and "json" in content_type.lower():
                    try:
                        document = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        document = None
                    if isinstance(document, dict):
                        document.update(context.as_dict())
                        if isinstance(document.get("detail"), dict):
                            document["detail"].update(context.as_dict())
                        body = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    headers = [(name, value) for name, value in headers if name.lower() != b"content-length"]
                headers = _with_correlation_headers(headers, context)
                headers = [(name, value) for name, value in headers if name.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode("ascii")))
                start["headers"] = headers
                await send(start)
                response_sent = True
                await send({"type": "http.response.body", "body": body})
                body_parts = []
                response_start = None
                if not logged:
                    logged = True
                    self.logger.info(
                        structured_log_json(
                            "http.request.completed",
                            service=self.service,
                            context=context,
                            method=str(scope.get("method", "")),
                            path=str(scope.get("path", "")),
                            status_code=status_code,
                            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                            error_type=scope.get("state", {}).get("error_type"),
                        )
                    )

            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if not response_sent:
                scope.setdefault("state", {})["error_type"] = type(exc).__name__
                if response_start is None:
                    await _send_json_error(send, ApiError("INTERNAL_ERROR", "internal server error", status_code=500), context)
                else:
                    raise
                self.logger.info(
                    structured_log_json(
                        "http.request.completed",
                        service=self.service,
                        context=context,
                        method=str(scope.get("method", "")),
                        path=str(scope.get("path", "")),
                        status_code=500,
                        duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                        error_type=type(exc).__name__,
                    )
                )
                logged = True
            else:
                raise
        finally:
            reset_tenant_context(token)


def install_api_observability(app: Any, *, logger: logging.Logger | None = None) -> Any:
    """Install middleware and framework exception handlers on a FastAPI app."""

    from fastapi import HTTPException, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse

    target_logger = logger or logging.getLogger("ai_workflow.api")

    def context_for(request: Request) -> TenantContext:
        context = getattr(getattr(request, "state", None), "tenant_context", None)
        return context or get_tenant_context() or TenantContext.new()

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.as_dict(context_for(request))})

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        error = api_error_from_http_exception(exc)
        return JSONResponse(status_code=error.status_code, content={"detail": error.as_dict(context_for(request))})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": ApiError(
                    "REQUEST_VALIDATION_ERROR",
                    "request validation failed",
                    status_code=422,
                    details={"errors": exc.errors()},
                ).as_dict(context_for(request))
            },
        )

    @app.exception_handler(Exception)
    async def unknown_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request.state.error_type = type(exc).__name__
        target_logger.info(
            structured_log_json(
                "api.exception",
                service="api",
                context=context_for(request),
                method=request.method,
                path=request.url.path,
                status_code=500,
                error_type=type(exc).__name__,
            )
        )
        return JSONResponse(
            status_code=500,
            content={"detail": ApiError("INTERNAL_ERROR", "internal server error", status_code=500).as_dict(context_for(request))},
        )

    app.add_middleware(CorrelationMiddleware, logger=target_logger)
    return app


# Compatibility aliases for callers that use the shorter names.
RequestContext = TenantContext
CorrelationContext = TenantContext
StructuredLogger = configure_structured_logging


__all__ = [
    "ApiError",
    "CorrelationContext",
    "CorrelationContextError",
    "CorrelationMiddleware",
    "JsonLogFormatter",
    "RequestContext",
    "StructuredLogFormatter",
    "StructuredLogger",
    "TenantContext",
    "api_error_from_http_exception",
    "configure_structured_logging",
    "get_correlation_context",
    "get_tenant_context",
    "install_api_observability",
    "redact",
    "reset_tenant_context",
    "set_tenant_context",
    "structured_log",
    "structured_log_json",
    "tenant_context_scope",
]
