from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from modules.model_gateway import ModelError, ModelGateway, ModelRequest, ModelResponse
from packages.prompt_registry import EvaluationError, EvaluationService


ORG = "11111111-1111-4111-8111-111111111111"
OTHER_ORG = "22222222-2222-4222-8222-222222222222"
ACTOR = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STAMP = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
INPUT_REF = "schema/eval-input/v1"
OUTPUT_REF = "schema/eval-output/v1"
SCHEMAS = {
    INPUT_REF: {
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {"query": {"type": "string", "minLength": 1}},
    },
    OUTPUT_REF: {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    },
}


class ScriptedProvider:
    provider = "fake"
    model_version = "scripted-v1"

    def __init__(self, *, invalid_output: bool = False, failing_case: str | None = None) -> None:
        self.invalid_output = invalid_output
        self.failing_case = failing_case
        self.call_count = 0

    def generate(self, request: ModelRequest) -> ModelResponse:
        case_id = request.input["case_id"]
        if case_id == self.failing_case:
            raise ModelError("PROVIDER_UNAVAILABLE", "synthetic failure")
        rendered = request.input["rendered_prompt"]
        cost = 2 if rendered.startswith("candidate") else 1
        if cost > request.budget_cents:
            raise ModelError("MODEL_BUDGET_EXCEEDED", "synthetic budget failure")
        self.call_count += 1
        query = request.input["case_input"]["query"]
        output = {"answer": 7 if self.invalid_output else ("wrong" if rendered.startswith("candidate") else query)}
        return ModelResponse(
            output=output,
            provider="fake",
            model_version=self.model_version,
            usage={"input_tokens": 4, "output_tokens": 2},
            cost_cents=cost,
            latency_ms=3,
            finish_reason="stop",
            request_hash=request.request_hash,
        )


def new_service(provider: ScriptedProvider | None = None) -> tuple[EvaluationService, ScriptedProvider, str]:
    selected = provider or ScriptedProvider()
    gateway = ModelGateway({"fake": selected})
    config = gateway.register_config(
        org_id=ORG,
        provider="fake",
        model="eval-fake",
        data_region="local",
        retention_policy="synthetic-only",
    )
    service = EvaluationService(
        model_gateway=gateway,
        schema_registry=SCHEMAS,
        clock=lambda: STAMP,
    )
    return service, selected, config.id


def register_prompt(
    service: EvaluationService,
    *,
    version_no: int = 1,
    expected_previous_version: int = 0,
    template: str = "baseline {query}",
    idempotency_key: str | None = None,
) -> dict:
    return service.register_prompt(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-eval",
        idempotency_key=idempotency_key or f"prompt-key-v{version_no}",
        prompt_key="answer.prompt",
        version_no=version_no,
        expected_previous_version=expected_previous_version,
        template=template,
        variables=["query"],
        input_schema_ref=INPUT_REF,
        output_schema_ref=OUTPUT_REF,
    )


def register_golden(service: EvaluationService, *, case_count: int = 2) -> dict:
    return service.register_golden_set(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-eval",
        idempotency_key="golden-key-v1",
        dataset_key="answer.golden",
        version_no=1,
        expected_previous_version=0,
        input_schema_ref=INPUT_REF,
        output_schema_ref=OUTPUT_REF,
        cases=[
            {
                "case_id": f"case.{index}",
                "input": {"query": f"synthetic-{index}"},
                "expected_output": {"answer": f"synthetic-{index}"},
                "tags": ["synthetic"],
            }
            for index in range(1, case_count + 1)
        ],
    )


def register_thresholds(
    service: EvaluationService,
    *,
    min_exact_match_ratio: float = 1.0,
    max_error_ratio: float = 0.0,
    max_total_cost_cents: int = 10,
    max_cost_per_case_cents: int = 2,
    max_quality_drop: float = 0.0,
    max_cost_increase_ratio: float = 0.1,
) -> dict:
    return service.register_thresholds(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-eval",
        idempotency_key="threshold-key-v1",
        threshold_key="answer.threshold",
        version_no=1,
        expected_previous_version=0,
        min_exact_match_ratio=min_exact_match_ratio,
        max_error_ratio=max_error_ratio,
        max_total_cost_cents=max_total_cost_cents,
        max_cost_per_case_cents=max_cost_per_case_cents,
        max_quality_drop=max_quality_drop,
        max_cost_increase_ratio=max_cost_increase_ratio,
    )


