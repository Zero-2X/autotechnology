from __future__ import annotations

import copy
from pathlib import Path

import yaml

from scripts.check_openapi_compatibility import check_compatibility


ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "packages/contracts/openapi/openapi.yaml"
BASELINE = ROOT / "docs/foundation/openapi-compatibility-baseline-v1.yaml"
ERROR_CATALOG = ROOT / "docs/foundation/error-code-catalog-v1.yaml"


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def current_and_baseline() -> tuple[dict, dict]:
    return load_yaml(OPENAPI), load_yaml(BASELINE)


def test_current_openapi_matches_foundation_baseline() -> None:
    document, baseline = current_and_baseline()
    errors, warnings = check_compatibility(document, baseline)
    assert errors == []
    assert warnings == []


def test_removed_operation_response_and_operation_id_are_breaking() -> None:
    document, baseline = current_and_baseline()

    removed_operation = copy.deepcopy(document)
    del removed_operation["paths"]["/health/live"]
    errors, _ = check_compatibility(removed_operation, baseline)
    assert any("removed baseline operation: GET /health/live" in item for item in errors)

    removed_response = copy.deepcopy(document)
    del removed_response["paths"]["/health/live"]["get"]["responses"]["200"]
    errors, _ = check_compatibility(removed_response, baseline)
    assert any("response code 200 was removed" in item for item in errors)

    changed_operation_id = copy.deepcopy(document)
    changed_operation_id["paths"]["/health/live"]["get"]["operationId"] = "liveHealthRenamed"
    errors, _ = check_compatibility(changed_operation_id, baseline)
    assert any("operationId changed" in item for item in errors)


def test_worker_and_idempotency_guards_are_enforced() -> None:
    document, baseline = current_and_baseline()

    worker_removed = copy.deepcopy(document)
    worker_removed["paths"]["/internal/outbox/dispatch"]["post"]["parameters"] = []
    errors, _ = check_compatibility(worker_removed, baseline)
    assert any("requires required X-Worker-Id header" in item for item in errors)

    idem_removed = copy.deepcopy(document)
    idem_removed["paths"]["/v1/sources"]["post"]["parameters"] = []
    errors, _ = check_compatibility(idem_removed, baseline)
    assert any("write operation requires Idempotency-Key" in item for item in errors)

    idem_narrowed = copy.deepcopy(document)
    idem_narrowed["components"]["parameters"]["IdempotencyKey"]["schema"]["minLength"] = 16
    errors, _ = check_compatibility(idem_narrowed, baseline)
    assert any("Idempotency-Key must retain minLength=8" in item for item in errors)


def test_local_ref_and_required_parameter_breaks_are_detected() -> None:
    document, baseline = current_and_baseline()

    broken_ref = copy.deepcopy(document)
    broken_ref["paths"]["/v1/sources"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"] = "../jsonschema/missing.schema.json"
    errors, _ = check_compatibility(broken_ref, baseline)
    assert any("broken local $ref" in item for item in errors)

    removed_required = copy.deepcopy(document)
    removed_required["paths"]["/v1/sources"]["post"]["parameters"] = []
    errors, _ = check_compatibility(removed_required, baseline)
    assert any("required parameter Idempotency-Key" in item for item in errors)


def test_error_catalog_contains_foundation_codes_and_consistent_metadata() -> None:
    catalog = load_yaml(ERROR_CATALOG)
    codes = catalog["codes"]
    required = {
        "INVALID_CORRELATION_CONTEXT",
        "REQUEST_VALIDATION_ERROR",
        "INTERNAL_ERROR",
        "WORKER_ONLY",
        "OUTBOX_NOT_CONFIGURED",
        "TASK_FAILURE_NOT_CONFIGURED",
        "INVALID_TASK_FAILURE",
        "JOB_NOT_FOUND",
        "JOB_NOT_CLAIMABLE",
        "RETRY_NOT_ALLOWED",
        "REPLAY_NOT_ALLOWED",
        "TENANT_SCOPE_VIOLATION",
        "IDEMPOTENCY_KEY_REUSED",
    }
    assert required <= set(codes)
    for code, metadata in codes.items():
        assert 400 <= metadata["http_status"] <= 599, code
        assert isinstance(metadata["retryable"], bool), code
        assert metadata["category"], code
        assert metadata["owner"], code
