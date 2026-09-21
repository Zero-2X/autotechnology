from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient


def test_counter_gauge_histogram_and_business_metrics_render_deterministically() -> None:
    from infra.foundation.metrics import MetricRegistry

    registry = MetricRegistry()
    counter = registry.counter("jobs_total", "Jobs completed.", label_names=("outcome",))
    gauge = registry.gauge("queue_depth", "Queue depth.", label_names=("queue",))
    histogram = registry.histogram(
        "job_duration_seconds",
        "Job duration.",
        label_names=("job_type",),
        buckets=(0.1, 0.5, 1.0),
    )
    business = registry.counter(
        "content_events_total",
        "Content events.",
        scope="business",
        label_names=("event_type", "outcome"),
    )

    counter.inc(outcome="succeeded")
    counter.inc(2, outcome="succeeded")
    gauge.set(4, queue="default")
    histogram.observe(0.25, job_type="synthetic")
    business.inc(event_type="content_created", outcome="accepted")

    text = registry.prometheus_text()
    assert 'jobs_total{outcome="succeeded"} 3' in text
    assert 'queue_depth{queue="default"} 4' in text
    assert 'job_duration_seconds_bucket{job_type="synthetic",le="0.1"} 0' in text
    assert 'job_duration_seconds_bucket{job_type="synthetic",le="0.5"} 1' in text
    assert 'job_duration_seconds_bucket{job_type="synthetic",le="+Inf"} 1' in text
    assert 'job_duration_seconds_sum{job_type="synthetic"} 0.25' in text
    assert 'content_events_total{event_type="content_created",outcome="accepted"} 1' in text
    assert text == registry.prometheus_text()


def test_invalid_samples_and_labels_do_not_create_partial_series() -> None:
    from infra.foundation.metrics import MetricRegistry, MetricValidationError

    registry = MetricRegistry()
    counter = registry.counter("safe_total", "Safe counter.", label_names=("outcome",))
    histogram = registry.histogram("safe_seconds", "Safe duration.", buckets=(1.0,))
    with pytest.raises(MetricValidationError):
        counter.inc(-1, outcome="failed")
    with pytest.raises(MetricValidationError):
        counter.inc(outcome="failed", extra="value")
    with pytest.raises(MetricValidationError):
        counter.inc(outcome="bad\nvalue")
    with pytest.raises(MetricValidationError):
        histogram.observe(math.inf)
    text = registry.prometheus_text()
    assert "safe_total{" not in text
    assert "safe_seconds_bucket{" not in text


def test_liveness_skips_checks_and_readiness_redacts_check_failures() -> None:
    from apps.api.main import create_app
    from infra.foundation.metrics import HealthRegistry, MetricRegistry

    calls = 0

    def failing_check():
        nonlocal calls
        calls += 1
        raise RuntimeError("password=must-not-leak")

    health = HealthRegistry()
    health.register("database", failing_check)
    client = TestClient(create_app(health_registry=health, metric_registry=MetricRegistry()))

    live = client.get("/health/live")
    assert live.status_code == 200
    assert calls == 0
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert calls == 1
    assert ready.json()["status"] == "unavailable"
    assert ready.json()["dependencies"]["checks"]["database"]["details"] == {
        "reason": "health check failed"
    }
    assert "must-not-leak" not in ready.text


def test_api_exposes_route_template_metrics_without_self_scraping() -> None:
    from apps.api.main import create_app
    from infra.foundation.metrics import MetricRegistry

    metrics = MetricRegistry()
    app = create_app(metric_registry=metrics)

    @app.get("/synthetic/{item_key}")
    def synthetic(item_key: str) -> dict[str, str]:
        return {"item_key": item_key}

    client = TestClient(app)
    assert client.get("/health/live").status_code == 200
    assert client.get("/synthetic/private-object-123").status_code == 200

    first = client.get("/metrics")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert 'http_requests_total{method="GET",route="/health/live",status_class="2xx"} 1' in first.text
    assert 'http_request_duration_seconds_count{method="GET",route="/health/live",status_class="2xx"} 1' in first.text
    assert 'route="/synthetic/{item_key}"' in first.text
    assert "private-object-123" not in first.text
    assert "org_id" not in first.text
    assert "trace_id" not in first.text

    second = client.get("/metrics")
    assert second.text == first.text
