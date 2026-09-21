from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_found_005_contract_files_are_registered() -> None:
    foundation = json.loads((ROOT / "packages/contracts/jsonschema/foundation.schema.json").read_text(encoding="utf-8"))
    refs = {item["$ref"] for item in foundation["oneOf"]}
    assert {"./api-error.schema.json", "./correlation-context.schema.json", "./structured-log.schema.json"} <= refs
    for name in ("api-error", "correlation-context", "structured-log"):
        schema = json.loads((ROOT / f"packages/contracts/jsonschema/{name}.schema.json").read_text(encoding="utf-8"))
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["additionalProperties"] is False or name == "structured-log"
    task = (ROOT / "docs/tasks/FOUND-005.md").read_text(encoding="utf-8")
    assert "状态：`done`" in task
    assert "INVALID_CORRELATION_CONTEXT" in task
    assert "INTERNAL_ERROR" in task


def test_api_error_and_structured_log_redact_secret_values() -> None:
    from infra.foundation.observability import ApiError, TenantContext, structured_log_json

    context = TenantContext("trace-1", "request-1", "org-1", "actor-1")
    error = ApiError(
        "BAD_INPUT",
        "safe message",
        details={"authorization": "Bearer abc", "nested": {"token": "secret-value"}},
    )
    value = error.as_dict(context)
    assert value["trace_id"] == "trace-1"
    assert value["details"]["authorization"] == "[REDACTED]"
    assert value["details"]["nested"]["token"] == "[REDACTED]"
    encoded = structured_log_json(
        "test.event", context=context, fields={"password": "not-written", "safe": "ok"}
    )
    record = json.loads(encoded)
    assert record["password"] == "[REDACTED]"
    assert record["safe"] == "ok"
    assert record["request_id"] == "request-1"


def test_found_005_migration_is_reversible_noop() -> None:
    source = (ROOT / "packages/db/migrations/versions/20260916_found_004f_api_observability.py").read_text(encoding="utf-8")
    assert 'revision = "20260916_found_004f"' in source
    assert 'down_revision = "20260916_found_004e"' in source
    assert "def upgrade()" in source and "def downgrade()" in source
