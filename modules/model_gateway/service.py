"""Provider-neutral model Port and deterministic Fake provider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from threading import RLock
import time
from typing import Any, Mapping, Protocol

from jsonschema import ValidationError, validate

from .budget import BudgetError, BudgetService


class ModelError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ModelRequest:
    model_id: str
    prompt_version: str
    input: Any
    response_schema_ref: str | None
    timeout_ms: int
    budget_cents: int
    trace_id: str
    org_id: str | None = None
    task_id: str | None = None

    @property
    def request_hash(self) -> str:
        payload = {"model_id": self.model_id, "prompt_version": self.prompt_version, "input": self.input, "response_schema_ref": self.response_schema_ref}
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class ModelResponse:
    output: Any
    provider: str
    model_version: str
    usage: dict[str, int]
    cost_cents: int
    latency_ms: int
    finish_reason: str
    request_hash: str

    def as_contract(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "provider": self.provider,
            "model_version": self.model_version,
            "usage": self.usage,
            "cost_cents": self.cost_cents,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "request_hash": self.request_hash,
        }


class ModelPort(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse: ...


class FakeModelProvider:
    """A deterministic provider with no network, secret, or prompt logging."""

    provider = "fake"
    model_version = "fake-v1"

    def __init__(self, *, fixtures: Mapping[str, Any] | None = None, latency_ms: int = 1, cost_cents: int = 1, schema_registry: Mapping[str, dict[str, Any]] | None = None) -> None:
        self.fixtures = dict(fixtures or {})
        self.latency_ms = latency_ms
        self.cost_cents = cost_cents
        self.schema_registry = dict(schema_registry or {})
        self.call_count = 0

    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.timeout_ms <= 0 or self.latency_ms > request.timeout_ms:
            raise ModelError("MODEL_TIMEOUT", "model deadline exceeded")
        if self.cost_cents > request.budget_cents:
            raise ModelError("MODEL_BUDGET_EXCEEDED", "model budget is insufficient")
        output = self.fixtures.get(request.request_hash, {"fixture": request.request_hash[:16]})
        if request.response_schema_ref:
            schema = self.schema_registry.get(request.response_schema_ref)
            if schema is None:
                raise ModelError("MODEL_OUTPUT_SCHEMA_INVALID", "response schema reference is unknown")
            try:
                validate(output, schema)
            except ValidationError as exc:
                raise ModelError("MODEL_OUTPUT_SCHEMA_INVALID", "fake output failed response schema") from exc
        started = time.perf_counter()
        self.call_count += 1
        latency_ms = max(self.latency_ms, int((time.perf_counter() - started) * 1000))
        output_tokens = max(1, len(json.dumps(output, ensure_ascii=True)) // 4)
        return ModelResponse(output, self.provider, self.model_version, {"input_tokens": max(1, len(json.dumps(request.input)) // 4), "output_tokens": output_tokens}, self.cost_cents, latency_ms, "stop", request.request_hash)


@dataclass(frozen=True)
class ModelGatewayConfig:
    id: str
    org_id: str
    provider: str
    model: str
    status: str
    data_region: str
    retention_policy: str
    created_at: str


@dataclass(frozen=True)
class ModelCallRecord:
    id: str
    org_id: str
    model_config_id: str
    provider: str
    model: str
    model_version: str
    prompt_version: str
    request_hash: str
    input_hash: str
    output_hash: str | None
    status: str
    input_tokens: int | None
    output_tokens: int | None
    cost_cents: int | None
    latency_ms: int | None
    attempt_no: int
    error_code: str | None
    response_ref: str | None
    created_at: str
    output: Any = None
    task_id: str | None = None

    def as_contract(self) -> dict[str, Any]:
        return {key: value for key, value in self.__dict__.items() if key != "output"}


class ModelGateway:
    """Tenant-scoped gateway that accepts only explicitly registered providers."""

    def __init__(self, providers: Mapping[str, ModelPort] | None = None, *, budget_service: BudgetService | None = None) -> None:
        self.providers: dict[str, ModelPort] = dict(providers or {"fake": FakeModelProvider()})
        self.budget_service = budget_service
        self.configs: dict[str, ModelGatewayConfig] = {}
        self.provider_evidence: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, ModelCallRecord] = {}
        self.idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self.events: list[dict[str, Any]] = []
        self._lock = RLock()

    def register_budget_policy(self, **values: Any) -> dict[str, Any]:
        if self.budget_service is None:
            raise ModelError("BUDGET_SERVICE_UNAVAILABLE", "budget service is not configured")
        try:
            return self.budget_service.register_policy(**values).as_contract()
        except BudgetError as exc:
            raise ModelError(exc.code, str(exc)) from exc

    def register_config(self, *, org_id: str, provider: str, model: str, data_region: str, retention_policy: str) -> ModelGatewayConfig:
        if provider != "fake" or provider not in self.providers:
            raise ModelError("PROVIDER_NOT_ALLOWED_IN_MVP", "only the fake provider is enabled")
        config = ModelGatewayConfig(f"cfg-{len(self.configs) + 1}", org_id, provider, model, "active", data_region, retention_policy, datetime.now(timezone.utc).isoformat())
        self.configs[config.id] = config
        return config

    def register_approved_config(self, *, org_id: str, provider: str, model: str,
                                 environment: str, data_region: str,
                                 retention_policy: str) -> ModelGatewayConfig:
        """Register a conditional dev/staging provider after evidence validation."""
        from .approved_provider import ApprovedExternalProvider

        adapter = self.providers.get(provider)
        if not isinstance(adapter, ApprovedExternalProvider):
            raise ModelError("PROVIDER_NOT_APPROVED", "provider has no approved external adapter")
        evidence = adapter.evidence_contract
        if environment not in {"dev", "staging"} or environment != evidence["environment"]:
            raise ModelError("PROVIDER_ENVIRONMENT_NOT_ALLOWED", "external providers are limited to their approved dev/staging environment")
        if data_region != evidence["selected_data_region"]:
            raise ModelError("PROVIDER_DATA_REGION_NOT_APPROVED", "configured data region differs from approved evidence")
        if not isinstance(retention_policy, str) or not retention_policy.strip():
            raise ModelError("PROVIDER_RETENTION_INVALID", "retention policy is required")
        config = ModelGatewayConfig(
            f"cfg-{len(self.configs) + 1}", org_id, provider, model, "active",
            data_region, retention_policy.strip(), datetime.now(timezone.utc).isoformat(),
        )
        self.configs[config.id] = config
        self.provider_evidence[config.id] = dict(evidence)
        return config

    def call(self, *, org_id: str, config_id: str, request: ModelRequest, idempotency_key: str, max_retries: int = 0) -> ModelCallRecord:
        with self._lock:
            return self._call_locked(
                org_id=org_id, config_id=config_id, request=request,
                idempotency_key=idempotency_key, max_retries=max_retries,
            )

    def _call_locked(self, *, org_id: str, config_id: str, request: ModelRequest, idempotency_key: str, max_retries: int = 0) -> ModelCallRecord:
        config = self.configs.get(config_id)
        if config is None or config.org_id != org_id:
            raise ModelError("TENANT_SCOPE_VIOLATION", "model config does not belong to organization")
        if config.status != "active":
            raise ModelError("PROVIDER_UNAVAILABLE", "model config is disabled")
        if request.org_id is not None and request.org_id != org_id:
            raise ModelError("TENANT_SCOPE_VIOLATION", "model request does not belong to organization")
        payload_hash = sha256(json.dumps([config_id, request.request_hash, request.budget_cents], sort_keys=True).encode()).hexdigest()
        cached = self.idempotency.get((org_id, idempotency_key))
        if cached:
            if cached[0] != payload_hash:
                raise ModelError("IDEMPOTENCY_KEY_REUSED", "idempotency key payload differs")
            return self.calls[cached[1]]
        call_id = f"call-{len(self.calls) + 1}"
        task_id = request.task_id or "unscoped"
        reservation = None
        if self.budget_service is not None:
            try:
                reservation, decision = self.budget_service.reserve(
                    org_id=org_id,
                    task_id=task_id,
                    model=config.model,
                    requested_cents=request.budget_cents,
                    idempotency_key=idempotency_key,
                    trace_id=request.trace_id,
                )
            except BudgetError as exc:
                raise ModelError(exc.code, str(exc)) from exc
            if not decision.allowed:
                record = self._failure_record(
                    call_id=call_id,
                    org_id=org_id,
                    config=config,
                    request=request,
                    task_id=task_id,
                    attempt_no=0,
                    error_code="BUDGET_EXCEEDED",
                    status="budget_exceeded",
                )
                self.calls[call_id] = record
                self.idempotency[(org_id, idempotency_key)] = (payload_hash, call_id)
                self.events.append({
                    "type": "model.call.failed",
                    "call_id": call_id,
                    "org_id": org_id,
                    "task_id": task_id,
                    "trace_id": request.trace_id,
                    "error_code": "BUDGET_EXCEEDED",
                })
                raise ModelError("BUDGET_EXCEEDED", "model budget policy denied the request")
        evidence = self.provider_evidence.get(config_id)
        self.events.append({"type": "model.call.started", "call_id": call_id, "org_id": org_id,
                            "task_id": task_id, "trace_id": request.trace_id,
                            "configured_provider": config.provider,
                            "terms_version": None if evidence is None else evidence["terms_version"],
                            "data_region": config.data_region})
        provider = self.providers[config.provider]
        attempts = max(0, max_retries) + 1
        last_error: ModelError | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = provider.generate(request)
                if response.cost_cents < 0 or response.cost_cents > request.budget_cents:
                    raise ModelError("MODEL_COST_INVALID", "provider cost exceeds the request budget")
                output_hash = sha256(json.dumps(response.output, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                record = ModelCallRecord(
                    id=call_id, org_id=org_id, model_config_id=config_id,
                    provider=response.provider, model=config.model,
                    model_version=response.model_version, prompt_version=request.prompt_version,
                    request_hash=request.request_hash,
                    input_hash=sha256(json.dumps(request.input, sort_keys=True).encode()).hexdigest(),
                    output_hash=output_hash, status="succeeded",
                    input_tokens=response.usage.get("input_tokens"),
                    output_tokens=response.usage.get("output_tokens"), cost_cents=response.cost_cents,
                    latency_ms=response.latency_ms, attempt_no=attempt, error_code=None,
                    response_ref=None, created_at=datetime.now(timezone.utc).isoformat(),
                    output=response.output, task_id=task_id,
                )
                if reservation is not None:
                    try:
                        self.budget_service.settle(
                            reservation_id=reservation.id, call_id=call_id,
                            actual_cost_cents=response.cost_cents, status="succeeded",
                        )
                    except BudgetError as exc:
                        raise ModelError(exc.code, str(exc)) from exc
                self.calls[call_id] = record
                self.idempotency[(org_id, idempotency_key)] = (payload_hash, call_id)
                route_reader = getattr(provider, "route_for", None)
                route = route_reader(request.request_hash) if callable(route_reader) else None
                self.events.append({"type": "model.call.succeeded", "call_id": call_id, "org_id": org_id,
                                    "task_id": task_id, "trace_id": request.trace_id,
                                    "configured_provider": config.provider,
                                    "actual_provider": response.provider,
                                    "fallback_reason": None if route is None else route.get("fallback_reason"),
                                    "terms_version": None if evidence is None else evidence["terms_version"],
                                    "data_region": config.data_region, "cost_cents": response.cost_cents,
                                    "latency_ms": response.latency_ms})
                return record
            except ModelError as exc:
                last_error = exc
                if exc.code not in {"MODEL_TIMEOUT", "PROVIDER_UNAVAILABLE"} or attempt == attempts:
                    break
        assert last_error is not None
        if reservation is not None:
            try:
                self.budget_service.settle(
                    reservation_id=reservation.id, call_id=call_id,
                    actual_cost_cents=0, status="timed_out" if last_error.code == "MODEL_TIMEOUT" else "failed",
                )
            except BudgetError:
                pass
        status = "timed_out" if last_error.code == "MODEL_TIMEOUT" else "budget_exceeded" if last_error.code in {"MODEL_BUDGET_EXCEEDED", "BUDGET_EXCEEDED"} else "failed"
        record = self._failure_record(
            call_id=call_id, org_id=org_id, config=config, request=request,
            task_id=task_id, attempt_no=attempts, error_code=last_error.code, status=status,
        )
        self.calls[call_id] = record
        self.idempotency[(org_id, idempotency_key)] = (payload_hash, call_id)
        self.events.append({"type": "model.call.failed", "call_id": call_id, "org_id": org_id,
                            "task_id": task_id, "trace_id": request.trace_id, "error_code": last_error.code})
        raise last_error

    @staticmethod
    def _failure_record(*, call_id: str, org_id: str, config: ModelGatewayConfig,
                        request: ModelRequest, task_id: str, attempt_no: int,
                        error_code: str, status: str) -> ModelCallRecord:
        return ModelCallRecord(
            id=call_id, org_id=org_id, model_config_id=config.id,
            provider=config.provider, model=config.model, model_version="unknown",
            prompt_version=request.prompt_version, request_hash=request.request_hash,
            input_hash=sha256(json.dumps(request.input, sort_keys=True).encode()).hexdigest(),
            output_hash=None, status=status, input_tokens=None, output_tokens=None,
            cost_cents=None, latency_ms=None, attempt_no=attempt_no, error_code=error_code,
            response_ref=None, created_at=datetime.now(timezone.utc).isoformat(),
            task_id=task_id,
        )

    def get_call(self, *, org_id: str, call_id: str) -> ModelCallRecord:
        record = self.calls.get(call_id)
        if record is None or record.org_id != org_id:
            raise ModelError("TENANT_SCOPE_VIOLATION", "model call does not belong to organization")
        return record

    def get_provider_evidence(self, *, org_id: str, config_id: str) -> dict[str, Any]:
        config = self.configs.get(config_id)
        if config is None or config.org_id != org_id:
            raise ModelError("TENANT_SCOPE_VIOLATION", "model config does not belong to organization")
        evidence = self.provider_evidence.get(config_id)
        if evidence is None:
            raise ModelError("PROVIDER_EVIDENCE_NOT_APPLICABLE", "config does not use an external provider")
        return dict(evidence)
