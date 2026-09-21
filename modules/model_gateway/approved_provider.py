"""Conditionally enabled external model provider with Fake fallback.

The adapter owns no SDK and performs no network access itself.  A reviewed
transport is injected by the runtime.  Tests use only an in-memory transport.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validate

from .service import FakeModelProvider, ModelError, ModelPort, ModelRequest, ModelResponse


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads((_ROOT / "packages/contracts/jsonschema/approved-model-provider.schema.json").read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FormatChecker())


@dataclass(frozen=True)
class ApprovedProviderEvidence:
    vendor_id: str
    environment: str
    processing_regions: tuple[str, ...]
    selected_data_region: str
    retention_days: int
    contract_ref: str
    dpa_ref: str
    subprocessors_review_ref: str
    exit_plan_ref: str
    deletion_proof_ref: str
    owner_approval_ref: str
    terms_version: str
    max_timeout_ms: int
    max_cost_cents_per_call: int

    def as_contract(self, *, credential_ref_present: bool) -> dict[str, Any]:
        return {
            "vendor_id": self.vendor_id,
            "category": "model",
            "selection_status": "approved",
            "environment": self.environment,
            "processing_regions": list(self.processing_regions),
            "selected_data_region": self.selected_data_region,
            "retention_days": self.retention_days,
            "contract_ref": self.contract_ref,
            "dpa_ref": self.dpa_ref,
            "subprocessors_review_ref": self.subprocessors_review_ref,
            "exit_plan_ref": self.exit_plan_ref,
            "deletion_proof_ref": self.deletion_proof_ref,
            "owner_approval_ref": self.owner_approval_ref,
            "terms_version": self.terms_version,
            "credential_ref_present": credential_ref_present,
            "max_timeout_ms": self.max_timeout_ms,
            "max_cost_cents_per_call": self.max_cost_cents_per_call,
            "fallback_provider": "fake",
            "status": "active",
        }

    def validate(self, *, credential_ref_present: bool) -> dict[str, Any]:
        contract = self.as_contract(credential_ref_present=credential_ref_present)
        errors = sorted(_VALIDATOR.iter_errors(contract), key=lambda error: list(error.path))
        if errors:
            raise ModelError("PROVIDER_EVIDENCE_INVALID", errors[0].message)
        if self.selected_data_region not in self.processing_regions:
            raise ModelError("PROVIDER_DATA_REGION_NOT_APPROVED", "selected region is outside approved processing regions")
        return contract


@dataclass(frozen=True)
class TransportResponse:
    output: Any
    model_version: str
    input_tokens: int
    output_tokens: int
    cost_cents: int
    latency_ms: int
    finish_reason: str = "stop"


class ProviderTransport(Protocol):
    def invoke(self, *, request: ModelRequest, credential_ref: str) -> TransportResponse: ...


class ApprovedExternalProvider:
    """ModelPort guarded by vendor evidence, environment and credential reference."""

    def __init__(
        self, *, evidence: ApprovedProviderEvidence, model_version: str,
        transport: ProviderTransport, credential_ref: str | None,
        fallback: ModelPort | None = None,
        schema_registry: Mapping[str, dict[str, Any]] | None = None,
    ) -> None:
        self.evidence = evidence
        self.provider = evidence.vendor_id
        self.model_version = model_version
        self.transport = transport
        self.credential_ref = credential_ref
        self.fallback = fallback or FakeModelProvider(schema_registry=schema_registry)
        self.schema_registry = dict(schema_registry or {})
        self.transport_call_count = 0
        self.routes: dict[str, dict[str, Any]] = {}
        if credential_ref is not None and (not isinstance(credential_ref, str) or not credential_ref.startswith("secretref://") or len(credential_ref) > 512):
            raise ModelError("PROVIDER_CREDENTIAL_REF_INVALID", "credential must be an opaque secretref:// reference")
        self.evidence_contract = evidence.validate(credential_ref_present=credential_ref is not None)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.timeout_ms <= 0 or request.timeout_ms > self.evidence.max_timeout_ms:
            raise ModelError("MODEL_TIMEOUT_POLICY_EXCEEDED", "request timeout exceeds the approved provider limit")
        if request.budget_cents < 0 or request.budget_cents > self.evidence.max_cost_cents_per_call:
            raise ModelError("MODEL_BUDGET_POLICY_EXCEEDED", "request budget exceeds the approved provider limit")
        if self.credential_ref is None:
            return self._fallback(request, "credential_unavailable")
        try:
            self.transport_call_count += 1
            response = self.transport.invoke(request=request, credential_ref=self.credential_ref)
            self._validate_transport_response(request, response)
        except ModelError as exc:
            if exc.code in {"MODEL_TIMEOUT", "PROVIDER_UNAVAILABLE"}:
                return self._fallback(request, exc.code.lower())
            raise
        result = ModelResponse(
            response.output, self.provider, response.model_version,
            {"input_tokens": response.input_tokens, "output_tokens": response.output_tokens},
            response.cost_cents, response.latency_ms, response.finish_reason, request.request_hash,
        )
        self.routes[request.request_hash] = {
            "configured_provider": self.provider, "actual_provider": self.provider,
            "fallback_reason": None, "terms_version": self.evidence.terms_version,
            "data_region": self.evidence.selected_data_region,
        }
        return result

    def _fallback(self, request: ModelRequest, reason: str) -> ModelResponse:
        response = self.fallback.generate(request)
        self.routes[request.request_hash] = {
            "configured_provider": self.provider, "actual_provider": response.provider,
            "fallback_reason": reason, "terms_version": self.evidence.terms_version,
            "data_region": self.evidence.selected_data_region,
        }
        return response

    def _validate_transport_response(self, request: ModelRequest, response: TransportResponse) -> None:
        if not isinstance(response, TransportResponse):
            raise ModelError("PROVIDER_RESPONSE_INVALID", "transport returned an invalid response")
        if not response.model_version or response.input_tokens < 0 or response.output_tokens < 0 or response.cost_cents < 0 or response.latency_ms < 0:
            raise ModelError("PROVIDER_RESPONSE_INVALID", "transport response metadata is invalid")
        if response.latency_ms > request.timeout_ms:
            raise ModelError("MODEL_TIMEOUT", "external provider exceeded the request timeout")
        if response.cost_cents > request.budget_cents:
            raise ModelError("MODEL_BUDGET_EXCEEDED", "external provider exceeded the request budget")
        if request.response_schema_ref:
            schema = self.schema_registry.get(request.response_schema_ref)
            if schema is None:
                raise ModelError("MODEL_OUTPUT_SCHEMA_INVALID", "response schema reference is unknown")
            try:
                validate(response.output, schema)
            except ValidationError as exc:
                raise ModelError("MODEL_OUTPUT_SCHEMA_INVALID", "external output failed response schema") from exc

    def route_for(self, request_hash: str) -> Mapping[str, Any] | None:
        route = self.routes.get(request_hash)
        return None if route is None else dict(route)


__all__ = ["ApprovedExternalProvider", "ApprovedProviderEvidence", "ProviderTransport", "TransportResponse"]
