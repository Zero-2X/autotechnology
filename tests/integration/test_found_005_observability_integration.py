from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse


def test_correlation_ids_are_generated_and_echoed_in_response_and_logs(caplog) -> None:
    from apps.api.main import create_app

    caplog.set_level(logging.INFO, logger="ai_workflow.api")
    client = TestClient(create_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == response.headers["X-Trace-Id"]
    assert body["request_id"] == response.headers["X-Request-Id"]
    records = [json.loads(record.getMessage()) for record in caplog.records if record.name == "ai_workflow.api"]
    assert records
    assert records[-1]["trace_id"] == body["trace_id"]
    assert records[-1]["request_id"] == body["request_id"]
    assert records[-1]["status_code"] == 200


def test_explicit_context_is_preserved_and_errors_use_unified_contract() -> None:
    from apps.api.main import create_app

    client = TestClient(create_app())
    headers = {
        "X-Trace-Id": "trace-explicit",
        "X-Request-Id": "request-explicit",
        "X-Org-Id": "org-explicit",
        "X-Actor-Id": "actor-explicit",
    }
    response = client.get("/health/live", headers=headers)
    assert response.status_code == 200
    assert response.json()["trace_id"] == "trace-explicit"
    assert response.json()["request_id"] == "request-explicit"
    assert response.headers["X-Org-Id"] == "org-explicit"
    rejected = client.post("/internal/outbox/dispatch", json={})
    assert rejected.status_code == 403
    detail = rejected.json()["detail"]
    assert detail["code"] == "WORKER_ONLY"
    assert {"trace_id", "request_id", "org_id", "actor_id", "retryable"} <= set(detail)


def test_invalid_context_is_rejected_without_echoing_unsafe_header() -> None:
    from apps.api.main import create_app

    client = TestClient(create_app())
    response = client.get("/health/live", headers={"X-Trace-Id": "unsafe\nvalue"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_CORRELATION_CONTEXT"
    assert "\n" not in response.text


def test_streaming_non_json_response_keeps_streaming_headers_and_body() -> None:
    from apps.api.main import create_app

    app = create_app()

    @app.get("/stream-audit")
    def stream_audit() -> StreamingResponse:
        return StreamingResponse(iter([b"first-", b"second"]), media_type="text/plain")

    response = TestClient(app).get("/stream-audit")
    assert response.status_code == 200
    assert response.content == b"first-second"
    assert "content-length" not in response.headers
    assert response.headers["X-Trace-Id"]
