from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"
BASELINE = ROOT / "docs/foundation/openapi-compatibility-baseline-v1.yaml"
ERROR_CATALOG = ROOT / "docs/foundation/error-code-catalog-v1.yaml"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_runtime_openapi_is_a_declared_subset_and_health_contract_is_live() -> None:
    from apps.api.main import create_app

    declared = load_yaml(OPENAPI)
    baseline = load_yaml(BASELINE)
    runtime = TestClient(create_app())
    runtime_paths = runtime.app.openapi()["paths"]
    assert set(runtime_paths) <= set(declared["paths"])
    assert {"/health/live", "/health/ready", "/metrics"} <= set(runtime_paths)
    assert set(baseline["operations"]) >= {
        "GET /health/live",
        "GET /health/ready",
        "GET /metrics",
    }

    live = runtime.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    ready = runtime.get("/health/ready")
    assert ready.status_code == 200
    assert "dependencies" in ready.json()
    metrics = runtime.get("/metrics")
    assert metrics.status_code == 200
    assert "# TYPE" in metrics.text


def test_error_envelope_and_worker_gate_use_catalog_codes() -> None:
    from apps.api.main import create_app

    catalog = load_yaml(ERROR_CATALOG)["codes"]
    client = TestClient(create_app())
    response = client.post("/internal/outbox/dispatch", json={})
    assert response.status_code == catalog["WORKER_ONLY"]["http_status"]
    assert response.json()["detail"]["code"] == "WORKER_ONLY"

    response = client.post("/internal/outbox/dispatch", headers={"X-Worker-Id": "worker-1"}, json={})
    assert response.status_code == catalog["OUTBOX_NOT_CONFIGURED"]["http_status"]
    assert response.json()["detail"]["code"] == "OUTBOX_NOT_CONFIGURED"
