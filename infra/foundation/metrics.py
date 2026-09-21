"""Dependency-free health checks and Prometheus-compatible metrics.

The registry is process-local by design.  It provides the foundation contract
for bounded technical/business metrics without exporting traces, contacting a
Prometheus server, or persisting samples.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from threading import RLock
import time
from typing import Any, Callable, Mapping, MutableMapping

from .database import DatabaseConfigurationError, DatabaseSettings, database_health
from .observability import redact


_METRIC_NAME_RE = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]*$")
_LABEL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SENSITIVE_LABEL_RE = re.compile(
    r"(?i)(?:secret|token|password|credential|authorization|payload|prompt|content|query|cookie)"
)
_HEALTH_STATUSES = frozenset(
    {"ready", "configured", "degraded", "unavailable", "invalid_configuration", "not_configured"}
)
_STATUS_PRIORITY = {
    "ready": 0,
    "configured": 1,
    "not_configured": 2,
    "degraded": 3,
    "invalid_configuration": 4,
    "unavailable": 5,
}


class MetricValidationError(ValueError):
    """Raised when a definition, label, or sample is unsafe."""


class MetricDefinitionConflictError(MetricValidationError):
    """Raised when one metric name is registered with another definition."""


def _finite(value: object, name: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricValidationError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise MetricValidationError(f"{name} must be finite")
    if non_negative and number < 0:
        raise MetricValidationError(f"{name} must not be negative")
    return number


def _number(value: float | int) -> str:
    number = float(value)
    if number == 0:
        return "0"
    if number.is_integer():
        return str(int(number))
    return format(number, ".15g")


def _escape_help(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n")


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def _label_text(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{name}="{_escape_label(value)}"' for name, value in labels) + "}"


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    help: str
    kind: str
    scope: str = "technical"
    label_names: tuple[str, ...] = ()
    buckets: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not _METRIC_NAME_RE.fullmatch(self.name):
            raise MetricValidationError("metric name is invalid")
        if not self.help.strip() or len(self.help) > 512 or _CONTROL_RE.search(self.help.replace("\n", "")):
            raise MetricValidationError("metric help is invalid")
        if self.kind not in {"counter", "gauge", "histogram"}:
            raise MetricValidationError("metric kind must be counter, gauge, or histogram")
        if self.scope not in {"technical", "business"}:
            raise MetricValidationError("metric scope must be technical or business")
        if len(set(self.label_names)) != len(self.label_names):
            raise MetricValidationError("metric labels must be unique")
        for label in self.label_names:
            lowered = label.lower()
            if not _LABEL_NAME_RE.fullmatch(label):
                raise MetricValidationError(f"metric label is invalid: {label}")
            if label.startswith("__") or (self.kind == "histogram" and label == "le"):
                raise MetricValidationError(f"reserved metric label is forbidden: {label}")
            if lowered.endswith("_id") or lowered in {"org", "actor", "trace", "request"}:
                raise MetricValidationError(f"high-cardinality identity label is forbidden: {label}")
            if _SENSITIVE_LABEL_RE.search(lowered):
                raise MetricValidationError(f"sensitive metric label is forbidden: {label}")
        normalized_buckets = tuple(_finite(value, "histogram bucket", non_negative=True) for value in self.buckets)
        if self.kind == "histogram":
            if not normalized_buckets or any(value <= 0 for value in normalized_buckets):
                raise MetricValidationError("histogram requires positive finite buckets")
            if tuple(sorted(set(normalized_buckets))) != normalized_buckets:
                raise MetricValidationError("histogram buckets must be unique and increasing")
        elif normalized_buckets:
            raise MetricValidationError("only histograms may define buckets")
        object.__setattr__(self, "buckets", normalized_buckets)


class _Collector:
    def __init__(self, definition: MetricDefinition, lock: RLock) -> None:
        self.definition = definition
        self._lock = lock

    def _labels(self, labels: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
        expected = set(self.definition.label_names)
        actual = set(labels)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise MetricValidationError(f"metric labels do not match definition; missing={missing} extra={extra}")
        values: list[tuple[str, str]] = []
        for name in self.definition.label_names:
            value = str(labels[name]).strip()
            if not value or len(value) > 128 or _CONTROL_RE.search(value):
                raise MetricValidationError(f"metric label value is invalid: {name}")
            values.append((name, value))
        return tuple(values)

    def render(self) -> list[str]:
        raise NotImplementedError


class Counter(_Collector):
    def __init__(self, definition: MetricDefinition, lock: RLock) -> None:
        super().__init__(definition, lock)
        self._samples: dict[tuple[tuple[str, str], ...], float] = {}

    def inc(self, amount: float = 1, **labels: object) -> None:
        value = _finite(amount, "counter amount", non_negative=True)
        label_set = self._labels(labels)
        with self._lock:
            self._samples[label_set] = self._samples.get(label_set, 0.0) + value

    def render(self) -> list[str]:
        with self._lock:
            return [
                f"{self.definition.name}{_label_text(labels)} {_number(value)}"
                for labels, value in sorted(self._samples.items())
            ]


class Gauge(_Collector):
    def __init__(self, definition: MetricDefinition, lock: RLock) -> None:
        super().__init__(definition, lock)
        self._samples: dict[tuple[tuple[str, str], ...], float] = {}

    def set(self, value: float, **labels: object) -> None:
        number = _finite(value, "gauge value")
        label_set = self._labels(labels)
        with self._lock:
            self._samples[label_set] = number

    def inc(self, amount: float = 1, **labels: object) -> None:
        number = _finite(amount, "gauge amount")
        label_set = self._labels(labels)
        with self._lock:
            self._samples[label_set] = self._samples.get(label_set, 0.0) + number

    def dec(self, amount: float = 1, **labels: object) -> None:
        self.inc(-_finite(amount, "gauge amount", non_negative=True), **labels)

    def render(self) -> list[str]:
        with self._lock:
            return [
                f"{self.definition.name}{_label_text(labels)} {_number(value)}"
                for labels, value in sorted(self._samples.items())
            ]


@dataclass
class _HistogramSample:
    buckets: list[int]
    count: int = 0
    total: float = 0.0


class Histogram(_Collector):
    def __init__(self, definition: MetricDefinition, lock: RLock) -> None:
        super().__init__(definition, lock)
        self._samples: dict[tuple[tuple[str, str], ...], _HistogramSample] = {}

    def observe(self, value: float, **labels: object) -> None:
        number = _finite(value, "histogram observation", non_negative=True)
        label_set = self._labels(labels)
        with self._lock:
            sample = self._samples.setdefault(
                label_set,
                _HistogramSample([0 for _ in self.definition.buckets]),
            )
            sample.count += 1
            sample.total += number
            for index, bucket in enumerate(self.definition.buckets):
                if number <= bucket:
                    sample.buckets[index] += 1

    def render(self) -> list[str]:
        result: list[str] = []
        with self._lock:
            for labels, sample in sorted(self._samples.items()):
                for bucket, count in zip(self.definition.buckets, sample.buckets):
                    result.append(
                        f'{self.definition.name}_bucket{_label_text(labels + (("le", _number(bucket)),))} {count}'
                    )
                result.append(
                    f'{self.definition.name}_bucket{_label_text(labels + (("le", "+Inf"),))} {sample.count}'
                )
                result.append(f"{self.definition.name}_sum{_label_text(labels)} {_number(sample.total)}")
                result.append(f"{self.definition.name}_count{_label_text(labels)} {sample.count}")
        return result


class MetricRegistry:
    """Thread-safe in-process collector registry."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._collectors: MutableMapping[str, _Collector] = {}

    def register(self, definition: MetricDefinition) -> _Collector:
        with self._lock:
            existing = self._collectors.get(definition.name)
            if existing is not None:
                if existing.definition != definition:
                    raise MetricDefinitionConflictError(f"metric definition conflicts: {definition.name}")
                return existing
            collector_type = {"counter": Counter, "gauge": Gauge, "histogram": Histogram}[definition.kind]
            collector = collector_type(definition, self._lock)
            self._collectors[definition.name] = collector
            return collector

    def counter(
        self,
        name: str,
        help: str,
        *,
        scope: str = "technical",
        label_names: tuple[str, ...] = (),
    ) -> Counter:
        collector = self.register(MetricDefinition(name, help, "counter", scope, label_names))
        if not isinstance(collector, Counter):  # pragma: no cover - guarded by definition equality
            raise MetricDefinitionConflictError(f"metric is not a counter: {name}")
        return collector

    def gauge(
        self,
        name: str,
        help: str,
        *,
        scope: str = "technical",
        label_names: tuple[str, ...] = (),
    ) -> Gauge:
        collector = self.register(MetricDefinition(name, help, "gauge", scope, label_names))
        if not isinstance(collector, Gauge):  # pragma: no cover
            raise MetricDefinitionConflictError(f"metric is not a gauge: {name}")
        return collector

    def histogram(
        self,
        name: str,
        help: str,
        *,
        buckets: tuple[float, ...],
        scope: str = "technical",
        label_names: tuple[str, ...] = (),
    ) -> Histogram:
        collector = self.register(MetricDefinition(name, help, "histogram", scope, label_names, buckets))
        if not isinstance(collector, Histogram):  # pragma: no cover
            raise MetricDefinitionConflictError(f"metric is not a histogram: {name}")
        return collector

    def prometheus_text(self) -> str:
        lines: list[str] = []
        with self._lock:
            collectors = [self._collectors[name] for name in sorted(self._collectors)]
            for collector in collectors:
                definition = collector.definition
                lines.append(f"# HELP {definition.name} {_escape_help(definition.help)}")
                lines.append(f"# TYPE {definition.name} {definition.kind}")
                lines.extend(collector.render())
        return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class HealthCheckResult:
    component: str
    status: str
    critical: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _LABEL_NAME_RE.fullmatch(self.component):
            raise ValueError("health component is invalid")
        if self.status not in _HEALTH_STATUSES:
            raise ValueError("health status is invalid")

    def as_contract(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status,
            "critical": self.critical,
            "details": redact(dict(self.details)),
        }


