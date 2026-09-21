"""Tenant-scoped prompt, golden-set, and offline evaluation registry."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from string import Formatter
from typing import Any, Callable, Mapping, Sequence
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from modules.model_gateway import ModelError, ModelGateway, ModelRequest


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages" / "contracts" / "jsonschema"
KEY = re.compile(r"^[a-z][a-z0-9_.-]{2,127}$")
VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EvaluationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise EvaluationError("INVALID_JSON_VALUE", "evaluation metadata must be JSON serializable") from exc


def _hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _uuid(value: UUID | str, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise EvaluationError("INVALID_EVALUATION_CONTEXT", f"{field} must be a UUID") from exc


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError("INVALID_EVALUATION_CONTEXT", f"{field} is required")
    return value.strip()


def _version(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise EvaluationError("INVALID_VERSION", "version_no must be a positive integer")
    return value


def _ratio(value: object, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError("INVALID_THRESHOLD", f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > 1:
        raise EvaluationError("INVALID_THRESHOLD", f"{field} must be between {minimum} and 1")
    return result


def _cents(value: object, field: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvaluationError("INVALID_THRESHOLD", f"{field} must be an integer >= {minimum}")
    return value


class EvaluationService:
    """In-memory application boundary for reproducible, account-free evaluation."""

    def __init__(
        self,
        *,
        model_gateway: ModelGateway,
        schema_registry: Mapping[str, Mapping[str, Any]],
        workflow_cost_cap_cents: int = 200,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.model_gateway = model_gateway
        self.schema_registry = {key: deepcopy(dict(value)) for key, value in schema_registry.items()}
        self.workflow_cost_cap_cents = _cents(workflow_cost_cap_cents, "workflow_cost_cap_cents", positive=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.prompts: dict[str, dict[str, Any]] = {}
        self.golden_sets: dict[str, dict[str, Any]] = {}
        self.thresholds: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self._latest: dict[tuple[str, str, str], int] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str, str]] = {}
        self.audit: list[dict[str, Any]] = []
        self._contracts = {
            name: json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
            for name in (
                "prompt-version.schema.json",
                "golden-set-version.schema.json",
                "regression-threshold-version.schema.json",
                "eval-run.schema.json",
            )
        }

    def register_prompt(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        prompt_key: str,
        version_no: int,
        expected_previous_version: int,
        template: str,
        variables: Sequence[str],
        input_schema_ref: str,
        output_schema_ref: str,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        name = self._key(prompt_key, "prompt_key")
        number = _version(version_no)
        previous = _cents(expected_previous_version, "expected_previous_version")
        text = _nonempty(template, "template")
        declared = self._variables(variables)
        actual = self._template_variables(text)
        if set(declared) != set(actual):
            raise EvaluationError("PROMPT_VARIABLE_MISMATCH", "declared variables must match template placeholders")
        input_ref = self._schema_ref(input_schema_ref)
        output_ref = self._schema_ref(output_schema_ref)
        body = {
            "command": "register_prompt",
            "prompt_key": name,
            "version_no": number,
            "expected_previous_version": previous,
            "template": text,
            "variables": declared,
            "input_schema_ref": input_ref,
            "output_schema_ref": output_ref,
        }
        replay = self._replay(tenant, key, _hash(body), "prompt", self.prompts)
        if replay is not None:
            return replay
        self._assert_next(tenant, "prompt", name, number, previous)
        created_at = self._now()
        result = {
            "id": str(uuid4()),
            "org_id": tenant,
            "prompt_key": name,
            "version_no": number,
            "version_ref": f"{name}/v{number}",
            "template": text,
            "variables": declared,
            "input_schema_ref": input_ref,
            "output_schema_ref": output_ref,
            "content_hash": _hash(body | {"expected_previous_version": None}),
            "status": "registered",
            "created_by": actor,
            "created_at": created_at,
        }
        self._validate_contract("prompt-version.schema.json", result)
        return self._store_version("prompt", tenant, name, number, key, _hash(body), result, trace)

    def register_golden_set(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        dataset_key: str,
        version_no: int,
        expected_previous_version: int,
        input_schema_ref: str,
        output_schema_ref: str,
        cases: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        name = self._key(dataset_key, "dataset_key")
        number = _version(version_no)
        previous = _cents(expected_previous_version, "expected_previous_version")
        input_ref = self._schema_ref(input_schema_ref)
        output_ref = self._schema_ref(output_schema_ref)
        normalized = self._cases(cases, input_ref, output_ref)
        body = {
            "command": "register_golden_set",
            "dataset_key": name,
            "version_no": number,
            "expected_previous_version": previous,
            "input_schema_ref": input_ref,
            "output_schema_ref": output_ref,
            "cases": normalized,
            "data_classification": "synthetic",
        }
        replay = self._replay(tenant, key, _hash(body), "golden_set", self.golden_sets)
        if replay is not None:
            return replay
        self._assert_next(tenant, "golden_set", name, number, previous)
        result = {
            "id": str(uuid4()),
            "org_id": tenant,
            "dataset_key": name,
            "version_no": number,
            "dataset_hash": _hash(normalized),
            "input_schema_ref": input_ref,
            "output_schema_ref": output_ref,
            "data_classification": "synthetic",
            "cases": normalized,
            "created_by": actor,
            "created_at": self._now(),
        }
        self._validate_contract("golden-set-version.schema.json", result)
        return self._store_version("golden_set", tenant, name, number, key, _hash(body), result, trace)

    def register_thresholds(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        threshold_key: str,
        version_no: int,
        expected_previous_version: int,
        min_exact_match_ratio: float,
        max_error_ratio: float,
        max_total_cost_cents: int,
        max_cost_per_case_cents: int,
        max_quality_drop: float,
        max_cost_increase_ratio: float,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        name = self._key(threshold_key, "threshold_key")
        number = _version(version_no)
        previous = _cents(expected_previous_version, "expected_previous_version")
        total = _cents(max_total_cost_cents, "max_total_cost_cents", positive=True)
        per_case = _cents(max_cost_per_case_cents, "max_cost_per_case_cents", positive=True)
        if total > self.workflow_cost_cap_cents or per_case > total:
            raise EvaluationError("EVAL_BUDGET_EXCEEDS_GOVERNANCE", "evaluation thresholds exceed the workflow cost cap")
        body = {
            "command": "register_thresholds",
            "threshold_key": name,
            "version_no": number,
            "expected_previous_version": previous,
            "min_exact_match_ratio": _ratio(min_exact_match_ratio, "min_exact_match_ratio"),
            "max_error_ratio": _ratio(max_error_ratio, "max_error_ratio"),
            "max_total_cost_cents": total,
            "max_cost_per_case_cents": per_case,
            "max_quality_drop": _ratio(max_quality_drop, "max_quality_drop"),
            "max_cost_increase_ratio": _ratio(max_cost_increase_ratio, "max_cost_increase_ratio"),
            "governance_workflow_cap_cents": self.workflow_cost_cap_cents,
        }
        replay = self._replay(tenant, key, _hash(body), "threshold", self.thresholds)
        if replay is not None:
            return replay
        self._assert_next(tenant, "threshold", name, number, previous)
        result = {
            "id": str(uuid4()),
            "org_id": tenant,
            **{key: value for key, value in body.items() if key not in {"command", "expected_previous_version"}},
            "content_hash": _hash(body | {"expected_previous_version": None}),
            "created_by": actor,
            "created_at": self._now(),
        }
        self._validate_contract("regression-threshold-version.schema.json", result)
        return self._store_version("threshold", tenant, name, number, key, _hash(body), result, trace)

    def run_offline(
        self,
        *,
        org_id: UUID | str,
        actor_id: UUID | str,
        trace_id: str,
        idempotency_key: str,
        prompt_version_id: str,
        dataset_version_id: str,
        threshold_version_id: str,
        model_config_id: str,
        baseline_run_id: str | None = None,
        timeout_ms: int = 1000,
        per_case_budget_cents: int = 1,
    ) -> dict[str, Any]:
        tenant, actor, trace, key = self._context(org_id, actor_id, trace_id, idempotency_key)
        prompt = self._owned(self.prompts, tenant, prompt_version_id, "prompt version")
        dataset = self._owned(self.golden_sets, tenant, dataset_version_id, "golden set")
        threshold = self._owned(self.thresholds, tenant, threshold_version_id, "threshold version")
        if prompt["input_schema_ref"] != dataset["input_schema_ref"] or prompt["output_schema_ref"] != dataset["output_schema_ref"]:
            raise EvaluationError("EVAL_SCHEMA_MISMATCH", "prompt and golden set schema references must match")
        baseline = None
        if baseline_run_id is not None:
            baseline = self._owned(self.runs, tenant, baseline_run_id, "baseline run")
            if baseline["dataset_hash"] != dataset["dataset_hash"]:
                raise EvaluationError("EVAL_BASELINE_DATASET_MISMATCH", "baseline must use the same golden set content")
        if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
            raise EvaluationError("INVALID_EVAL_RUN", "timeout_ms must be a positive integer")
        case_budget = _cents(per_case_budget_cents, "per_case_budget_cents", positive=True)
        if case_budget > threshold["max_cost_per_case_cents"]:
            raise EvaluationError("EVAL_BUDGET_EXCEEDS_THRESHOLD", "per-case budget exceeds the approved threshold")
        body = {
            "command": "run_offline",
            "prompt_version_id": prompt["id"],
            "dataset_version_id": dataset["id"],
            "threshold_version_id": threshold["id"],
            "model_config_id": _nonempty(model_config_id, "model_config_id"),
            "baseline_run_id": None if baseline is None else baseline["id"],
            "timeout_ms": timeout_ms,
            "per_case_budget_cents": case_budget,
        }
        request_hash = _hash(body)
        replay = self._replay(tenant, key, request_hash, "run", self.runs)
        if replay is not None:
            return replay
        config = self.model_gateway.configs.get(body["model_config_id"])
        if config is None or config.org_id != tenant:
            raise EvaluationError("TENANT_SCOPE_VIOLATION", "model config does not belong to organization")
        started_at = self._now()
        results: list[dict[str, Any]] = []
        total_cost = 0
        model_versions: set[str] = set()
        for case in dataset["cases"]:
            remaining = threshold["max_total_cost_cents"] - total_cost
            if remaining <= 0:
                results.append(self._error_result(case, "EVAL_COST_LIMIT_REACHED"))
                continue
            request = ModelRequest(
                model_id=config.model,
                prompt_version=prompt["version_ref"],
                input={
                    "case_id": case["case_id"],
                    "rendered_prompt": self._render(prompt, case["input"]),
                    "case_input": deepcopy(case["input"]),
                },
                response_schema_ref=prompt["output_schema_ref"],
                timeout_ms=timeout_ms,
                budget_cents=min(case_budget, remaining),
                trace_id=trace,
                org_id=tenant,
            )
            try:
                call = self.model_gateway.call(
                    org_id=tenant,
                    config_id=config.id,
                    request=request,
                    idempotency_key=f"eval/{key}/{case['case_id']}",
                )
            except ModelError as exc:
                results.append(self._error_result(case, exc.code))
                continue
            cost = int(call.cost_cents or 0)
            total_cost += cost
            if call.model_version:
                model_versions.add(call.model_version)
            try:
                self._validate_schema(prompt["output_schema_ref"], call.output, "MODEL_OUTPUT_SCHEMA_INVALID")
            except EvaluationError as exc:
                results.append({
                    **self._error_result(case, exc.code),
                    "output_hash": call.output_hash,
                    "model_call_id": call.id,
                    "model_version": call.model_version,
                    "cost_cents": cost,
                    "latency_ms": call.latency_ms,
                })
                continue
            exact = _canonical(call.output) == _canonical(case["expected_output"])
            results.append({
                "case_id": case["case_id"],
                "status": "passed" if exact else "failed",
                "exact_match": exact,
                "expected_output_hash": _hash(case["expected_output"]),
                "output_hash": call.output_hash,
                "model_call_id": call.id,
                "model_version": call.model_version,
                "cost_cents": cost,
                "latency_ms": call.latency_ms,
                "error_code": None,
            })
        run = self._build_run(
            tenant=tenant,
            actor=actor,
            trace=trace,
            request_hash=request_hash,
            prompt=prompt,
            dataset=dataset,
            threshold=threshold,
            config_id=config.id,
            configured_model=config.model,
            baseline=baseline,
            results=results,
            total_cost=total_cost,
            model_versions=sorted(model_versions),
            started_at=started_at,
        )
        self._validate_contract("eval-run.schema.json", run)
        self.runs[run["id"]] = deepcopy(run)
        self._idempotency[(tenant, key)] = (request_hash, "run", run["id"])
        self.audit.append({
            "event_type": "evaluation.eval_run.completed",
            "org_id": tenant,
            "actor_id": actor,
            "trace_id": trace,
            "subject_id": run["id"],
            "request_hash": request_hash,
            "prompt_hash": prompt["content_hash"],
            "dataset_hash": dataset["dataset_hash"],
            "threshold_hash": threshold["content_hash"],
            "gate_status": run["gate_status"],
            "total_cost_cents": total_cost,
        })
        return deepcopy(run)

    def get_prompt(self, *, org_id: UUID | str, prompt_version_id: str) -> dict[str, Any]:
        return self._owned(self.prompts, _uuid(org_id, "org_id"), prompt_version_id, "prompt version")

    def get_golden_set(self, *, org_id: UUID | str, dataset_version_id: str) -> dict[str, Any]:
        return self._owned(self.golden_sets, _uuid(org_id, "org_id"), dataset_version_id, "golden set")

    def get_thresholds(self, *, org_id: UUID | str, threshold_version_id: str) -> dict[str, Any]:
        return self._owned(self.thresholds, _uuid(org_id, "org_id"), threshold_version_id, "threshold version")

    def get_run(self, *, org_id: UUID | str, run_id: str) -> dict[str, Any]:
        return self._owned(self.runs, _uuid(org_id, "org_id"), run_id, "evaluation run")

    def audit_for(self, *, org_id: UUID | str) -> tuple[dict[str, Any], ...]:
        tenant = _uuid(org_id, "org_id")
        return tuple(deepcopy(item) for item in self.audit if item["org_id"] == tenant)

    def _build_run(
        self, *, tenant: str, actor: str, trace: str, request_hash: str,
        prompt: Mapping[str, Any], dataset: Mapping[str, Any], threshold: Mapping[str, Any],
        config_id: str, configured_model: str, baseline: Mapping[str, Any] | None,
        results: Sequence[Mapping[str, Any]], total_cost: int, model_versions: list[str], started_at: str,
    ) -> dict[str, Any]:
        count = len(results)
        passed = sum(item["status"] == "passed" for item in results)
        failed = sum(item["status"] == "failed" for item in results)
        errors = sum(item["status"] == "error" for item in results)
        exact_ratio = passed / count
        error_ratio = errors / count
        max_case_cost = max((int(item["cost_cents"]) for item in results), default=0)
        reasons: list[str] = []
        if exact_ratio < threshold["min_exact_match_ratio"]:
            reasons.append("MIN_EXACT_MATCH_RATIO_NOT_MET")
        if error_ratio > threshold["max_error_ratio"]:
            reasons.append("MAX_ERROR_RATIO_EXCEEDED")
        if total_cost > threshold["max_total_cost_cents"]:
            reasons.append("MAX_TOTAL_COST_EXCEEDED")
        if max_case_cost > threshold["max_cost_per_case_cents"]:
            reasons.append("MAX_COST_PER_CASE_EXCEEDED")
        quality_delta: float | None = None
        cost_increase: float | None = None
        if baseline is not None:
            quality_delta = round(exact_ratio - baseline["metrics"]["exact_match_ratio"], 6)
            if -quality_delta > threshold["max_quality_drop"]:
                reasons.append("QUALITY_REGRESSION_EXCEEDED")
            baseline_cost = int(baseline["metrics"]["total_cost_cents"])
            if baseline_cost == 0:
                if total_cost > 0:
                    reasons.append("COST_REGRESSION_EXCEEDED")
            else:
                cost_increase = round((total_cost - baseline_cost) / baseline_cost, 6)
                if cost_increase > threshold["max_cost_increase_ratio"]:
                    reasons.append("COST_REGRESSION_EXCEEDED")
        metrics = {
            "exact_match_ratio": round(exact_ratio, 6),
            "error_ratio": round(error_ratio, 6),
            "total_cost_cents": total_cost,
            "average_cost_cents": round(total_cost / count, 6),
            "max_case_cost_cents": max_case_cost,
            "quality_delta": quality_delta,
            "cost_increase_ratio": cost_increase,
        }
        return {
            "id": str(uuid4()),
            "org_id": tenant,
            "prompt_version_id": prompt["id"],
            "prompt_version": prompt["version_ref"],
            "prompt_hash": prompt["content_hash"],
            "model_config_id": config_id,
            "configured_model": configured_model,
            "model_versions": model_versions,
            "dataset_version_id": dataset["id"],
            "dataset_hash": dataset["dataset_hash"],
            "threshold_version_id": threshold["id"],
            "threshold_hash": threshold["content_hash"],
            "baseline_run_id": None if baseline is None else baseline["id"],
            "status": "completed",
            "gate_status": "passed" if not reasons else "failed",
            "case_count": count,
            "passed_cases": passed,
            "failed_cases": failed,
            "error_cases": errors,
            "metrics": metrics,
            "regression_reasons": sorted(set(reasons)),
            "results": [deepcopy(dict(item)) for item in results],
            "request_hash": request_hash,
            "trace_id": trace,
            "created_by": actor,
            "created_at": started_at,
            "completed_at": self._now(),
        }

    @staticmethod
    def _error_result(case: Mapping[str, Any], error_code: str) -> dict[str, Any]:
        return {
            "case_id": case["case_id"],
            "status": "error",
            "exact_match": False,
            "expected_output_hash": _hash(case["expected_output"]),
            "output_hash": None,
            "model_call_id": None,
            "model_version": None,
            "cost_cents": 0,
            "latency_ms": None,
            "error_code": error_code,
        }

    def _store_version(
        self, kind: str, tenant: str, name: str, number: int, key: str,
        payload_hash: str, value: Mapping[str, Any], trace: str,
    ) -> dict[str, Any]:
        stores = {"prompt": self.prompts, "golden_set": self.golden_sets, "threshold": self.thresholds}
        stored = deepcopy(dict(value))
        stores[kind][stored["id"]] = stored
        self._latest[(tenant, kind, name)] = number
        self._idempotency[(tenant, key)] = (payload_hash, kind, stored["id"])
        self.audit.append({
            "event_type": f"evaluation.{kind}.registered",
            "org_id": tenant,
            "actor_id": stored["created_by"],
            "trace_id": trace,
            "subject_id": stored["id"],
            "content_hash": stored.get("content_hash", stored.get("dataset_hash")),
            "version_no": number,
        })
        return deepcopy(stored)

    def _replay(
        self, tenant: str, key: str, payload_hash: str, expected_kind: str,
        store: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        cached = self._idempotency.get((tenant, key))
        if cached is None:
            return None
        if cached[0] != payload_hash or cached[1] != expected_kind:
            raise EvaluationError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
        return deepcopy(dict(store[cached[2]]))

    def _assert_next(self, tenant: str, kind: str, name: str, number: int, previous: int) -> None:
        current = self._latest.get((tenant, kind, name), 0)
        if previous != current or number != current + 1:
            raise EvaluationError("VERSION_CONFLICT", "expected previous version or next version is stale")

    def _context(
        self, org_id: UUID | str, actor_id: UUID | str, trace_id: str, idempotency_key: str,
    ) -> tuple[str, str, str, str]:
        tenant = _uuid(org_id, "org_id")
        actor = _uuid(actor_id, "actor_id")
        trace = _nonempty(trace_id, "trace_id")
        key = _nonempty(idempotency_key, "idempotency_key")
        if len(key) < 8 or len(key) > 200:
            raise EvaluationError("INVALID_EVALUATION_CONTEXT", "idempotency_key length must be 8..200")
        return tenant, actor, trace, key

    @staticmethod
    def _key(value: object, field: str) -> str:
        text = _nonempty(value, field)
        if not KEY.fullmatch(text):
            raise EvaluationError("INVALID_REGISTRY_KEY", f"{field} has an invalid format")
        return text

    def _schema_ref(self, value: object) -> str:
        ref = _nonempty(value, "schema_ref")
        if ref not in self.schema_registry:
            raise EvaluationError("UNKNOWN_SCHEMA_REF", "schema reference is not registered")
        Draft202012Validator.check_schema(self.schema_registry[ref])
        return ref

    def _validate_schema(self, ref: str, value: Any, code: str) -> None:
        try:
            Draft202012Validator(self.schema_registry[ref], format_checker=FormatChecker()).validate(value)
        except ValidationError as exc:
            raise EvaluationError(code, f"value failed {ref}") from exc

    def _cases(
        self, cases: Sequence[Mapping[str, Any]], input_ref: str, output_ref: str,
    ) -> list[dict[str, Any]]:
        if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence) or not cases:
            raise EvaluationError("INVALID_GOLDEN_SET", "golden set requires at least one case")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in cases:
            if not isinstance(raw, Mapping):
                raise EvaluationError("INVALID_GOLDEN_SET", "each golden case must be an object")
            if not set(raw).issubset({"case_id", "input", "expected_output", "tags"}):
                raise EvaluationError("INVALID_GOLDEN_SET", "golden case contains unknown fields")
            case_id = self._key(raw.get("case_id"), "case_id")
            if case_id in seen:
                raise EvaluationError("INVALID_GOLDEN_SET", "case_id must be unique")
            seen.add(case_id)
            if "input" not in raw or "expected_output" not in raw:
                raise EvaluationError("INVALID_GOLDEN_SET", "each case requires input and expected_output")
            if not isinstance(raw["input"], Mapping):
                raise EvaluationError("INVALID_GOLDEN_SET", "golden case input must be an object")
            self._validate_schema(input_ref, raw["input"], "GOLDEN_INPUT_SCHEMA_INVALID")
            self._validate_schema(output_ref, raw["expected_output"], "GOLDEN_OUTPUT_SCHEMA_INVALID")
            tags = raw.get("tags", [])
            if isinstance(tags, (str, bytes)) or not isinstance(tags, Sequence) or any(not isinstance(tag, str) or not tag for tag in tags):
                raise EvaluationError("INVALID_GOLDEN_SET", "tags must be non-empty strings")
            normalized.append({
                "case_id": case_id,
                "input": deepcopy(raw["input"]),
                "expected_output": deepcopy(raw["expected_output"]),
                "tags": sorted(set(tags)),
            })
        return sorted(normalized, key=lambda item: item["case_id"])

    @staticmethod
    def _variables(values: Sequence[str]) -> list[str]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise EvaluationError("INVALID_PROMPT_VARIABLE", "variables must be an array")
        result = list(values)
        if len(set(result)) != len(result) or any(not isinstance(item, str) or not VARIABLE.fullmatch(item) for item in result):
            raise EvaluationError("INVALID_PROMPT_VARIABLE", "variables must be unique simple identifiers")
        return result

    @staticmethod
    def _template_variables(template: str) -> list[str]:
        fields: list[str] = []
        try:
            for _, field, format_spec, conversion in Formatter().parse(template):
                if field is None:
                    continue
                if not VARIABLE.fullmatch(field) or format_spec or conversion:
                    raise EvaluationError("INVALID_PROMPT_TEMPLATE", "only simple placeholders are allowed")
                fields.append(field)
        except ValueError as exc:
            raise EvaluationError("INVALID_PROMPT_TEMPLATE", "prompt template braces are invalid") from exc
        return fields

    @staticmethod
    def _render(prompt: Mapping[str, Any], inputs: Mapping[str, Any]) -> str:
        if not isinstance(inputs, Mapping):
            raise EvaluationError("INVALID_GOLDEN_SET", "prompt inputs must be an object")
        values: dict[str, str] = {}
        for variable in prompt["variables"]:
            if variable not in inputs:
                raise EvaluationError("PROMPT_VARIABLE_MISMATCH", f"missing prompt input: {variable}")
            raw = inputs[variable]
            values[variable] = raw if isinstance(raw, str) else _canonical(raw)
        return str(prompt["template"]).format_map(values)

    @staticmethod
    def _owned(
        store: Mapping[str, Mapping[str, Any]], tenant: str, identity: object, label: str,
    ) -> dict[str, Any]:
        value = store.get(str(identity))
        if value is None or value["org_id"] != tenant:
            raise EvaluationError("TENANT_SCOPE_VIOLATION", f"{label} does not belong to organization")
        return deepcopy(dict(value))

    def _now(self) -> str:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise EvaluationError("INVALID_CLOCK", "clock must return a timezone-aware datetime")
        return value.isoformat()

    def _validate_contract(self, name: str, value: Mapping[str, Any]) -> None:
        try:
            Draft202012Validator(self._contracts[name], format_checker=FormatChecker()).validate(value)
        except ValidationError as exc:
            raise EvaluationError("EVALUATION_CONTRACT_INVALID", f"result failed {name}") from exc
