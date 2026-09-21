from datetime import datetime, timezone

from modules.model_gateway import FakeModelProvider, ModelGateway, ModelRequest
from packages.prompt_registry import EvaluationService


ORG = "33333333-3333-4333-8333-333333333333"
ACTOR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
INPUT_REF = "schema/eval-input/v1"
OUTPUT_REF = "schema/eval-output/v1"
INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {"query": {"type": "string"}},
}
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fixture"],
    "properties": {"fixture": {"type": "string"}},
}


def test_eval_001_runs_through_fake_model_gateway_without_network() -> None:
    provider = FakeModelProvider(schema_registry={OUTPUT_REF: OUTPUT_SCHEMA})
    gateway = ModelGateway({"fake": provider})
    config = gateway.register_config(
        org_id=ORG,
        provider="fake",
        model="fake-eval-model",
        data_region="local",
        retention_policy="synthetic-only",
    )
    service = EvaluationService(
        model_gateway=gateway,
        schema_registry={INPUT_REF: INPUT_SCHEMA, OUTPUT_REF: OUTPUT_SCHEMA},
        clock=lambda: datetime(2026, 9, 19, 13, 0, tzinfo=timezone.utc),
    )
    prompt = service.register_prompt(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-integration",
        idempotency_key="integration-prompt",
        prompt_key="fixture.prompt",
        version_no=1,
        expected_previous_version=0,
        template="answer {query}",
        variables=["query"],
        input_schema_ref=INPUT_REF,
        output_schema_ref=OUTPUT_REF,
    )
    probe = ModelRequest(
        model_id=config.model,
        prompt_version=prompt["version_ref"],
        input={
            "case_id": "case.one",
            "rendered_prompt": "answer synthetic",
            "case_input": {"query": "synthetic"},
        },
        response_schema_ref=OUTPUT_REF,
        timeout_ms=100,
        budget_cents=1,
        trace_id="trace-integration",
        org_id=ORG,
    )
    golden = service.register_golden_set(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-integration",
        idempotency_key="integration-golden",
        dataset_key="fixture.golden",
        version_no=1,
        expected_previous_version=0,
        input_schema_ref=INPUT_REF,
        output_schema_ref=OUTPUT_REF,
        cases=[{
            "case_id": "case.one",
            "input": {"query": "synthetic"},
            "expected_output": {"fixture": probe.request_hash[:16]},
            "tags": ["integration"],
        }],
    )
    thresholds = service.register_thresholds(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-integration",
        idempotency_key="integration-threshold",
        threshold_key="fixture.threshold",
        version_no=1,
        expected_previous_version=0,
        min_exact_match_ratio=1,
        max_error_ratio=0,
        max_total_cost_cents=1,
        max_cost_per_case_cents=1,
        max_quality_drop=0,
        max_cost_increase_ratio=0,
    )
    result = service.run_offline(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-integration",
        idempotency_key="integration-run",
        prompt_version_id=prompt["id"],
        dataset_version_id=golden["id"],
        threshold_version_id=thresholds["id"],
        model_config_id=config.id,
        timeout_ms=100,
        per_case_budget_cents=1,
    )

    assert result["gate_status"] == "passed"
    assert result["model_versions"] == ["fake-v1"]
    assert provider.call_count == 1
    assert [event["type"] for event in gateway.events] == ["model.call.started", "model.call.succeeded"]
