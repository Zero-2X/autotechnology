from uuid import uuid4

import pytest

from modules.agent import AgentRunLedger, LedgerError


def test_ledger_persists_hashes_without_raw_prompt_and_is_tenant_scoped() -> None:
    ledger = AgentRunLedger()
    org_id = uuid4()
    record = ledger.record_agent_run(org_id=org_id, agent_definition_id=uuid4(), status="succeeded", input_payload={"prompt": "secret text"}, output_payload={"answer": "ok"})
    assert len(record.input_hash) == 64
    assert "secret text" not in repr(record)
    assert ledger.get_agent_run(org_id=org_id, run_id=record.id) == record
    with pytest.raises(LedgerError) as error:
        ledger.get_agent_run(org_id=uuid4(), run_id=record.id)
    assert error.value.code == "TENANT_SCOPE_VIOLATION"


def test_model_call_ledger_records_attempt_cost_latency_and_error() -> None:
    ledger = AgentRunLedger()
    call = ledger.record_model_call(org_id=uuid4(), model_config_id="cfg-1", prompt_version="p/v1", request_hash="a" * 64, input_payload={"x": 1}, cost_cents=2, latency_ms=5, status="failed", attempt_no=2, error_code="MODEL_TIMEOUT")
    assert (call.attempt_no, call.cost_cents, call.error_code) == (2, 2, "MODEL_TIMEOUT")
