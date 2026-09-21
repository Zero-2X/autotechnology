from __future__ import annotations

from datetime import datetime, timezone
import json
import logging

import pytest
from fastapi.testclient import TestClient


def _finished(runtime):
    runtime.force_flush()
    return runtime.exporter.get_finished_spans()


def test_api_server_span_unifies_generated_trace_response_body_and_log(caplog) -> None:
    from apps.api.main import create_app
    from infra.foundation.tracing import create_tracing_runtime

    caplog.set_level(logging.INFO, logger="ai_workflow.api")
    runtime = create_tracing_runtime("api-test")
    response = TestClient(create_app(tracing_runtime=runtime)).get("/health/live")

    assert response.status_code == 200
    trace_id = response.json()["trace_id"]
    assert len(trace_id) == 32
    assert response.headers["X-Trace-Id"] == trace_id
    assert response.headers["traceparent"].split("-")[1] == trace_id
    assert response.headers["traceparent"].split("-")[2] == response.headers["X-Span-Id"]

    span = _finished(runtime)[-1]
    assert f"{span.context.trace_id:032x}" == trace_id
    assert span.name == "GET /health/live"
    assert span.attributes["http.route"] == "/health/live"
    assert span.attributes["correlation.trace_id"] == trace_id
    records = [json.loads(record.getMessage()) for record in caplog.records if record.name == "ai_workflow.api"]
    assert records[-1]["trace_id"] == trace_id


def test_w3c_parent_child_and_legacy_correlation_are_distinct_and_safe() -> None:
    from apps.api.main import create_app
    from infra.foundation.tracing import create_tracing_runtime

    runtime = create_tracing_runtime("api-test")
    parent_trace = "0123456789abcdef0123456789abcdef"
    parent_span = "0123456789abcdef"
    client = TestClient(create_app(tracing_runtime=runtime))
    inherited = client.get(
        "/health/live",
        headers={"traceparent": f"00-{parent_trace}-{parent_span}-01"},
    )
    assert inherited.status_code == 200
    assert inherited.json()["trace_id"] == parent_trace
    first_span = _finished(runtime)[-1]
    assert f"{first_span.context.trace_id:032x}" == parent_trace
    assert first_span.parent.span_id == int(parent_span, 16)

    legacy = client.get("/health/live", headers={"X-Trace-Id": "legacy-trace"})
    assert legacy.status_code == 200
    assert legacy.json()["trace_id"] == "legacy-trace"
    legacy_span = _finished(runtime)[-1]
    assert legacy_span.attributes["correlation.trace_id"] == "legacy-trace"
    assert f"{legacy_span.context.trace_id:032x}" != "legacy-trace"

    with runtime.start_span("foundation.parent", attributes={"component": "fixture"}) as parent:
        with runtime.start_span("foundation.child", attributes={"operation": "synthetic"}) as child:
            assert child.get_span_context().trace_id == parent.get_span_context().trace_id
    spans = _finished(runtime)
    child_data = next(item for item in spans if item.name == "foundation.child")
    parent_data = next(item for item in spans if item.name == "foundation.parent")
    assert child_data.parent.span_id == parent_data.context.span_id