@dataclass(frozen=True)
class HealthSnapshot:
    status: str
    checks: tuple[HealthCheckResult, ...]

    def as_contract(self) -> dict[str, Any]:
        return {"status": self.status, "checks": {item.component: item.as_contract() for item in self.checks}}


HealthCheck = Callable[[], HealthCheckResult]


class HealthRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, tuple[HealthCheck, bool]] = {}

    def register(self, component: str, check: HealthCheck, *, critical: bool = True) -> None:
        if not _LABEL_NAME_RE.fullmatch(component):
            raise ValueError("health component is invalid")
        if component in self._checks:
            raise ValueError(f"health component already registered: {component}")
        self._checks[component] = (check, critical)

    def readiness(self) -> HealthSnapshot:
        results: list[HealthCheckResult] = []
        for component in sorted(self._checks):
            check, critical = self._checks[component]
            try:
                result = check()
                if result.component != component:
                    raise ValueError("health result component does not match registration")
                if result.critical != critical:
                    result = HealthCheckResult(result.component, result.status, critical, result.details)
            except Exception:
                result = HealthCheckResult(
                    component=component,
                    status="unavailable",
                    critical=critical,
                    details={"reason": "health check failed"},
                )
            results.append(result)
        critical_results = [item for item in results if item.critical]
        considered = critical_results or results
        status = max(considered, key=lambda item: _STATUS_PRIORITY[item.status]).status if considered else "ready"
        return HealthSnapshot(status=status, checks=tuple(results))


