"""OpenTelemetry tracing with local-by-default W3C propagation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import re
from typing import Any, Iterator, Mapping, MutableMapping

from opentelemetry.propagators.textmap import CarrierT
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer, get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from .observability import get_tenant_context


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ /:-]{0,127}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_BLOCKED_ATTRIBUTE_RE = re.compile(
    r"(?i)(?:org[_-]?id|actor[_-]?id|headers?|query|url|body|payload|prompt|content|token|secret|password|credential|authorization|cookie)"
)


class TraceValidationError(ValueError):
    """Raised when a caller tries to attach unsafe trace data."""


def _span_id(span: Span) -> tuple[str, str, int]:
    context = span.get_span_context()
    return f"{context.trace_id:032x}", f"{context.span_id:016x}", int(context.trace_flags)


def _safe_attributes(attributes: Mapping[str, object] | None) -> dict[str, str | bool | int | float]:
    result: dict[str, str | bool | int | float] = {}
    for key, value in (attributes or {}).items():
        name = str(key)
        if not _NAME_RE.fullmatch(name) or _BLOCKED_ATTRIBUTE_RE.search(name):
            raise TraceValidationError(f"span attribute is not allowed: {name}")
        if isinstance(value, bool):
            result[name] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            result[name] = value
        elif isinstance(value, str):
            normalized = value.strip()
            if not normalized or len(normalized) > 256 or _CONTROL_RE.search(normalized):
                raise TraceValidationError(f"span attribute value is invalid: {name}")
            result[name] = normalized
        else:
            raise TraceValidationError(f"span attribute value type is invalid: {name}")
    return result


@dataclass(frozen=True)
class TracingRuntime:
    service_name: str
    provider: TracerProvider
    tracer: Tracer
    exporter: SpanExporter

    @contextmanager
    def start_span(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[Span]:
        if not _NAME_RE.fullmatch(name):
            raise TraceValidationError("span name is invalid")
        safe_attributes = _safe_attributes(attributes)
        with self.tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=safe_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except Exception as exc:
                span.set_attribute("exception.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return bool(self.provider.force_flush(timeout_millis=timeout_millis))

    def shutdown(self) -> None:
        self.provider.shutdown()


def create_tracing_runtime(
    service_name: str = "api",
    *,
    exporter: SpanExporter | None = None,
) -> TracingRuntime:
    if not _NAME_RE.fullmatch(service_name):
        raise TraceValidationError("service_name is invalid")
    selected_exporter = exporter or InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(selected_exporter))
    tracer = provider.get_tracer("ai_workflow.foundation", "1.0.0")
    return TracingRuntime(service_name, provider, tracer, selected_exporter)


def current_trace_headers() -> dict[str, str]:
    span = get_current_span()
    context = span.get_span_context()
    if not context.is_valid:
        return {}
    trace_id, span_id, flags = _span_id(span)
    return {
        "traceparent": f"00-{trace_id}-{span_id}-{flags:02x}",
        "X-Trace-Id": trace_id,
        "X-Span-Id": span_id,
    }


class OpenTelemetryMiddleware:
    """Create one server span and propagate a safe correlation trace ID."""

    def __init__(self, app: Any, *, runtime: TracingRuntime) -> None:
        self.app = app
        self.runtime = runtime
        self.propagator = TraceContextTextMapPropagator()

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        carrier: CarrierT = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        parent = self.propagator.extract(carrier=carrier)
        method = str(scope.get("method", "UNKNOWN")).upper()
        status_code = 500
        with self.runtime.tracer.start_as_current_span(
            f"{method} http.request",
            context=parent,
            kind=SpanKind.SERVER,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            trace_id, span_id, flags = _span_id(span)
            headers = list(scope.get("headers", []))
            if not any(name.lower() == b"x-trace-id" for name, _ in headers):
                headers.append((b"x-trace-id", trace_id.encode("ascii")))
                scope["headers"] = headers

            async def send_wrapper(message: MutableMapping[str, Any]) -> None:
                nonlocal status_code
                if message.get("type") == "http.response.start":
                    status_code = int(message.get("status", 200))
                    response_headers = [
                        (name, value)
                        for name, value in message.get("headers", [])
                        if name.lower() not in {b"traceparent", b"x-span-id"}
                    ]
                    response_headers.extend(
                        [
                            (b"traceparent", f"00-{trace_id}-{span_id}-{flags:02x}".encode("ascii")),
                            (b"x-span-id", span_id.encode("ascii")),
                        ]
                    )
                    message = dict(message)
                    message["headers"] = response_headers
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception as exc:
                span.set_attribute("exception.type", type(exc).__name__)
                status_code = 500
                raise
            finally:
                route = getattr(scope.get("route"), "path", None) or "__unmatched__"
                span.update_name(f"{method} {route}")
                span.set_attribute("http.request.method", method)
                span.set_attribute("http.route", str(route))
                span.set_attribute("http.response.status_code", status_code)
                span.set_attribute("http.response.status_class", f"{status_code // 100}xx")
                context = scope.get("state", {}).get("tenant_context") or get_tenant_context()
                if context is not None:
                    span.set_attribute("correlation.trace_id", context.trace_id)
                    span.set_attribute("correlation.request_id", context.request_id)
                span.set_status(Status(StatusCode.ERROR if status_code >= 500 else StatusCode.UNSET))


__all__ = [
    "OpenTelemetryMiddleware",
    "TraceValidationError",
    "TracingRuntime",
    "create_tracing_runtime",
    "current_trace_headers",
]