def test_invalid_traceparent_and_unsafe_span_attributes_are_rejected() -> None:
    from apps.api.main import create_app
    from infra.foundation.tracing import TraceValidationError, create_tracing_runtime

    runtime = create_tracing_runtime("api-test")
    response = TestClient(create_app(tracing_runtime=runtime)).get(
        "/health/live",
        headers={"traceparent": "00-not-a-trace-not-a-span-01"},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_CORRELATION_CONTEXT"
    assert "not-a-trace" not in response.text

    with pytest.raises(TraceValidationError):
        with runtime.start_span("unsafe", attributes={"org_id": "org-a"}):
            pass
    with pytest.raises(TraceValidationError):
        with runtime.start_span("unsafe", attributes={"prompt": "raw prompt"}):
            pass


def test_server_span_uses_route_template_and_excludes_sensitive_request_data() -> None:
    from apps.api.main import create_app
    from infra.foundation.tracing import create_tracing_runtime

    runtime = create_tracing_runtime("api-test")
    app = create_app(tracing_runtime=runtime)

    @app.get("/synthetic/{item_key}")
    def synthetic(item_key: str) -> dict[str, str]:
        return {"item_key": item_key}

    response = TestClient(app).get(
        "/synthetic/private-object-123?token=must-not-appear",
        headers={"X-Org-Id": "org-private", "X-Actor-Id": "actor-private"},
    )
    assert response.status_code == 200
    span = _finished(runtime)[-1]
    assert span.attributes["http.route"] == "/synthetic/{item_key}"
    encoded = json.dumps(dict(span.attributes))
    for forbidden in ("private-object-123", "must-not-appear", "org-private", "actor-private"):
        assert forbidden not in encoded


def test_cost_recorder_is_append_only_idempotent_and_tenant_scoped() -> None:
    from infra.foundation.costs import CostIdempotencyConflictError, CostRecorder, InMemoryCostSink
    from infra.foundation.observability import TenantContext

    sink = InMemoryCostSink()
    recorder = CostRecorder(sink)
    first_context = TenantContext("trace-one", "request-one", "org-a", "actor-a")
    replay_context = TenantContext("trace-two", "request-two", "org-a", "actor-a")
    values = {
        "service": "model-gateway",
        "operation": "generate",
        "provider": "fake",
        "model": "fixture-model",
        "input_units": 10,
        "output_units": 5,
        "cost_cents": 2,
        "latency_ms": 12,
        "status": "succeeded",
        "idempotency_key": "cost-key-001",
        "occurred_at": datetime(2026, 9, 16, tzinfo=timezone.utc),
    }
    first = recorder.record(context=first_context, **values)
    replay = recorder.record(context=replay_context, **values)
    assert replay is first
    assert len(sink.records) == 1
    assert first.org_id == "org-a"
    assert first.trace_id == "trace-one"
    assert set(first.as_contract()) == {
        "id", "org_id", "trace_id", "request_id", "service", "operation", "provider", "model",
        "input_units", "output_units", "cost_cents", "latency_ms", "status", "idempotency_key", "occurred_at",
    }
    with pytest.raises(CostIdempotencyConflictError):
        recorder.record(context=first_context, **{**values, "cost_cents": 3})
    assert len(sink.records) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_units", -1),
        ("output_units", -1),
        ("cost_cents", -1),
        ("latency_ms", -1),
        ("status", "unknown"),
        ("provider", ""),
        ("model", "password=secret"),
        ("idempotency_key", "short"),
    ],
)
def test_invalid_cost_facts_do_not_write_partial_records(field: str, value: object) -> None:
    from infra.foundation.costs import CostRecorder, CostValidationError, InMemoryCostSink
    from infra.foundation.observability import TenantContext

    sink = InMemoryCostSink()
    recorder = CostRecorder(sink)
    values = {
        "service": "model-gateway",
        "operation": "generate",
        "provider": "fake",
        "model": "fixture-model",
        "input_units": 1,
        "output_units": 1,
        "cost_cents": 1,
        "latency_ms": 1,
        "status": "succeeded",
        "idempotency_key": "cost-key-001",
    }
    values[field] = value
    with pytest.raises(CostValidationError):
        recorder.record(context=TenantContext("trace", "request", "org-a", "actor-a"), **values)
    assert sink.records == ()


def test_cost_record_safely_contains_sink_failures() -> None:
    from infra.foundation.costs import CostRecorder
    from infra.foundation.observability import TenantContext

    class FailingSink:
        def write(self, record) -> None:
            raise RuntimeError("sink unavailable")

    result = CostRecorder(FailingSink()).record_safely(
        service="api",
        operation="synthetic",
        provider="fake",
        model="fixture",
        input_units=0,
        output_units=0,
        cost_cents=0,
        latency_ms=0,
        status="succeeded",
        idempotency_key="cost-key-safe",
        context=TenantContext("trace", "request", "org-a", "actor-a"),
    )
    assert result is None