def run(
    service: EvaluationService,
    *,
    prompt: dict,
    golden: dict,
    thresholds: dict,
    config_id: str,
    key: str,
    baseline_run_id: str | None = None,
    per_case_budget_cents: int = 2,
) -> dict:
    return service.run_offline(
        org_id=ORG,
        actor_id=ACTOR,
        trace_id="trace-eval",
        idempotency_key=key,
        prompt_version_id=prompt["id"],
        dataset_version_id=golden["id"],
        threshold_version_id=thresholds["id"],
        model_config_id=config_id,
        baseline_run_id=baseline_run_id,
        timeout_ms=100,
        per_case_budget_cents=per_case_budget_cents,
    )


def test_prompt_versions_are_immutable_monotonic_and_idempotent() -> None:
    service, _, _ = new_service()
    first = register_prompt(service)
    replay = register_prompt(service)
    assert replay == first
    first["template"] = "tampered"
    assert service.get_prompt(org_id=ORG, prompt_version_id=first["id"])["template"] == "baseline {query}"

    with pytest.raises(EvaluationError) as stale:
        register_prompt(service, version_no=3, expected_previous_version=1, idempotency_key="prompt-key-v3")
    assert stale.value.code == "VERSION_CONFLICT"
    second = register_prompt(
        service,
        version_no=2,
        expected_previous_version=1,
        template="candidate {query}",
        idempotency_key="prompt-key-v2",
    )
    assert second["version_ref"] == "answer.prompt/v2"
    with pytest.raises(EvaluationError) as mismatch:
        service.register_prompt(
            org_id=ORG,
            actor_id=ACTOR,
            trace_id="trace-eval",
            idempotency_key="prompt-bad-vars",
            prompt_key="other.prompt",
            version_no=1,
            expected_previous_version=0,
            template="answer {missing}",
            variables=["query"],
            input_schema_ref=INPUT_REF,
            output_schema_ref=OUTPUT_REF,
        )
    assert mismatch.value.code == "PROMPT_VARIABLE_MISMATCH"


def test_golden_set_and_thresholds_fail_closed_on_invalid_contracts() -> None:
    service, _, _ = new_service()
    with pytest.raises(EvaluationError) as invalid_case:
        service.register_golden_set(
            org_id=ORG,
            actor_id=ACTOR,
            trace_id="trace-eval",
            idempotency_key="golden-invalid",
            dataset_key="answer.invalid",
            version_no=1,
            expected_previous_version=0,
            input_schema_ref=INPUT_REF,
            output_schema_ref=OUTPUT_REF,
            cases=[{"case_id": "case.bad", "input": {"query": "x"}, "expected_output": {"answer": 7}}],
        )
    assert invalid_case.value.code == "GOLDEN_OUTPUT_SCHEMA_INVALID"
    with pytest.raises(EvaluationError) as unknown_field:
        service.register_golden_set(
            org_id=ORG,
            actor_id=ACTOR,
            trace_id="trace-eval",
            idempotency_key="golden-extra-field",
            dataset_key="answer.extra",
            version_no=1,
            expected_previous_version=0,
            input_schema_ref=INPUT_REF,
            output_schema_ref=OUTPUT_REF,
            cases=[{
                "case_id": "case.extra",
                "input": {"query": "x"},
                "expected_output": {"answer": "x"},
                "source": "unapproved",
            }],
        )
    assert unknown_field.value.code == "INVALID_GOLDEN_SET"
    with pytest.raises(EvaluationError) as budget:
        service.register_thresholds(
            org_id=ORG,
            actor_id=ACTOR,
            trace_id="trace-eval",
            idempotency_key="threshold-over-budget",
            threshold_key="answer.over-budget",
            version_no=1,
            expected_previous_version=0,
            min_exact_match_ratio=1,
            max_error_ratio=0,
            max_total_cost_cents=201,
            max_cost_per_case_cents=1,
            max_quality_drop=0,
            max_cost_increase_ratio=0,
        )
    assert budget.value.code == "EVAL_BUDGET_EXCEEDS_GOVERNANCE"


