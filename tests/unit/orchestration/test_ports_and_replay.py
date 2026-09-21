from uuid import uuid4

import pytest

from orchestration.distribution import draft_only_distribution
from orchestration.errors import GraphError
from orchestration.evaluation import GoldenCase, GoldenSet, GraphEvaluator
from orchestration.observability import record_model_call
from orchestration.replay import ReplayGuard
from packages.observability import TraceLedger


def test_replay_guard_never_repeats_provider_side_effect():
    guard = ReplayGuard(); calls = []
    intent = guard.create_intent(org_id="org", intent_key="intent-1", target_version_ref="target://1", policy_ref="policy://1")
    result = guard.provider_call(org_id="org", provider_key="fake", intent_key=intent.intent_key, payload_hash="a" * 64,
                                 call=lambda: calls.append("called") or {"external_id": "object-1"})
    again = guard.provider_call(org_id="org", provider_key="fake", intent_key=intent.intent_key, payload_hash="a" * 64,
                                call=lambda: calls.append("called-again") or {"external_id": "object-2"})
    assert result == again and calls == ["called"]
    assert guard.replay(org_id="org", intent_key="intent-1")["provider_calls"] == 1
    with pytest.raises(GraphError): guard.provider_call(org_id="org", provider_key="fake", intent_key="intent-1", payload_hash="b" * 64, call=lambda: {})


def test_distribution_gate_and_trace_redaction():
    with pytest.raises(GraphError) as error:
        draft_only_distribution(port=lambda **kwargs: {"x": "ref://x"}, state={}, context={})
    assert error.value.code == "EXT_ACCOUNT_UNAVAILABLE"
    ledger = TraceLedger()
    record_model_call(ledger, phase="succeeded", org_id="org", actor_id="actor", trace_id="trace", run_id="run", provider="fake", input_tokens=1, output_tokens=2, amount_minor=3)
    event = ledger.emit("test", org_id="org", trace_id="trace", payload={"token": "secret", "ref": "private://x"})
    assert event["payload"]["token"] == "<redacted>"
    assert len(ledger.costs) == 1


def test_golden_evaluator_is_deterministic():
    golden = GoldenSet((GoldenCase("case-1", {"input": "ref://1"}, {"answer": "ref://a"}),))
    result = GraphEvaluator().evaluate(golden, lambda refs: {"result_refs": {"answer": refs["input"].replace("1", "a")}})
    assert result["passed"] == 1 and result["failed"] == 0