def database_check() -> HealthCheckResult:
    try:
        snapshot = database_health(DatabaseSettings.from_env())
    except DatabaseConfigurationError as exc:
        snapshot = {
            "status": "invalid_configuration",
            "configured": False,
            "engine": "postgresql",
            "probe": "skipped",
            "reason": str(exc),
        }
    return HealthCheckResult("database", str(snapshot["status"]), True, snapshot)


def default_health_registry() -> HealthRegistry:
    registry = HealthRegistry()
    registry.register("database", database_check)
    return registry


@dataclass(frozen=True)
class DefaultMetrics:
    http_requests: Counter
    http_duration: Histogram
    dependency_ready: Gauge
    business_events: Counter


def register_default_metrics(registry: MetricRegistry) -> DefaultMetrics:
    labels = ("method", "route", "status_class")
    return DefaultMetrics(
        http_requests=registry.counter(
            "http_requests_total",
            "HTTP requests completed by method, route template, and status class.",
            label_names=labels,
        ),
        http_duration=registry.histogram(
            "http_request_duration_seconds",
            "HTTP request duration in seconds.",
            label_names=labels,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        ),
        dependency_ready=registry.gauge(
            "dependency_ready",
            "Whether a dependency health check reports ready.",
            label_names=("component",),
        ),
        business_events=registry.counter(
            "business_events_total",
            "Business events recorded by bounded event type and outcome.",
            scope="business",
            label_names=("event_type", "outcome"),
        ),
    )


def default_metric_registry() -> MetricRegistry:
    registry = MetricRegistry()
    register_default_metrics(registry)
    return registry


class ApiMetricsMiddleware:
    """Record bounded HTTP metrics using Starlette route templates."""

    def __init__(self, app: Any, *, registry: MetricRegistry) -> None:
        self.app = app
        self.metrics = register_default_metrics(registry)

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 200))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = getattr(scope.get("route"), "path", None) or "__unmatched__"
            labels = {
                "method": str(scope.get("method", "UNKNOWN")).upper(),
                "route": str(route),
                "status_class": f"{status_code // 100}xx",
            }
            self.metrics.http_requests.inc(**labels)
            self.metrics.http_duration.observe(max(0.0, time.perf_counter() - started), **labels)


__all__ = [
    "ApiMetricsMiddleware",
    "Counter",
    "DefaultMetrics",
    "Gauge",
    "HealthCheck",
    "HealthCheckResult",
    "HealthRegistry",
    "HealthSnapshot",
    "Histogram",
    "MetricDefinition",
    "MetricDefinitionConflictError",
    "MetricRegistry",
    "MetricValidationError",
    "database_check",
    "default_health_registry",
    "default_metric_registry",
    "register_default_metrics",
]