def test_offline_run_records_hashes_costs_and_replays_without_model_calls() -> None:
    service, provider, config_id = new_service()
    prompt = register_prompt(service)
    golden = register_golden(service)
    thresholds = register_thresholds(service)
    result = run(
        service,
        prompt=prompt,
        golden=golden,
        thresholds=thresholds,
        config_id=config_id,
        key="offline-run-1",
    )
    assert result["gate_status"] == "passed"
    assert result["metrics"] == {
        "exact_match_ratio": 1.0,
        "error_ratio": 0.0,
        "total_cost_cents": 2,
        "average_cost_cents": 1.0,
        "max_case_cost_cents": 1,
        "quality_delta": None,
        "cost_increase_ratio": None,
    }
    assert provider.call_count == 2
    assert run(
        service,
        prompt=prompt,
        golden=golden,
        thresholds=thresholds,
        config_id=config_id,
        key="offline-run-1",
    ) == result
    assert provider.call_count == 2
    serialized = json.dumps(result, sort_keys=True)
    assert "synthetic-1" not in serialized
    assert "synthetic-1" not in json.dumps(service.audit_for(org_id=ORG), sort_keys=True)

    with pytest.raises(EvaluationError) as conflict:
        run(
            service,
            prompt=prompt,
            golden=golden,
            thresholds=thresholds,
            config_id=config_id,
            key="offline-run-1",
            per_case_budget_cents=1,
        )
    assert conflict.value.code == "IDEMPOTENCY_KEY_REUSED"
    with pytest.raises(EvaluationError) as foreign:
        service.get_run(org_id=OTHER_ORG, run_id=result["id"])
    assert foreign.value.code == "TENANT_SCOPE_VIOLATION"


def test_baseline_comparison_flags_quality_and_cost_regressions() -> None:
    service, _, config_id = new_service()
    baseline_prompt = register_prompt(service)
    candidate_prompt = register_prompt(
        service,
        version_no=2,
        expected_previous_version=1,
        template="candidate {query}",
        idempotency_key="prompt-key-v2",
    )
    golden = register_golden(service)
    thresholds = register_thresholds(service, min_exact_match_ratio=0)
    baseline = run(
        service,
        prompt=baseline_prompt,
        golden=golden,
        thresholds=thresholds,
        config_id=config_id,
        key="baseline-run",
    )
    candidate = run(
        service,
        prompt=candidate_prompt,
        golden=golden,
        thresholds=thresholds,
        config_id=config_id,
        key="candidate-run",
        baseline_run_id=baseline["id"],
    )
    assert baseline["gate_status"] == "passed"
    assert candidate["gate_status"] == "failed"
    assert candidate["metrics"]["quality_delta"] == -1.0
    assert candidate["metrics"]["cost_increase_ratio"] == 1.0
    assert candidate["regression_reasons"] == ["COST_REGRESSION_EXCEEDED", "QUALITY_REGRESSION_EXCEEDED"]


def test_model_output_schema_failure_preserves_incurred_cost_without_raw_output() -> None:
    service, _, config_id = new_service(ScriptedProvider(invalid_output=True))
    prompt = register_prompt(service)
    golden = register_golden(service, case_count=1)
    thresholds = register_thresholds(service)
    result = run(
        service,
        prompt=prompt,
        golden=golden,
        thresholds=thresholds,
        config_id=config_id,
        key="invalid-output-run",
    )
    assert result["gate_status"] == "failed"
    assert result["error_cases"] == 1
    assert result["metrics"]["total_cost_cents"] == 1
    assert result["results"][0]["error_code"] == "MODEL_OUTPUT_SCHEMA_INVALID"
    assert result["results"][0]["output_hash"] is not None
    assert "\"answer\": 7" not in json.dumps(result)


def test_run_stops_new_calls_when_absolute_cost_limit_is_reached() -> None:
    service, provider, config_id = new_service()
    prompt = register_prompt(service)
    golden = register_golden(service)
    thresholds = register_thresholds(
        service,
        max_total_cost_cents=1,
        max_cost_per_case_cents=1,
    )
    result = run(
        service,
        prompt=prompt,
        golden=golden,
        thresholds=thresholds,
        config_id=config_id,
        key="cost-stop-run",
        per_case_budget_cents=1,
    )
    assert provider.call_count == 1
    assert result["metrics"]["total_cost_cents"] == 1
    assert result["results"][1]["error_code"] == "EVAL_COST_LIMIT_REACHED"
    assert result["gate_status"] == "failed"
